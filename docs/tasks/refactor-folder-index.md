# Refactor of `FolderIndex` and `ImportGraph`

The goal is a workspace index that changes when somebody creates, deletes, or edits a file. The index has two parts:

1. The import graph: the `imports` and `imported_by` edges, and the indices that Joule needs to update the edges.
2. The cache of resolved documents.

Joule has two layers:

- **The service layer** controls concurrency and parallelism. It uses `asyncio` so that the server stays responsive, and process pools so that large builds are fast. It is difficult to test this layer with `unittest`.
- **The core layer** is synchronous and has the core logic. It is easy to test.

The classes are:

| Class            | Layer   | Role                                                                                                           |
| ---------------- | ------- | -------------------------------------------------------------------------------------------------------------- |
| `FolderService`  | Service | Finds the documents, builds the index outside the event loop, and gets the LSP events of one workspace folder. |
| `FolderIndex`    | Core    | Holds the `ImportGraph` and the cache of resolved documents.                                                   |
| `ImportGraph`    | Core    | Builds the graph sequentially or with a process pool, and updates it on file events. Its indices are private.  |
| `ImportResolver` | Core    | Resolves importees like the file importer of Jsonnet, with caches that have a short life.                      |

#### Design decision: How long do the resolver caches live?

The caches record only if files exist. Thus they become incorrect after somebody creates or deletes a file.

1. Keep one resolver with the graph, and invalidate its caches on each event.
   - **Pros:** A resolution after an edit can use the caches.
   - **Cons:** The caches use much memory on large monorepos. They save only a few milliseconds on an incremental update. The invalidation rules are difficult to make correct.
2. Create a new `ImportResolver` for each bulk build or incremental update, and discard it after.
   - **Pros:** A cache with a short life is always correct. There is one implementation to test.
   - **Cons:** An incremental update starts with empty caches.

Joule takes option 2.

#### Design decision: Which class owns `resolve_document`?

1. `ImportGraph`.
   - **Pros:** The import graph and the document cache change on the same events.
   - **Cons:** The two have different data and different invalidation rules. The graph holds only paths and sets. The cache holds large trees, and it needs an eviction policy.
2. `FolderIndex`.
   - **Pros:** `ImportGraph` stays a pure graph. `FolderIndex` holds the graph and the cache, so it can apply the rules that need both. An example is: "If document B changes, also invalidate the documents in `imported_by[B]`." Cross-document analysis needs this rule.
   - **Cons:** One more class.

Joule takes option 2. `FolderIndex` gets each event. It updates the graph first, and then it invalidates the cache.

#### Design decision: Where does the process pool go?

1. `ImportGraphBuilder.build` creates the pool.
   - **Pros:** One class.
   - **Cons:** The core layer starts processes. The tests must build the graph only one time, in `setUpClass`.
2. `build` gets a `map` parameter.
   - **Pros:** The tests can build sequentially.
   - **Cons:** Each production caller must create a `ProcessPoolExecutor`.
3. `do_build` gets the `map` parameter. `ImportGraphBuilder.build` is sequential, and `ParallelImportGraphBuilder.build` uses a pool.
   - **Pros:** The production callers get a parallel build with no setup. The tests get a cheap sequential build.
   - **Cons:** One more class. The graph and its builders share the configuration (`root` and `jpaths`), so the update methods must get a resolver from the caller.
4. `ImportGraph` has two class methods, `build` and `build_in_parallel`. The graph keeps `root` and `jpaths`, and it makes a new resolver for each build and each event.
   - **Pros:** The production callers get a parallel build with no setup. The tests get a cheap sequential build. The interface shows no resolver, importees, or indices.
   - **Cons:** None found.

Joule takes option 4. Before, it took option 3.

### Concurrency rules

- `FolderIndex` is not thread-safe.
- `FolderService` is the only writer of its `FolderIndex`. The event handlers change the index on the event loop.
- The full build runs outside the event loop. One assignment publishes the complete index.
- Events that arrive before the index exists go into a queue. The service applies them after the build.
- Requests for single-document features do not wait for the index. Until the index exists, `FolderService.resolve_document` uses `workspace.resolve_document`, which has no cache.

## Plan

Each step is one commit. After each step, all tests must pass. Verify each step with:

- `./test.sh`, ruff, and `ty check`.
- `joule benchmark` on grafonnet and on a large monorepo. The document, edge, and malformed counts must be the same as before the step, and the build time must not increase. At this time, grafonnet has 1,413 edges.

### Progress

- [x] Edges as sets
- [x] Tests for the build of the import graph
- [x] Separate import resolution from the graph
- [x] Add `ImportGraphBuilder`
- [x] Split `FolderService` and `FolderIndex`, and add `ParallelImportGraphBuilder`
- [x] Build `FolderIndex` from a complete `ImportGraph`
- [x] Refactor the tests of the import graph
- [x] Keep the data for incremental updates
- [ ] Update the import graph incrementally
- [ ] Update the index on file events
- [ ] Cache the resolved documents

### Completed steps

