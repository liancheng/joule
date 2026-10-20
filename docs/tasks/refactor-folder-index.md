# Refactor of `FolderIndex`

Joule has two layers:

- **The service layer** controls concurrency and parallelism. It uses `asyncio` so that the server stays responsive, and process pools so that large builds are fast. It is difficult to test this layer with `unittest`.
- **The core layer** is synchronous and has the core logic. It is easy to test.

`FolderIndex` has parts of the two layers. It also needs new functions:

1. `resolve_document` must cache the resolved documents. The cache must change when somebody creates, deletes, or edits a file.
2. `ImportGraph` must also change on the same events.

Proposal:

- Rename the current `FolderIndex` to `FolderService`. It is in the service layer.
- Add a new `FolderIndex` class in the core layer. It holds the `ImportGraph` and the cache of resolved documents.
- Divide `ImportGraphBuilder` in the same way:
  - `ImportGraphBuilder.do_build(docs, map)` does the build with the `map` function that it gets.
  - `ImportGraphBuilder.build(docs)` calls `do_build` with the builtin `map`. The build is sequential, so the tests can use it.
  - `ParallelImportGraphBuilder.build(docs)` calls `do_build` with `ProcessPoolExecutor.map`. Production code uses it. The callers do not create an executor.

#### Design decision: Which class owns `resolve_document`?

1. `ImportGraph`.
   - **Pros:** The import graph and the document cache change on the same events.
   - **Cons:** The two have different data and different invalidation rules. The graph holds only paths and sets. The cache holds large trees, and it needs an eviction policy.
2. `FolderIndex`.
   - **Pros:** `ImportGraph` stays a pure graph. `FolderIndex` holds the graph and the cache, so it can apply the rules that need both. An example is: "If document B changes, also invalidate the documents in `imported_by[B]`." Cross-document analysis needs this rule.
   - **Cons:** One more class.

Joule takes option 2. `FolderIndex` gets each event. It updates the graph first, and then it invalidates the cache.

#### Design decision: Where does the process pool go?

1. `ImportGraphBuilder.build` creates the pool, as before.
   - **Pros:** No change.
   - **Cons:** The core layer starts processes. The tests must build the graph only one time, in `setUpClass`.
2. `build` gets a `map` parameter.
   - **Pros:** The tests can build sequentially.
   - **Cons:** Each production caller must create a `ProcessPoolExecutor`.
3. `do_build` gets the `map` parameter. `build` is sequential, and `ParallelImportGraphBuilder.build` uses a pool.
   - **Pros:** The production callers get a parallel build with no setup. The tests get a cheap sequential build.
   - **Cons:** One more class.

Joule takes option 3.

### Concurrency rules

- `FolderIndex` is not thread-safe.
- `FolderService` is the only writer of its `FolderIndex`. The event handlers change the index on the event loop.
- The full build runs outside the event loop. One assignment publishes the result.
- Events that arrive during the initial build go into a queue. The service applies them after the build. Alternatively, it does a new build. See "Bursts of file events" in [TODO.md](../TODO.md).
- Requests for single-document features do not wait for the import graph.

## Plan

Each step is one commit. After each step, all tests must pass. Verify each step with:

- `./test.sh`, ruff, and `ty check`.
- `joule benchmark` on grafonnet and on a large monorepo. The document, edge, and malformed counts must be the same as before the step. Before step 1, grafonnet has 1,413 edges.

### Progress

- [x] Step 1: Split `FolderService` and `FolderIndex`, and add `ParallelImportGraphBuilder`
- [ ] Step 2: Refactor `TestImportGraphBuilder`
- [ ] Step 3: Update the index on file events
- [ ] Step 4: Cache the resolved documents

### Step 1: Split `FolderService` and `FolderIndex`, and add `ParallelImportGraphBuilder`

Make the structural changes. Do not add the cache or the event handlers.

- `FolderService(folder, config)` does the discovery with `fd` and the build in `asyncio.to_thread`. It also gives `ready` and its `index`.
- `FolderIndex(root, jpaths)` holds `import_graph` and `resolve_document`.
- Put all the code of the service layer into the `joule.server` package:
  - `_language_server.py`: `JouleLanguageServer`, `server`, `load_config`, and the LSP handlers.
  - `_folder_service.py`: `FolderService`.
  - `__init__.py`: re-exports these names. The import of `_language_server` also registers the handlers.
- `joule.workspace` keeps `discover_docs` and `FolderIndex`. It does not use `asyncio`.
- Add `ImportGraphBuilder.do_build`, `ImportGraphBuilder.build`, and `ParallelImportGraphBuilder`.
- `TestImportGraphBuilder` uses the sequential builder. One test makes sure that the parallel build gives the same graph.

Also fix these issues:

- `joule benchmark` fails, because it calls `FolderIndex.discover_docs`, which does not exist.
- `server.py` has a module-level `resolve_document` and an import of `resolve` that nothing uses.
- `FolderIndex.start` calculates the root two times, in two different ways.

Commit: ``refactor: Split `FolderService` out of `FolderIndex` ``

### Step 2: Refactor `TestImportGraphBuilder`

The user does this step manually. The new tests use a testing DSL, so that they are easier to read.

### Step 3: Update the index on file events

- Add the event methods to `FolderIndex`. They update the import graph.
- Connect `workspace/didChangeWatchedFiles` to these methods through `FolderService`.
- Reuse the design of steps 4 and 5 of [refactor-import-graph.md](refactor-import-graph.md): the raw importees, the file-name index, and the tests that compare the result with a full build.

### Step 4: Cache the resolved documents

- Add an LRU cache of resolved documents to `FolderIndex`.
- Use the `(mtime_ns, size)` of the file as the cache key. For an open buffer, use the LSP version of the document. Then the cache of one document stays correct without events. The events are necessary only for invalidation across documents.
- Read the open buffers (`didOpen`, `didChange`, and `didClose`). They have priority over the files on the disk. At this time, `T.parse_document` reads only from the disk.

Step 4 does not need step 3. You can do it first.
