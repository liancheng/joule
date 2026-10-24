# Joule Design

## Overview

Joule is a language server for Jsonnet, built on pygls. Joule has two aims. It must operate on very large workspaces. It must also give deeper semantic intelligence than the current Jsonnet language servers.

## Goals

### Scalability

Joule must operate on workspaces with 100k Jsonnet source files in deep and wide directory trees. On an EC2 m8id.8xlarge instance, the time-to-initial-intelligence (TTII) must be less than 10 seconds with a cold OS cache. With a warm OS cache, it must be less than 5 seconds.

[Open-sourcing Metals v2][metals-v2-blog] defines TTII:

[metals-v2-blog]: https://www.databricks.com/blog/open-sourcing-metals-v2-databricks-java-and-scala-language-server-multi-million-line-codebases

> Time-to-initial-intelligence (TTII) measures how quickly the editor becomes useful after opening the repository. We start the clock when the language server activates and stop when the most important features are available, assuming no user intervention. These critical features include fuzzy searching workspace symbols, jump-to-definition, and finding symbol usages across the entire repository.

For the approach of Joule, see [Large repositories](#large-repositories).

### Deeper semantic intelligence

The current Jsonnet language servers miss some cases that need deeper analysis. An example is a lambda function that other documents call:

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

Go-to-definition at (1) must go to (2) and to (3).

For the approach of Joule, see [Cross-document analysis](#cross-document-analysis).

### Non-goals

- Joule does not format or lint code.
- Joule does not give features that need Jsonnet evaluation. An example is go-to-definition for computed field keys. In this example, go-to-definition at (2) cannot find (1):

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

Joule operates at two levels:

- **Workspace level**: Each LSP workspace folder has one `FolderService`. The `FolderService` finds the Jsonnet files of the folder and builds the `FolderIndex` of the folder, which holds the import graph. See [Workspace loading](#workspace-loading).
- **Document level**: Joule builds the full AST of a document, with resolved scopes, only when a request needs it. See [Document analysis](#document-analysis).

TODO: Add a component diagram and the module layout (`joule.cli`, `joule.server`, `joule.features`, `joule.workspace`, `joule.analysis`, `joule.syntax`).

## Workspace loading

### `FolderIndex` and the import graph

Each LSP workspace folder has one `FolderService`. A `FolderService` finds all the Jsonnet source files in its folder. Then it builds the import graph of the folder into its `FolderIndex`, as two dictionaries:

- **imports**: For each source file, the files that it imports directly.
- **imported-by**: For each source file, the files that import it directly.

### Import graph construction

For each workspace folder, Joule does these steps:

1. Find all the Jsonnet files with `fd`. Do not follow symlinks. Editors report only the real paths of files, so a document under a symlinked directory never gets updates.
2. Parse each file into a CST with tree-sitter.
3. Find all the `import` nodes. Ignore the `importstr` and `importbin` nodes.
4. Parse each node into an `Import` AST node, and get the importee path.
5. Resolve the importee path to the absolute path of a source file. See [Import resolution](#import-resolution). If no file matches, log an error.
6. Record the edge in the imports dictionary and in the imported-by dictionary.

### Import resolution

Import resolution follows the file importer of Jsonnet. Thus the graph contains the same files that `jsonnet` loads. The steps are:

1. If the importee path is absolute, use it without a change.
2. If not, try the path relative to the **directory of the importer**. Do not use the workspace folder or the working directory of the process.
3. If step 2 fails, try each **library search path** (jpath). A jpath is the equivalent of `jsonnet -J` and `JSONNET_PATH`. Later entries have priority, so try them in reverse sequence.
4. The result is the first candidate that is the name of a file that exists.

Joule joins and normalizes paths lexically. It collapses `.` and `..` as text, and it does not follow symlinks. Both dictionaries use the resolved path as the key.

The search path is important in practice:

- In large monorepos, most imports are relative to the root of the repository. Thus the repository root must be on the jpath.
- Some builds generate importees. These files are never on the disk, so their imports do not resolve, even with the correct jpath.

### Startup and readiness

- The scan starts in the `initialized` handler. At that time, the server knows all the workspace folders.
- The scan is asynchronous. It does not block the server.
- Joule tracks the readiness of each workspace folder. Some handlers need the import graph, for example find definition and find references. Until the scan and the import graph of a folder are complete, these handlers return empty results for that folder.
- Other handlers need only the current file, for example document symbol. These handlers do not wait for the scan. They answer immediately.

### Large repositories

A workspace folder can contain more than 100k Jsonnet files in deep and wide directory trees. To meet the [TTII targets](#scalability), Joule does only the cheap work at the start, in parallel. It does the other work later:

1. **Discovery.** `fd` is a Rust tool. It goes through the tree in parallel, with work stealing. Thus it finds all the source files in a deep and wide workspace very quickly.
2. **Parse.** tree-sitter is also very fast. With 32 cores (an m8id.8xlarge has 32 vCPUs), it parses 100k Jsonnet files into CSTs in a few seconds.
3. **Import graph.** The load gets only the `import` nodes from each CST to build the import graph (step 4 in [Import graph construction](#import-graph-construction)). Joule does the full AST construction and the per-file analysis, such as scope resolution, later.
4. **On-demand ASTs.** The conversion from a CST to an AST is fast. Thus intelligent LSP operations, such as go-to-definition and find references, can build ASTs for tens to hundreds of documents for each request. See [On-demand ASTs](#on-demand-asts).

When the import graph of a folder is ready, go-to-definition and find references can start from the related documents. They follow the import graph and build only the ASTs that they need.

#### Design decision: eager vs. on-demand ASTs

1. Build full ASTs, with resolved scopes, for all files when Joule loads the workspace.
   - **Pros:**
     - Joule can answer each semantic request immediately, because all the ASTs exist.
     - Workspace-wide features, such as fuzzy workspace symbol search, have all the data that they need.
   - **Cons:**
     - The load must also build ASTs and resolve scopes for all files. This works against the [TTII targets](#scalability).
     - Joule keeps an AST for each file in memory.
2. During the load, build only CSTs and the import graph. Build an AST when a request needs it.
   - **Pros:**
     - The load does only cheap work that can run in parallel: discovery, CST parse, and extraction of `import` nodes.
     - The [AST cache](#ast-cache) sets a limit on the memory.
   - **Cons:**
     - The first request on a document must wait for its AST.
     - Workspace-wide features must get their data in a different way. See [Open questions](#open-questions).

Joule takes option 2. It is cheap enough to build ASTs for tens to hundreds of documents for each request. It is not cheap enough to build all of them at the start.

## Document analysis

### Syntax trees

Joule parses Jsonnet source code into a concrete syntax tree (CST) with tree-sitter. Then it makes an abstract syntax tree (AST) from the CST. The `joule.syntax.trees.Tree` class hierarchy represents the AST.

### On-demand ASTs

Joule builds the full AST of a file, with resolved scopes, only when an LSP method needs high-level semantic data. An LRU cache keeps the ASTs that Joule built.

#### AST cache

The cache has one entry for each document URI. Each entry records a revision token for the content that Joule built the AST from. A lookup is a hit only if the stored token is equal to the current token of the document. If not, Joule builds the AST again and replaces the entry. See [where the revision token lives](#design-decision-where-the-revision-token-lives).

The owner of the content of the document gives the token:

| Document state     | Owner  | Revision token                                 |
| ------------------ | ------ | ---------------------------------------------- |
| Open in the editor | Client | `("mem", version)`, from `didOpen`/`didChange` |
| Closed             | Disk   | `("disk", mtime_ns, size, inode)`, from `stat` |

- **Open documents.** The LSP `version` increases on each change, also on an undo. But it increases only in one open session. After `didClose` and `didOpen`, it can start again. Joule removes the entry on `didOpen` and on `didClose`, so it never compares versions from different sessions. The `"mem"` and `"disk"` tags prevent collisions between the two types of token.
- **Closed documents.** The mtime alone is not sufficient. Some file systems have coarse timestamps. Also, tools such as `cp -p`, `rsync -t`, and `tar` keep the mtime. The `size` and the `inode` cover most of these cases, as the stat data in the git index does. A file can change in the same timestamp tick as the cache fill. This is the "racy git" problem of git. For such a file, Joule uses a content hash.
- **Invalidation.** Joule also removes entries on `workspace/didChangeWatchedFiles`. Thus most lookups do not need a `stat`.

##### Design decision: where the revision token lives

1. Include the revision token in the cache key, `(URI, token)`.
   - **Pros:**
     - A lookup is a plain dictionary lookup. A separate validity check is not necessary.
   - **Cons:**
     - Old versions of a document stay in the LRU until eviction. They take space from live entries.
2. Use only the URI as the key, and keep the token in the entry.
   - **Pros:**
     - There is a maximum of one entry for each document. Thus all the capacity of the LRU is for live documents.
   - **Cons:**
     - Each lookup must also compare the stored token with the current token.

Joule takes option 2.

##### Design decision: revision tokens for closed documents

1. Only the mtime.
   - **Pros:**
     - This is the cheapest option: one `stat` field.
   - **Cons:**
     - It does not see changes on file systems with coarse timestamps. It also does not see changes from tools that keep the mtime (`cp -p`, `rsync -t`, `tar`).
2. The `stat` data, `(mtime_ns, size, inode)`, with a content hash for racy writes.
   - **Pros:**
     - It sees most of the changes that the mtime alone does not see. The cost is one `stat` for each lookup.
     - A cache hit never reads the file.
   - **Cons:**
     - It is more complex. To be fully correct, it needs the content hash for racy writes.
3. A content hash of each document.
   - **Pros:**
     - It is the simplest option, and it is always correct.
     - It is cheap for open documents, because their text is already in memory.
   - **Cons:**
     - For a closed file, each cache hit reads the full file to calculate its hash. For workspace-wide queries on thousands of files, this cost is large.

Joule takes option 2.

Joule must normalize cache keys in the same way as the import graph paths: lexically, without symlinks, and with consistent percent-encoding. If not, one file gets two entries, and lookups from the import graph do not hit the cache.

A cached AST depends only on the content of its document, because scope resolution operates on one document. Thus the cache does not need to track dependencies. Cached cross-document results will need tokens that combine the tokens of all the documents that they depend on.

### Scope resolution

Scope resolution runs after Joule parses a Jsonnet source file into an AST. It does these steps:

1. It binds local variables, object locals, and function parameters as `VarBinding`s. It keeps them in `VarScope`s.
2. It binds static object field keys to their values as `FieldBinding`s. It keeps them in `FieldScope`s.
3. It resolves variable and field references to their definitions. It does not examine other documents.

The resolution of variable references is simple, because variables are always local to a document. See [Storage of resolution results](#storage-of-resolution-results).

A field reference can have more than one definition, and some definitions can come from imported documents. Resolution does not analyze imported documents. It records the origin of each definition on the `Id.FieldRef`:

- `("local", Field)`: a field of an object in the same document.
- `("imported", URI)`: a field of an object in the imported document at `URI`.

`imported` origins connect references to other documents. [Cross-document analysis](#cross-document-analysis) follows them, and features such as go-to-definition and find references use its results. Thus the analysis of each document is self-contained, and the [cached ASTs](#ast-cache) do not need to track dependencies.

Jsonnet uses lexical scopes. Joule models them with nested scopes. `VarScope` and `FieldScope` have a similar structure:

- A scope contains zero or more bindings: `VarBinding`s in a `VarScope`, and `FieldBinding`s in a `FieldScope`. A `VarBinding` binds a variable to an expression. A `FieldBinding` binds a static field key to a field value.
- Each scope has a parent pointer to the scope that contains it. The parent of the root scope is `None`. A name lookup goes up the parent chain.
- Each scope has an owner. The owner of a `VarScope` is a `Tree` node. The owner of a `FieldScope` is an `Object`.

Three special cases control the types:

- In a list comprehension or an object comprehension, such as `[i + 1 for i in [1, 2]]`, resolution binds the variable `i` to the for-spec (`for i in [1, 2]`). It does not bind `i` to the collection expression `[1, 2]`, because `i` refers to the elements of the collection, not to the collection. `ForSpec` is a `Tree`, but not an `Expr`. Thus `VarBinding.target` is a `Tree`.
- In a function such as `function(x, y=1) x + y`, resolution binds the `Id.Var` of each parameter to its `Param`. A `Param` is also a `Tree`, but not an `Expr`. This is another reason why `VarBinding.target` is a `Tree`.
- `FieldBinding` records only static field keys. Static analysis cannot easily find the names of computed field keys, so `FieldBinding` does not include them.

### Storage of resolution results

Joule keeps the resolution results on the AST nodes. Thus code can go through them in the two directions:

- An `Id.Var` that is bound to a `Tree` node refers to its `VarBinding`. The `VarBinding` refers to its `VarScope`.
- The `Id.Field` of a static field key refers to its `FieldBinding`. The `FieldBinding` refers to its `FieldScope`.

Jsonnet variables are always local to a document: the `Id.Var` that defines an `Id.VarRef` is always in the same `Document`. For fast access, resolution also connects the two directly:

- Each `Id.VarRef` refers to the `Id.Var` that defines it.
- Each `Id.Var` keeps a list of all the `Id.VarRef`s that refer to it.

#### Design decision: lookup tables vs. AST nodes

There are at least two options for the location of the resolution results:

1. Keep them in separate lookup tables, as `ty` does. Use hashes or stable IDs of AST nodes as the keys.
   - **Pros:**
     - This option is cleaner. The AST nodes stay immutable, which is good for languages that recommend immutability.
     - Incremental computation libraries such as Salsa help to decrease the recomputation of the tables when a source file changes.
     - It scales better when Joule collects more types of data in the future.
   - **Cons:**
     - It is more complex to implement.
2. Keep them directly in the AST nodes.
   - **Pros:**
     - It is easier to implement.
   - **Cons:**
     - The AST nodes must be mutable.
     - When the quantity of data increases, it is more difficult to track.
     - The AST classes cannot be frozen `dataclass`es with an automatically generated hash method.

Joule takes option 2. Jsonnet is a simple language, so there is not much data to collect or keep. Recomputation is cheap: Joule can do a full recomputation of a file on each change. Also, Python has no mature equivalent of Salsa. With option 1, Joule must build the incremental machinery from the start.

## Cross-document analysis

TODO: Tell how Joule follows values across `import` edges and function calls to answer queries such as the example in [Deeper semantic intelligence](#deeper-semantic-intelligence). This includes:

- How Joule finds what an imported file evaluates to.
- How Joule finds the call sites of an imported function through the imported-by graph.
- How Joule tracks which objects go into a parameter.
- How Joule follows the `("imported", URI)` field origins that [scope resolution](#scope-resolution) records.
- How Joule invalidates cached cross-document results. See [AST cache](#ast-cache).

## Document synchronization

TODO: Tell how `didOpen`, `didChange`, `didSave`, `didClose`, and file changes on the disk update the import graph. For cached ASTs, see [AST cache](#ast-cache).

## Tests and benchmarks

### Marked-span syntax

Parser tests and LSP tests must refer to exact source positions. Examples are the span of an AST node, the cursor position of a request, and the range in a response. The tests do not calculate line and column numbers manually. Instead, they add annotations to the Jsonnet source to mark spans. These spans are _marked spans_. `tests.dsl.span_markers.parse` removes the annotations. It returns the plain source and a map from mark IDs to spans.

Each line of an annotated source starts with a prefix of 4 characters:

- `:   ` (a `:` and 3 spaces) marks a source line.
- `>   ` (a `>` and 3 spaces) marks an annotation line. An annotation line marks spans on the source line above it, with runs of `^` and mark IDs:
  - `^^^1`: the characters of the run are span `1`.
  - `^1,2`: more than one mark on the same run, with commas between the IDs.

  A source line can have more than one annotation line. Use more annotation lines when the marks overlap.

A different line prefix is an error.

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

For a source without marks, use `fake_document(source, marked=False)`.

Each mark covers a span on one line. For a longer span, or for a span on more than one line, give more than one mark (usually two) to the `FakeDocument` helpers below. The result goes from the start of the first mark to the end of the last mark. Thus it is sufficient to mark only the first and the last characters:

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

`FakeDocument` parses the annotated source, runs scope resolution, and gives these helpers:

- `at(*marks)` returns the span that covers the marks. Its `SpanDSL` constructors (`num`, `var`, `array`, …) build expected trees with exact spans.
- `node_at(*marks)` returns the node at that span. `num_at`, `var_at`, and `var_ref_at` return the node as a specific node type.

Thus the positions are near the code that they refer to, and the tests are easy to read. When you change a test source, you move only the marks. You never calculate the coordinates again. Parser tests (expected spans) and LSP tests (request positions and expected ranges) use the same marks.

If two trees of the same type are not equal, `FakeDocumentTestCase` shows a side-by-side diff of their pretty-printed forms (with ocdiff), not the raw reprs. If the `CI` environment variable is set, `FakeDocumentTestCase` does not show this diff.

### Benchmarking

TODO: Tell how Joule measures TTII against the [scalability](#scalability) targets.

## Possible optimizations

Do these only if a measurement shows a real problem.

- **Interned paths in the import graph.** Each import resolution makes a new `Path`. Thus a file that many documents import exists as many `Path` objects, and each `Path` keeps its own cached strings and lists. Instead, store the paths of the graph as `str`s, and intern them with `sys.intern`, as Joule already does for the raw importees. Then the graph keeps one small string for each file. `sys.intern` does not accept `Path`s. A dictionary that keeps one `Path` for each file is also possible, but it saves less memory. The cost is that the resolver returns `str`s, and the callers convert between `Path` and `str` at the boundary.
- **Interned identifier names in the AST cache.** The same identifier names occur in many documents. If the [AST cache](#ast-cache) keeps many ASTs, intern the `name` of each `Id` node in its `from_cst`. Python frees an interned string when nothing refers to it, so the evicted ASTs do not keep their names in memory. Do not intern all the text of the CST. String literals and numbers repeat less, and the extra work costs more than it saves.

## Open questions

- How does the server get the jpath? The options are `initializationOptions`, `workspace/configuration`, a default for each folder such as the repository root, or a combination.
- The jpath priority in step 3 of [Import resolution](#import-resolution) comes from go-jsonnet. Verify it against the other Jsonnet implementations. Do this before Joule uses the priority for jpaths with more than one entry.
- TTII includes fuzzy workspace symbol search and find usages in the full repository. But the load builds only the import graph. It is not yet decided how these features become available within the TTII target without ASTs for all the files.