- **Edges as sets.** `imports` and `imported_by` are `dict[Path, set[Path]]`. Thus the graph keeps one edge for each pair of files, and it can remove an edge in O(1).
- **Tests for the build.** The tests protect the subsequent steps.
- **Separate import resolution.** `ImportResolver(root, jpaths)` has the `_is_file`, `_same_dir`, and `_via_jpaths` caches. See the design decision about the resolver caches.
- **Add `ImportGraphBuilder`.** The builder does all the construction. `ImportGraph` is the result with a long life, and it has no caches.
- **Split `FolderService` and `FolderIndex`.** The `joule.server` package has all the code of the service layer: `JouleLanguageServer` and `FolderService`. `joule.workspace` keeps `discover_docs` and `FolderIndex`, and it does not use `asyncio`. `ParallelImportGraphBuilder` builds with a process pool.
- **Build `FolderIndex` from a complete `ImportGraph`.** `FolderIndex(import_graph)` gets `root` from the graph. `FolderService.index` is `None` until `start` publishes it. `FolderService.resolve_document` and `JouleLanguageServer.resolve_document` fall back to `workspace.resolve_document`. Thus single-document features also work before the build, and for documents outside the workspace folders.
- **Refactor the tests.** `TestImportGraph` and `TestImportResolver` use `FakeWorkspaceTestCase`. Each test declares its own documents and files.
- **Keep the data for incremental updates.** `ImportGraph.add_import` records each import, also an unresolved import. It sets these fields:

  - `importees: dict[Path, set[str]]`: the raw importee strings of each document. Joule needs them to resolve the importees again. The order and the duplicates are not important. A set also lets Joule compare the old and the new importees of a changed document.
  - `basename_imported_by: dict[str, set[Path]]`: a map from the file name of each importee (`P.basename(importee)`) to the documents that import it.

  When somebody creates a file, `basename_imported_by` finds all the imports that can resolve differently. It can select too many imports, but it never misses an import. The reason is that each candidate path of an importee ends with the file name of the importee. When somebody deletes a file, `imported_by` finds the affected imports exactly.

  The worker processes send a separate copy of each raw importee. Thus `add_import` interns the strings. The counts and the build times did not change. The memory of the graph increased as follows:

  | Workspace           | Edges | Raw imports | `imports` + `imported_by` | `importees` | `basename_imported_by` |
  | ------------------- | ----- | ----------- | ------------------------- | ----------- | ---------------------- |
  | grafonnet           | 1,413 | 1,790       | 0.91 MiB                  | 0.34 MiB    | 0.14 MiB               |
  | earthengine-catalog | 1,556 | 10,264      | 1.08 MiB                  | 1.39 MiB    | 0.59 MiB               |

  In earthengine-catalog, 8,708 of the imports do not resolve with the root as the only jpath. Thus `importees` is larger than the edges. TODO: Measure the memory on a large monorepo.

### Step: Update the import graph incrementally

Merge `ImportGraphBuilder` and `ParallelImportGraphBuilder` into `ImportGraph`. The interface is:

- `ImportGraph.build(root, jpaths, docs)` and `ImportGraph.build_in_parallel(root, jpaths, docs)`.
- The queries `imports_of(path)`, `importers_of(path)`, `edges()`, and `malformed`.
- The file events. Each event uses a new `ImportResolver`:
  - `file_created(path)`: resolve again the imports with the file name of `path`. A new file can shadow a candidate with a lower priority. It can also make an unresolved import resolve. This applies to all files, also to files that are not documents, such as `.json` import targets.
  - `file_changed(path)`: collect the importees of the document again, also if it is malformed. Then replace its edges, its index entries, and its entry in `malformed`.
  - `file_deleted(path)`: remove the edges from the file and its index entries. Then resolve again the imports in `importers_of(path)`. These imports can now resolve to a candidate with a lower priority.

The graph does not know which files are documents. That is a rule of the discovery, so `FolderService` applies it. When somebody creates a document, the service calls `file_created` and then `file_changed`.

Test each event against a full build:

1. Apply a change to a workspace of `FakeWorkspaceTestCase`.
2. Send the event to the graph.
3. Make sure that the graph is equal to a new graph that `ImportGraph.build` makes from the changed workspace. `ImportGraph.__eq__` compares all the data of the graph, also the private indices. Thus a test also finds an index entry that an event did not remove.

Commit: ``feat: Update `ImportGraph` incrementally on file changes``

### Step: Update the index on file events

- Add the event methods to `FolderIndex`. They call the methods of `ImportGraph`.
- Connect `workspace/didChangeWatchedFiles` to these methods through `FolderService`. Before the index exists, put the events in a queue, and apply them after the build.

Commit: ``feat: Update `FolderIndex` on file events``

### Step: Cache the resolved documents

- Add an LRU cache of resolved documents to `FolderIndex`.
- Use the `(mtime_ns, size)` of the file as the cache key. For an open buffer, use the LSP version of the document. Then the cache of one document stays correct without events. The events are necessary only for invalidation across documents.
- Read the open buffers (`didOpen`, `didChange`, and `didClose`). They have priority over the files on the disk. At this time, `workspace.resolve_document` reads only from the disk.

This step does not need the previous steps. You can do it first.

Commit: ``feat: Cache the resolved documents in `FolderIndex` ``

### Out of scope

- Combine bursts of events, such as a `git checkout`, into a full build.

After the plan is complete, record this item in `TODO.md`.
