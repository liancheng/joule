# Joule TODO

This document records the current progress and the work that remains. For the design, see [DESIGN.md](DESIGN.md).

## Progress

### LSP features

Each feature is a provider class in `joule.features`. `joule.server` connects each provider to an LSP method. All the current features need only the current document:

| Method                        | Provider                 | Scope            |
| ----------------------------- | ------------------------ | ---------------- |
| `textDocument/documentSymbol` | `DocumentSymbolProvider` | Current document |
| `textDocument/definition`     | `DefinitionProvider`     | Current document |
| `textDocument/references`     | `ReferencesProvider`     | Current document |
| `textDocument/foldingRange`   | `FoldingRangeProvider`   | Current document |

For each request, the server parses the document and runs [scope resolution](DESIGN.md#scope-resolution) on it (`resolve_document`). These features do not read the [import graph](DESIGN.md#folderindex-and-the-import-graph). Thus they also work for documents that are not in a workspace folder, for example a stray file in `/tmp`.

- **Document symbols** make a hierarchy that follows the nested structure of the code:
  - Locals and object locals are `Variable`s. If a local is bound to a function, it is a `Function`.
  - Function parameters and comprehension variables (`for x in ...`) are `Variable`s.
  - Static field keys are `Field`s. The provider skips computed keys, because their names are known only after evaluation. See [Non-goals](DESIGN.md#non-goals).
- **Go-to-definition** operates on variable references (`Id.VarRef`). It returns the `Id.Var` that defines the reference.
- **Find references** operates on a variable definition (`Id.Var`). It returns each `Id.VarRef` that refers to it.
- **Folding ranges** cover these expressions when they are on more than one line: arrays, objects, array comprehensions, object comprehensions, functions, and parenthesized expressions.

### Workspace loading

- `initialized` reads the configuration (`jpaths`, `exclude`, `extensions`) through `workspace/configuration`. Then it creates one `FolderService` for each workspace folder.
- `FolderService` finds the documents with `fd`. Then it builds the import graph in a process pool, with batches of work and with cached import resolution.
- `joule benchmark` measures the discovery and the build of the import graph.

## TODO

### LSP features

- [ ] **Unsaved content.** Joule reads documents from the disk. Thus the features show the last saved version of a file, not the editor buffer. See [Document synchronization](DESIGN.md#document-synchronization).
- [ ] **AST cache.** For each request, Joule parses and resolves the document again. See [AST cache](DESIGN.md#ast-cache).
- [ ] **Find references from a use.** If the cursor is on a reference, not on the definition, find references returns nothing. It must first resolve the reference to its definition.
- [ ] **`includeDeclaration`.** Find references ignores this parameter. It never includes the definition in the results.
- [ ] **Field references.** Go-to-definition and find references do not support fields (`o.f`) yet.
- [ ] **Cross-document results.** Definitions and references stay in one document until [cross-document analysis](DESIGN.md#cross-document-analysis) exists.

### Analysis

- [ ] **Field reference resolution.** [Scope resolution](DESIGN.md#scope-resolution) tells how Joule records the origins of each field reference (`("local", Field)` or `("imported", URI)`). But at this time, Joule resolves only variable references.
- [ ] **Cross-document analysis.** There is no implementation yet. See [Cross-document analysis](DESIGN.md#cross-document-analysis).

### Server

- [ ] **No workspace folders.** If the client sends no workspace folders, `initialized` creates no `FolderService`. The single-file features still work, but nothing uses the import graph.
- [ ] **Readiness.** `FolderService.ready` exists, but no handler checks it yet. Also, `initialized` waits until the scan of each folder is complete before it returns.
- [ ] **Scan failures.** If the discovery or the build of the import graph fails, `FolderService.index` stays `None`. Nothing tells the reason.

### Design document

- [ ] Add the component diagram and the module layout ([Architecture](DESIGN.md#architecture)).
- [ ] Write [Cross-document analysis](DESIGN.md#cross-document-analysis).
- [ ] Write [Document synchronization](DESIGN.md#document-synchronization).
- [ ] Tell how Joule measures TTII ([Benchmarking](DESIGN.md#benchmarking)).
- [ ] Answer the [open questions](DESIGN.md#open-questions).
