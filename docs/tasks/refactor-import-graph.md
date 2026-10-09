# Refactoring `ImportGraph`

`ImportGraph` mixes three concerns:

1. The graph itself: the `imports` and `imported_by` edges.
2. The caches that speed up resolving imports while building the graph.
3. The indices needed to update the graph when files are created, deleted, or edited. These don't exist yet.

Proposal:

- Split it into an `ImportGraph` holding the edges and the update indices, and an `ImportGraphBuilder` holding the caches.
- The caches pay off only during a bulk build. They stay valid afterwards, since they record only whether files exist, but keeping them isn't worth it: they hold about 56 MiB on Universe, and save at most a few milliseconds when re-resolving an edited document. So create a fresh `ImportGraphBuilder` for each bulk build and drop it afterwards.
- Make `ImportGraph` mutable, so it can be updated in place when files are created, deleted, or edited.

## Plan

Each step leaves the tests green and is its own commit. Every step is verified with:

- `./test.sh`, ruff, and `ty check`, including `tests/test_layering.py`.
- `joule benchmark` on grafonnet and Universe master, with the same document, edge, and malformed counts as before the step: grafonnet 1,413 edges, Universe 141,332 edges with the root as jpath. Import graph build time must not regress.

Prerequisite (done, uncommitted): `imports` and `imported_by` are `dict[Path, set[Path]]`, so one edge is stored per pair of files and edges can be removed in O(1).

### Step 1: Tests for `ImportGraph.build`

`build` has no tests today, so add them first, against the current API, to protect the following steps:

- Edges in both directions (`imports`, `imported_by`).
- A document importing the same file twice yields one edge.
- Unresolved imports yield no edge.
- `importstr` and `importbin` are ignored.
- A document that fails to parse is listed in `malformed` and contributes no edges.
- Imports resolved through jpaths and through the importer's directory.

Commit: `test: Cover ImportGraph.build`

### Step 2: Separate import resolution from the graph

Move resolution out of `ImportGraph` into two resolvers with the same interface:

- `ImportResolver(root, jpaths)` resolves without caches. Incremental updates will use it.
- `CachedImportResolver(ImportResolver)` adds the `_is_file`, `_same_dir`, and `_via_jpaths` caches by overriding the lookups. Bulk builds use it.

`ImportGraph` keeps its current public API for now, delegating to a `CachedImportResolver`. Run the existing resolution tests against both resolvers, so that the two can't drift apart.

Commit: `refactor: Extract import resolution into ImportResolver`

### Step 3: Introduce `ImportGraphBuilder`

- `ImportGraphBuilder(root, jpaths).build(docs) -> ImportGraph` owns the whole construction: the parallel `collect_importees` pass and resolution with a `CachedImportResolver`. It is ephemeral, created per build and dropped afterwards, which frees the caches (about 56 MiB on Universe).
- `ImportGraph` becomes the long-lived result: `root`, `jpaths`, `imports`, `imported_by`, and `malformed`. It has no caches and no `build` method.
- Update `FolderIndex.start` and `joule benchmark` to use the builder. The builder still runs in `asyncio.to_thread` and the graph is published in one assignment, so no locking is needed.
- Move the Step 1 tests to the builder.

Commit: `refactor: Split ImportGraphBuilder out of ImportGraph`

### Step 4: Keep the data needed for incremental updates

Add to `ImportGraph`, populated by the builder:

- `importees: dict[Path, list[str]]`: each document's raw importee strings, needed to re-resolve them.
- `importers_by_name: dict[str, set[Path]]`: the file name of each importee (`P.basename(P.normpath(importee))`) mapped to the documents importing it. When a file is created or deleted, this finds every import that might resolve differently. It may over-select but never misses an import, because every candidate path of an importee ends with that file name.

Measure the memory cost on Universe and record it here.

Commit: `refactor: Keep raw importees and a file-name index in ImportGraph`

### Step 5: Incremental updates

Add mutation methods to `ImportGraph`, using an uncached `ImportResolver`:

- `update_document(doc)`: re-collect the document's importees, diff them against `importees[doc]`, re-resolve only what changed, and update edges, `malformed`, and the file-name index.
- `add_file(path)`: re-resolve the imports found through `importers_by_name[basename(path)]`. A new file can shadow a lower-priority candidate or make an unresolved import resolve. This applies to any file, including non-documents such as `.json` import targets. If `path` is a document, also collect and resolve its own imports.
- `remove_file(path)`: drop the document's outgoing edges and index entries, then re-resolve the name-matched imports, which may now resolve to a lower-priority candidate.

Test each method against a full rebuild: apply a change to a temporary workspace, update the graph incrementally, and assert that it equals a graph freshly built from the changed workspace.

Commit: `feat: Update ImportGraph incrementally on file changes`

### Out of scope

Wiring these methods to LSP events (`workspace/didChangeWatchedFiles`, `textDocument/didSave`) and batching bursts of events, such as a `git checkout`, into a full rebuild. Track these in [TODO.md](../TODO.md) once Step 5 lands.
