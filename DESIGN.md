# Joule Design

## Overview

Joule is a Jsonnet language server built on pygls. It aims to scale to very large workspaces and to provide deeper semantic intelligence than existing Jsonnet language servers.

TODO: Project status and scope of the first milestone.

## Goals

### Scalability

Handle large workspaces with 100k Jsonnet source files in deep and wide directory trees. On an EC2 m8id.8xlarge instance, time-to-initial-intelligence (TTII) should be under 10 seconds with a cold OS cache and under 5 seconds with a warm one.

TTII is defined in [Open-sourcing Metals v2][metals-v2-blog]:

[metals-v2-blog]: https://www.databricks.com/blog/open-sourcing-metals-v2-databricks-java-and-scala-language-server-multi-million-line-codebases

> Time-to-initial-intelligence (TTII) measures how quickly the editor becomes useful after opening the repository. We start the clock when the language server activates and stop when the most important features are available, assuming no user intervention. These critical features include fuzzy searching workspace symbols, jump-to-definition, and finding symbol usages across the entire repository.

See [Scaling to large repositories](#scaling-to-large-repositories) for how Joule approaches this.

### Deeper semantic intelligence

Existing Jsonnet language servers miss cases that need deeper analysis. For example, cross-document lambda function calls:

```jsonnet
// f1.libsonnet
function(x) x.f + 1
           /* ^1 */

// f2.jsonnet
local f = import "f1.libsonnet";
local obj = { f: 1 };
           /* ^2 */
f(obj)

// f3.jsonnet
local f = import "f1.libsonnet";
f({ f: 2 })
 /* ^3 */
```

Go to definition at (1) should lead to both (2) and (3).

See [Cross-document analysis](#cross-document-analysis) for how Joule approaches this.

### Non-goals

- Formatting or linting.
- Anything that requires evaluating Jsonnet, such as go-to-definition for computed field keys. Below, go-to-definition at (2) can't reach (1):

  ```jsonnet
  local obj = {
      ['f' + i]: i
   /* ^^^^^^^^^1 */
      for i in std.range(1, 10)
  };
  obj.f1
   /* ^^2 */
  ```

## Architecture

Joule works at two levels:

- **Workspace level**: each LSP workspace folder maps to one `FolderIndex`, which discovers the folder's Jsonnet files and builds its import graph. See [Workspace loading](#workspace-loading).
- **Document level**: a document's full AST, with scopes resolved, is built on demand. See [Document analysis](#document-analysis).

TODO: Component diagram and module layout (`joule.cli`, `joule.server`, `joule.features`, `joule.workspace`, `joule.analysis`, `joule.trees`).

## Workspace loading

### `FolderIndex` and the import graph

Each LSP workspace folder maps to one `FolderIndex`. A `FolderIndex` discovers all Jsonnet source files under its folder and builds the folder's import graph as two dictionaries:

- **imports**: for each source file, the files it directly imports.
- **imported-by**: for each source file, the files that directly import it.

### Building the import graph

For each workspace folder:

1. Discover all Jsonnet files with `fd`.
2. Parse each file with tree-sitter into a CST.
3. Find all `import` nodes, excluding `importstr` and `importbin`.
4. Parse each node into an `Import` AST node and extract the importee path.
5. Resolve the importee path to an absolute path pointing to a source file (see [Import resolution](#import-resolution)). If no such file is found, log an error.
6. Record the edge in both the imports and imported-by dictionaries.

### Import resolution

Resolution follows Jsonnet's file importer, so the graph matches what `jsonnet` actually loads:

1. An absolute importee path is used as-is.
2. Otherwise, try the path relative to the **importing file's directory** (not the workspace folder or the process's working directory).
3. If that fails, try each **library search path** (jpath), the equivalent of `jsonnet -J` / `JSONNET_PATH`. Later entries take precedence, so they are tried in reverse order.
4. The first candidate that names an existing file wins.

Paths are joined and normalized lexically: `.` and `..` are collapsed as text and symlinks are not followed. The resolved path is the key used in both dictionaries.

The search path matters in practice. Universe imports are mostly relative to the repo root (e.g. `ci/runbot/builds/build-utils.jsonnet.TEMPLATE`), so the repo root must be on the jpath; without it, about 45% of the imports under `ci/runbot` fail to resolve. Some importees are generated at build time (e.g. `*team_generated.libsonnet`) and never exist on disk, so they stay unresolved even with the right jpath.

### Startup and readiness

- Scanning starts in the `initialized` handler, where all workspace folders are already known.
- Scanning is asynchronous and does not block the server.
- Readiness is tracked per workspace folder. Until a folder's scan and import graph are complete, handlers that need the import graph (find definition, find references, etc.) return empty results for that folder.
- Handlers that only need the current file, such as document symbol, don't wait for the scan and answer immediately.

### Scaling to large repositories

Workspace folders may hold over 100k Jsonnet files in deep and wide directory trees. Joule aims to meet the [TTII targets](#scalability) by doing only the cheap, parallelizable work up front and deferring the rest:

1. **Discovery.** `fd` is written in Rust and walks the tree in parallel with work stealing, so locating every source file in a deep and wide workspace is extremely fast.
2. **Parsing.** tree-sitter is also extremely fast: with 32 cores (an m8id.8xlarge has 32 vCPUs), parsing 100k Jsonnet files into CSTs takes a few seconds.
3. **Import graph.** Loading extracts only the `import` nodes from each CST to build the import graph (step 4 above). Full AST construction and per-file analysis, such as scope resolution, are deferred.
4. **On-demand ASTs.** Converting a CST to an AST is fast enough that intelligent LSP operations, such as go-to-definition and find references, can afford to build ASTs for tens to hundreds of documents per request. See [On-demand ASTs](#on-demand-asts).

Once a folder's import graph is ready, go-to-definition and find references can start from the relevant documents and follow the import graph, building only the ASTs they need.

#### Design decision: eager vs. on-demand ASTs

1. Build full ASTs, with scopes resolved, for every file while loading the workspace.
   - **Pros:**
     - Every semantic request can be answered without building ASTs first.
     - Workspace-wide features, such as fuzzy workspace symbol search, have all the information they need.
   - **Cons:**
     - Adds AST construction and scope resolution for every file to loading, which works against the [TTII targets](#scalability).
     - Keeps an AST for every file in memory.
2. Build only CSTs and the import graph while loading, and build ASTs on demand.
   - **Pros:**
     - Loading does only cheap, parallelizable work: discovery, CST parsing, and extracting `import` nodes.
     - Memory stays bounded by the [AST cache](#ast-cache).
   - **Cons:**
     - The first request touching a document pays for building its AST.
     - Workspace-wide features need another way to get their information (see [Open questions](#open-questions)).

Jwith High/Medium CI Impact oule takes option 2. Building ASTs for tens to hundreds of documents per request is cheap enough, while building all of them up front is not.

## Document analysis

### Parsing

Joule parses Jsonnet source with tree-sitter into a concrete syntax tree (CST), then constructs an abstract syntax tree (AST) from it. The AST is represented by the `joule.trees.Tree` class hierarchy.

### On-demand ASTs

A file's full AST, with scopes resolved, is built only when an LSP method needing high-level semantic information is invoked. Built ASTs are kept in an LRU cache.

#### AST cache

The cache holds one entry per document URI. Each entry records a revision token for the content it was built from. A lookup hits only if the stored token matches the document's current token; otherwise the AST is rebuilt and the entry replaced. See [where the revision token lives](#design-decision-where-the-revision-token-lives).

The token comes from whoever owns the document's content:

| Document state     | Owner  | Revision token                                 |
| ------------------ | ------ | ---------------------------------------------- |
| Open in the editor | Client | `("mem", version)`, from `didOpen`/`didChange` |
| Closed             | Disk   | `("disk", mtime_ns, size, inode)`, from `stat` |

- **Open documents.** The LSP `version` increases on every change, including undo, but only within one open session; it may restart after `didClose` and `didOpen`. Entries are dropped on `didOpen` and `didClose`, so versions are never compared across sessions. The `"mem"`/`"disk"` tag keeps the two kinds of token from colliding.
- **Closed documents.** mtime alone is not enough: some filesystems have coarse timestamps, and tools like `cp -p`, `rsync -t` and `tar` preserve mtime. Adding `size` and `inode` covers most of these cases, similar to the stat data git keeps in its index. A file written within the same timestamp tick as the cache fill (git's "racy git" problem) falls back to a content hash.
- **Invalidation.** Entries are also dropped on `workspace/didChangeWatchedFiles`, so most lookups don't need a `stat`.

##### Design decision: where the revision token lives

1. Include the revision token in the cache key, `(URI, token)`.
   - **Pros:**
     - A plain dictionary lookup; no separate validity check.
   - **Cons:**
     - Stale versions of the same document pile up in the LRU until they are evicted, crowding out live entries.
2. Key by URI only, and store the token in the entry.
   - **Pros:**
     - At most one entry per document, so the LRU's capacity goes to live documents.
   - **Cons:**
     - Each lookup also compares the stored token with the current one.

Joule takes option 2.

##### Design decision: revision tokens for closed documents

1. mtime only.
   - **Pros:**
     - Cheapest: one `stat` field.
   - **Cons:**
     - Misses changes on filesystems with coarse timestamps, and changes made by tools that preserve mtime (`cp -p`, `rsync -t`, `tar`).
2. `stat` data: `(mtime_ns, size, inode)`, with a content-hash fallback for racy writes.
   - **Pros:**
     - Catches most of the cases mtime alone misses, at the cost of one `stat` per lookup.
     - A cache hit never reads the file.
   - **Cons:**
     - More complex: needs the racy-write fallback to be fully correct.
3. Content hash of every document.
   - **Pros:**
     - Simplest and always correct.
     - Cheap for open documents, whose text is already in memory.
   - **Cons:**
     - For closed files, every cache hit reads the whole file just to hash it. This adds up for workspace-wide queries touching thousands of files.

Joule takes option 2.

Cache keys must be normalized the same way as import graph paths (lexically, without following symlinks, with consistent percent-encoding). Otherwise one file gets two entries, and lookups from the import graph miss the cache.

A cached AST depends only on its own document's content, since scope resolution is per document, so no dependency tracking is needed. Cached cross-document results will need tokens that combine the tokens of the documents they depend on.

### Scope resolution

Scope resolution runs after a Jsonnet source file is parsed into an AST. It:

1. Binds local variables, object locals, and function parameters as `VarBinding`s, stored in `VarScope`s.
2. Binds static object field keys to their values as `FieldBinding`s, stored in `FieldScope`s.
3. Resolves variable and field references to their definitions, without looking into other documents.

Resolving variable references is trivial: variables are always document-local (see [Storing resolution results](#storing-resolution-results)).

A field reference may have several definitions, some from imported documents. Resolution doesn't analyze imported documents. It records each definition's origin on the `Id.FieldRef`:

- `("local", Field)`: a field of an object in the same document.
- `("imported", URI)`: a field of an object in the imported document at `URI`.

`imported` origins anchor references to other documents. Following them is left to [cross-document analysis](#cross-document-analysis), which backs features like go-to-definition and find references. This keeps per-document analysis self-contained, which lets [cached ASTs](#ast-cache) skip dependency tracking.

Jsonnet is lexically scoped, which Joule models with nested scopes. `VarScope` and `FieldScope` are structurally similar:

- A scope contains zero or more bindings: `VarBinding`s in a `VarScope`, `FieldBinding`s in a `FieldScope`. A `VarBinding` binds a variable to an expression; a `FieldBinding` binds a static field key to a field value.
- Each scope has a parent pointer to its enclosing scope (`None` at the root). Name lookup walks up the parent chain.
- Each scope has an owner: a `VarScope`'s owner is a `Tree` node; a `FieldScope`'s owner is an `Object`.

Three corner cases shape the types:

- In a list or object comprehension such as `[i + 1 for i in [1, 2]]`, the variable `i` is bound to the for-spec (`for i in [1, 2]`), not to the collection expression `[1, 2]` — `i` denotes the elements of the collection rather than the collection itself. Since `ForSpec` is a `Tree` but not an `Expr`, `VarBinding.target` is a `Tree`.
- In a function such as `function(x, y=1) x + y`, each parameter's `Id.Var` is bound to its `Param`, which is also a `Tree` but not an `Expr`. This is another reason `VarBinding.target` is a `Tree`.
- `FieldBinding` tracks static field keys only. The materialized key names of computed field keys cannot easily be learned by static analysis, so they are excluded.

### Storing resolution results

Resolution results are stored on AST nodes, so they can be navigated in both directions:

- An `Id.Var` bound to a `Tree` node references its `VarBinding`, which references the `VarScope` it lives in.
- The `Id.Field` of a static field key references its `FieldBinding`, which references the `FieldScope` it lives in.

Jsonnet variables are always document-local: the `Id.Var` defining any `Id.VarRef` is in the same `Document`. For fast access, resolution also links the two directly:

- Each `Id.VarRef` references its defining `Id.Var`.
- Each `Id.Var` holds a list of all `Id.VarRef`s that reference it.

#### Design decision: lookup tables vs. AST nodes

There are at least two options for where to store resolution results:

1. Like `ty`, store them in separate lookup tables keyed by hashes or stable IDs of AST nodes.
   - **Pros:**
     - Cleaner, and keeps AST nodes immutable, which suits languages that encourage immutability.
     - Incremental computation libraries like Salsa help minimize recomputing the tables when a source file changes.
     - Scales better as more kinds of information are collected in the future.
   - **Cons:**
     - More complicated to implement.
2. Store them directly in the AST nodes.
   - **Pros:**
     - Easier to implement.
   - **Cons:**
     - Requires mutable AST nodes.
     - Harder to track as the amount of information grows.
     - Prevents AST classes from being frozen `dataclass`es with an auto-generated hash method.

Joule takes option 2. Jsonnet is a simple language: there isn't much information to collect or store, and recomputation is cheap enough that Joule can afford a full recomputation per file on every change. Python also has no mature Salsa equivalent, so option 1 would mean building the incremental machinery from scratch.

## Cross-document analysis

TODO: How Joule follows values across `import` edges and function calls to answer queries like the [better intelligence](#better-intelligence) example: resolving what an imported file evaluates to, finding the call sites of an imported function via the imported-by graph, tracking which objects flow into a parameter, and following `("imported", URI)` field origins recorded by [scope resolution](#scope-resolution). Also how cached cross-document results are invalidated (see [AST cache](#ast-cache)).

## LSP features

TODO: Supported LSP methods, and for each, whether it needs only the current document or the workspace import graph.

## Document synchronization

TODO: How `didOpen`/`didChange`/`didSave`/`didClose` and on-disk file changes update the import graph. For cached ASTs, see [AST cache](#ast-cache).

## Testing and benchmarking

### Marked-span syntax

Parsing and LSP tests need to refer to precise source positions: the span an AST node should have, the cursor position of a request, or the range a response should return. Tests annotate Jsonnet source with _marked spans_ instead of computing line and column numbers by hand. `tests.dsl.span_markers.parse` strips the annotations and returns the plain source together with a map from mark IDs to spans.

Each line of an annotated source starts with a 4-character prefix:

- `:   ` (a `:` followed by 3 spaces) marks a source line.
- `>   ` (a `>` followed by 3 spaces) marks an annotation line, which marks spans on the preceding source line with runs of `^` followed by mark IDs:
  - `^^^1`: the run's characters are span `1`.
  - `^1,2`: several marks on the same run, separated by commas.

  A source line can have several annotation lines, which helps when marks would otherwise overlap.

Any other line prefix is an error.

For example:

```python
t = self.fake_document(
    """\
    :   local x = 1, y = 2; x + y
    >   ^1    ^2  ^3 ^4  ^5 ^6  ^7
    """
)

x: Id.Var = t.var_at(2)  # `x` in `x = 1`
x_ref: Id.VarRef = t.var_ref_at(6)  # `x` in `x + y`
```

Sources without marks use `fake_document(source, marked=False)`.

Each mark covers a span on a single line. Longer spans, including spans across lines, are formed by passing several marks (in practice, two) to the `FakeDocument` helpers below. The result runs from the start of the earliest mark to the end of the latest one, so it's enough to mark just the first and last characters:

```python
t = self.fake_document(
    """\
    :   local obj = {
    >               ^1
    :       a: 1
    :   };
    >   ^2
    :   obj
    """
)

# The span of the object literal from `{` to `}`
obj_span = t.at(1, 2)
```

`FakeDocument` parses the annotated source, runs scope resolution, and provides helpers:

- `at(*marks)` returns the span covering the given marks. Its `SpanDSL` constructors (`num`, `var`, `array`, …) build expected trees with exact spans.
- `node_at(*marks)` returns the node at that span, and `num_at`, `var_at` and `var_ref_at` return it as a specific node type.

This keeps positions next to the code they refer to. Tests stay readable, and editing a test source only means moving the marks, never recomputing coordinates. The same marks serve both parser tests (expected spans) and LSP tests (request positions and expected ranges).

When two trees of the same type differ, `FakeDocumentTestCase` shows a side-by-side diff of their pretty-printed forms (via ocdiff) instead of raw reprs. This is disabled when `CI` is set.

### Benchmarking

TODO: How TTII is measured against the [scalability](#scalability) targets.

## Open questions

- How the server gets the jpath: `initializationOptions`, `workspace/configuration`, a per-folder default such as the repo root, or a combination.
- The jpath precedence in [import resolution](#import-resolution) step 3 is taken from go-jsonnet. Verify it against the Jsonnet implementation Universe builds with before relying on it for multi-entry jpaths.
- TTII includes fuzzy workspace symbol search and repository-wide find usages, but loading only builds the import graph. How these features become available within the TTII target without building every AST is undecided.
