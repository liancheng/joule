# Joule Design

## Parsing

Joule parses Jsonnet source with tree-sitter into a concrete syntax tree (CST), then constructs an abstract syntax tree (AST) from it. The AST is represented by the `joule.trees.Tree` class hierarchy.

## Scopes

Joule tracks variable scopes and object field scopes separately, with `VarScope` and `FieldScope`. The two are structurally similar:

- A scope contains zero or more bindings: `VarBinding`s in a `VarScope`, `FieldBinding`s in a `FieldScope`. A `VarBinding` binds a variable to an expression; a `FieldBinding` binds a static field key to a field value.
- Scopes can be nested.
- Each scope has an owner: a `VarScope`'s owner is a `Tree` node; a `FieldScope`'s owner is an `Object`.

Two corner cases shape the types:

- In a list or object comprehension such as `[i + 1 for i in [1, 2]]`, the variable `i` is bound to the for-spec (`for i in [1, 2]`), not to the collection expression `[1, 2]` — `i` denotes the elements of the collection rather than the collection itself. Since `ForSpec` is a `Tree` but not an `Expr`, `VarBinding.target` is a `Tree`.
- `FieldBinding` tracks static field keys only. The materialized key names of computed field keys cannot easily be learned by static analysis, so they are excluded.

## Workspace folders and `LanguageService`

Each LSP workspace folder maps to one `LanguageService`. A `LanguageService` discovers all Jsonnet source files under its folder and builds the folder's import graph as two dictionaries:

- **imports**: for each source file, the files it directly imports.
- **imported-by**: for each source file, the files that directly import it.

## Building the import graph

The existing `imports` CLI command already implements this logic. For each workspace folder:

1. Discover all Jsonnet files with `fd`.
2. Parse each file with tree-sitter into a CST.
3. Find all `import` nodes, excluding `importstr` and `importbin`.
4. Parse each node into an `Import` AST node and extract the importee path.
5. Resolve the importee path to an absolute path pointing to a source file (see [Import resolution](#import-resolution)). If no such file is found, log an error.
6. Record the edge in both the imports and imported-by dictionaries.

## Import resolution

Resolution follows Jsonnet's file importer, so the graph matches what `jsonnet` actually loads:

1. An absolute importee path is used as-is.
2. Otherwise, try the path relative to the **importing file's directory** (not the workspace folder or the process's working directory).
3. If that fails, try each **library search path** (jpath), the equivalent of `jsonnet -J` / `JSONNET_PATH`. Later entries take precedence, so they are tried in reverse order.
4. The first candidate that names an existing file wins.

Paths are joined and normalized lexically: `.` and `..` are collapsed as text and symlinks are not followed. The resolved path is the key used in both dictionaries.

The search path matters in practice. Universe imports are mostly relative to the repo root (e.g. `ci/runbot/builds/build-utils.jsonnet.TEMPLATE`), so the repo root must be on the jpath; without it, about 45% of the imports under `ci/runbot` fail to resolve. Some importees are generated at build time (e.g. `*team_generated.libsonnet`) and never exist on disk, so they stay unresolved even with the right jpath.

Open questions:

- How the server gets the jpath: `initializationOptions`, `workspace/configuration`, a per-folder default such as the repo root, or a combination.
- The jpath precedence in step 3 is taken from go-jsonnet. Verify it against the Jsonnet implementation Universe builds with before relying on it for multi-entry jpaths.

## Startup and readiness

- Scanning starts in the `initialized` handler, where all workspace folders are already known.
- Scanning is asynchronous and does not block the server.
- Readiness is tracked per workspace folder. Until a folder's scan and import graph are complete, handlers that need the import graph (find definition, find references, etc.) return empty results for that folder.
- Handlers that only need the current file, such as document symbol, don't wait for the scan and answer immediately.
