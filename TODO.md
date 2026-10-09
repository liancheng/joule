# Joule TODO

Current progress and remaining work. See [DESIGN.md](DESIGN.md) for the design.

## Progress

### LSP features

Each feature is a provider class in `joule.features`, and `joule.server` wires it to an LSP method. All implemented features need only the current document:

| Method | Provider | Scope |
| --- | --- | --- |
| `textDocument/documentSymbol` | `DocumentSymbolProvider` | Current document |
| `textDocument/definition` | `DefinitionProvider` | Current document |
| `textDocument/references` | `ReferencesProvider` | Current document |
| `textDocument/foldingRange` | `FoldingRangeProvider` | Current document |

For every request, the server parses the document and runs [scope resolution](DESIGN.md#scope-resolution) on it (`resolve_document`). None of these features reads the [import graph](DESIGN.md#folderindex-and-the-import-graph), so they also work for documents outside every workspace folder, such as a stray file in `/tmp`.

- **Document symbols** form a hierarchy that follows nesting:
  - Locals and object locals are `Variable`s, or `Function`s when bound to a function.
  - Function parameters and comprehension variables (`for x in ...`) are `Variable`s.
  - Static field keys are `Field`s. Computed keys are skipped, since their names are only known after evaluation (see [Non-goals](DESIGN.md#non-goals)).
- **Go to definition** works on variable references (`Id.VarRef`) and returns the defining `Id.Var`.
- **Find references** works on a variable definition (`Id.Var`) and returns every `Id.VarRef` that refers to it.
- **Folding ranges** cover multi-line arrays, objects, array and object comprehensions, functions, and parenthesized expressions.

### Workspace loading

- `initialized` reads the configuration (`jpaths`, `exclude`, `extensions`) through `workspace/configuration`, then creates one `FolderIndex` per workspace folder.
- `FolderIndex` discovers documents with `fd` and builds the import graph in a process pool, with batched work and cached import resolution.
- `joule benchmark` measures discovery and import graph building. On Universe master (77k documents) both take about 11 to 12 seconds in total on a 10-core Mac.

## TODO

### Bugs

- [ ] `FolderIndex.start` passes `config.jpaths` to `discover_docs` as its `ignore` argument, so jpaths are excluded from discovery instead of used for resolution.
- [ ] `config.exclude` is never used.
- [ ] `ImportGraph` always gets `[root]` as its jpaths instead of `config.jpaths`.

### LSP features

- [ ] **Unsaved content.** Documents are read from disk, so features reflect the last saved version of a file rather than the editor buffer. See [Document synchronization](DESIGN.md#document-synchronization).
- [ ] **AST cache.** Every request parses and resolves the document again. See [AST cache](DESIGN.md#ast-cache).
- [ ] **Find references from a use.** With the cursor on a reference rather than the definition, find references returns nothing. It should first resolve the reference to its definition.
- [ ] **`includeDeclaration`.** Find references ignores it and never includes the definition itself.
- [ ] **Field references.** Go to definition and find references don't handle fields (`o.f`) yet.
- [ ] **Cross-document results.** Definitions and references stay within one document until [cross-document analysis](DESIGN.md#cross-document-analysis) exists.

### Analysis

- [ ] **Field reference resolution.** [Scope resolution](DESIGN.md#scope-resolution) describes recording each field reference's origins (`("local", Field)` or `("imported", URI)`), but only variable references are resolved so far.
- [ ] **Cross-document analysis.** Not started. See [Cross-document analysis](DESIGN.md#cross-document-analysis).

### Server

- [ ] **No workspace folders.** `initialized` creates no `FolderIndex` when the client sends none. Single-file features still work, but nothing uses the import graph.
- [ ] **Readiness.** `FolderIndex.ready` exists, but no handler checks it yet. `initialized` also waits for every folder's scan to finish before returning.
- [ ] **Scan failures.** If discovery or the import graph build fails, `import_graph` stays `None` and nothing reports why.

### Design doc

- [ ] Component diagram and module layout ([Architecture](DESIGN.md#architecture)).
- [ ] [Cross-document analysis](DESIGN.md#cross-document-analysis).
- [ ] [Document synchronization](DESIGN.md#document-synchronization).
- [ ] How TTII is measured ([Benchmarking](DESIGN.md#benchmarking)).
- [ ] The [open questions](DESIGN.md#open-questions).
