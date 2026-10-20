# Refactor of `ImportGraph`

`ImportGraph` has three concerns:

1. The graph: the `imports` and `imported_by` edges.
2. The caches that make import resolution faster during the build of the graph.
3. The indices that Joule needs to update the graph when somebody creates, deletes, or edits a file. These indices do not exist yet.

Proposal:

- Divide `ImportGraph` into two classes:
  - `ImportGraph` holds the edges and the update indices.
  - `ImportGraphBuilder` holds the caches.
- The caches are useful only during a bulk build. They record only if files exist, so they stay valid until somebody creates or deletes a file. But it is not worth it to keep them. They use much memory on large monorepos, and they save a maximum of a few milliseconds when Joule resolves an edited document again. Thus, create a new `ImportGraphBuilder` for each bulk build, and discard it after the build.
- Make `ImportGraph` mutable, so that Joule can update it in place when files change.

## Plan

Each step is one commit. After each step, all tests must pass. Verify each step with:

- `./test.sh`, ruff, and `ty check`.
- `joule benchmark` on grafonnet and on a large monorepo. The document, edge, and malformed counts must be the same as before the step: 1,413 edges for grafonnet. The build time of the import graph must not increase.

Prerequisite: `imports` and `imported_by` are `dict[Path, set[Path]]`. Thus the graph keeps one edge for each pair of files, and it can remove an edge in O(1).

### Progress

- [x] Prerequisite: Edges as sets
- [x] Step 1: Tests for `ImportGraph.build`
- [x] Step 2: Separate import resolution from the graph
- [x] Step 3: Add `ImportGraphBuilder`
- [ ] Step 4: Keep the data for incremental updates. Moved to step 3 of [refactor-folder-index.md](refactor-folder-index.md).
- [ ] Step 5: Incremental updates. Moved to step 3 of [refactor-folder-index.md](refactor-folder-index.md).

### Step 1: Tests for `ImportGraph.build`

`build` has no tests. Thus, first add tests against the current API. These tests protect the subsequent steps. Test these behaviors:

- The edges in the two directions (`imports` and `imported_by`).
- If a document imports the same file two times, the graph has one edge.
- An import that does not resolve gives no edge.
- The build ignores `importstr` and `importbin`.
- If a document does not parse, the build adds it to `malformed`, and the document gives no edges.
- Imports resolve through jpaths and through the directory of the importer.

Commit: `test: Cover ImportGraph.build`

### Step 2: Separate import resolution from the graph

Move import resolution from `ImportGraph` into `ImportResolver(root, jpaths)`. `ImportResolver` has the `_is_file`, `_same_dir`, and `_via_jpaths` caches. Bulk builds and incremental updates both use it.

The caches record only if files exist. Thus they become incorrect after somebody creates or deletes a file. Do not invalidate the caches. Instead, create a new resolver for each batch of resolutions, and discard it after the batch. A batch is one bulk build or one incremental update.

For now, `ImportGraph` keeps its current public API. It sends the resolution calls to an `ImportResolver`.

> An earlier version of this step had two resolvers: an `ImportResolver` without caches for incremental updates, and a `CachedImportResolver` subclass for bulk builds. This step now merges them into one `ImportResolver` with caches. A cache with a short life is always valid, and it costs little on a small update. Also, there is only one implementation to test.

Commit: `refactor: Extract import resolution into ImportResolver`

### Step 3: Add `ImportGraphBuilder`

- `ImportGraphBuilder(root, jpaths).build(docs) -> ImportGraph` does all the construction: the parallel `collect_importees` pass, and the resolution with an `ImportResolver`. The builder has a short life. Create one for each build, and discard it after the build. This releases the caches.
- `ImportGraph` becomes the result with a long life: `root`, `jpaths`, `imports`, `imported_by`, and `malformed`. It has no caches and no `build` method.
- Change `FolderIndex.start` and `joule benchmark` so that they use the builder. The builder still runs in `asyncio.to_thread`, and one assignment publishes the graph. Thus a lock is not necessary.
- Move the Step 1 tests to the builder.

Commit: `refactor: Split ImportGraphBuilder out of ImportGraph`

### Step 4: Keep the data for incremental updates

Add these fields to `ImportGraph`. The builder sets their values.

- `importees: dict[Path, list[str]]`: the raw importee strings of each document. Joule needs them to resolve the importees again.
- `importers_by_name: dict[str, set[Path]]`: a map from the file name of each importee (`P.basename(P.normpath(importee))`) to the documents that import it.

When somebody creates or deletes a file, `importers_by_name` finds all the imports that can resolve differently. It can select too many imports, but it never misses an import. The reason is that each candidate path of an importee ends with the file name of the importee.

Make sure that the memory cost is acceptable on large monorepos.

Commit: `refactor: Keep raw importees and a file-name index in ImportGraph`

### Step 5: Incremental updates

Add methods that change `ImportGraph`. Each method resolves imports with a new `ImportResolver`.

- `update_document(doc)`:
  1. Collect the importees of the document again, and compare them with `importees[doc]`.
  2. Resolve again only the importees that changed.
  3. Update the edges, `malformed`, and the file-name index.
- `add_file(path)`:
  1. Resolve again the imports that `importers_by_name[basename(path)]` finds. A new file can shadow a candidate with a lower priority. It can also make an unresolved import resolve. This applies to all files, also to files that are not documents, such as `.json` import targets.
  2. If `path` is a document, also collect and resolve its imports.
- `remove_file(path)`:
  1. Remove the edges from the document, and its index entries.
  2. Resolve again the imports that match the file name. These imports can now resolve to a candidate with a lower priority.

Test each method against a full rebuild:

1. Apply a change to a temporary workspace.
2. Update the graph incrementally.
3. Make sure that the graph is equal to a new graph that Joule builds from the changed workspace.

Commit: `feat: Update ImportGraph incrementally on file changes`

### Out of scope

This task does not include these items:

- Connect these methods to LSP events (`workspace/didChangeWatchedFiles` and `textDocument/didSave`).
- Combine bursts of events, such as a `git checkout`, into a full rebuild.

After Step 5 is complete, record these items in [TODO.md](../TODO.md).
