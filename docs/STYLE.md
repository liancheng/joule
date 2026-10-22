# Joule Code Style

This document tells how to write code for Joule. Follow it, so that new code is consistent with the current code.

## Tools

- Use Python 3.14 or later. Use the current syntax:
  - PEP 695 generics: `def maybe[U](v: U | None)` and `type Maybe[U] = ...`.
  - Deferred annotations: write forward references without quotes and without `from __future__ import annotations`.
  - `except A, B:` without parentheses.
- Format and lint the code with `ruff format` and `ruff check` (`./lint.sh`). Use the default configuration, with a line length of 88 columns.
- Check the types with `ty check`. Annotate all parameters, and all return types other than `None`. Narrow optional types explicitly. Do not suppress type errors.
- Run the tests with `./test.sh`, which runs pytest. `./sign-off.sh` runs the checks of the tree-sitter grammar, then the tests.

## Imports

- Sort the imports in this sequence: the standard library, third-party packages, `joule`, and `tests`. Ruff sorts them for you.
- If you use a module frequently, import it with a single capital letter as its alias:

  | Alias | Module                          |
  | ----- | ------------------------------- |
  | `A`   | `asyncio`                       |
  | `D`   | `dataclasses`                   |
  | `L`   | `lsprotocol.types`              |
  | `P`   | `os.path` (or `parsy` in tests) |
  | `T`   | `joule.syntax.trees`            |

  The code then reads `T.Id.VarRef`, `L.Location`, and `D.field(...)`.

- Import other names directly, for example `from pathlib import Path`.
- Use absolute imports, for example `from joule.maybe import maybe`. Use relative imports only to re-export names in the `__init__.py` of a package.

## Modules and packages

- Joule has these package layers, from low to high:
  1. `syntax`: trees, the visitor, and the pretty-printer.
  2. `analysis`: scopes and imports.
  3. `features`: LSP providers.
  4. `workspace`: `FolderIndex` and the discovery of documents. This layer and the lower layers are synchronous.
  5. `server` and `cli`. The `server` package has the code that uses `asyncio`, threads, or process pools: `JouleLanguageServer` and `FolderService`.

  A module can import modules from its layer and from lower layers. It must not import modules from higher layers.

- A package can keep its implementation in private modules, such as `features/_definition.py`. Then re-export the public names from the `__init__.py` of the package.
- Declare `__all__` in each module that has a public API. Sort the names alphabetically. If `__all__` is long, as in `trees.py`, add a test to make sure that it is complete.

## Names

- Give a class a noun name that tells its role: `DefinitionProvider`, `ScopeResolver`, `ImportResolver`, `ImportGraphBuilder`, `FolderIndex`.
- Give a function or a method a verb name: `serve`, `resolve`, `build`, `find_definition`, `discover_docs`.
- Name conversions `to_*` and `from_*`, for example `to_range`, `to_location`, `from_cst`, and `from_lsp`.
- Name a helper that gets a value from a node `*_of`, for example `span_of`, `text_of`, `field_of`, and `enum_of`.
- In a small scope, use short conventional names:
  - `t` for the tree that a visitor method visits.
  - `f`, `k`, `b`, `a`, and `p` for a field, a key, a bind, an assert, and a parameter in a loop.
  - `doc`, `uri`, `pos`, and `node`.
- Write enum members in CamelCase, for example `Visibility.Hidden` and `ImportKind.Default`.
- If a name is the same as a Python keyword or builtin, add an underscore at the end: `import_`, `self_`, `super_`.

## Classes

- Declare the instance attributes with annotations in the class body. Then set them in `__init__`:

  ```python
  class DefinitionProvider:
      uri: str
      doc: T.Document

      def __init__(self, uri: str, doc: T.Document):
          self.uri = uri
          self.doc = doc
  ```

- Put related attributes in a group. Keep private state, such as caches, separate from the public attributes. Start the names of private attributes with `_`.
- If a class only holds data, use `@D.dataclass(slots=True)`. For a value type, also add `frozen=True`.
- Use slots where memory is important. Joule builds ASTs for tens of thousands of files.
- Some fields get their values after construction, for example `parent`, `field_scope`, and `top_level_scope`. Declare these fields with `D.field(default=None, init=False, repr=False, compare=False)`. Then they have no effect on equality, hashes, or printed output.
- Mark each override with `@override`. This includes properties: put `@property` above `@override`.
- Write alternative constructors as `@staticmethod`s, for example `from_cst`, `from_lsp`, and `empty`. If a subclass must get an instance of its own type, use a `@classmethod` that returns `typing.Self`, as in `Span.from_points`.
- If a setup is expensive and occurs only one time, put it in a module-level function with `@functools.cache`. Examples are `parser()`, `language()`, and `import_cursor()`.

## Control flow

- Use comprehensions and generator expressions, not loops that append to a list. You can nest `for` clauses. Nested clauses are frequent together with `maybe`.
- For optional values, use `joule.maybe`, not `if x is not None` blocks:
  - `maybe(x)` changes `X | None` to a tuple with zero or one item. Use it in a comprehension.
  - `head_or_none(gen)` gives the first item of a generator, or `None`.
  - `just(x)` asserts that a value is not `None`. Tests use it most.

  ```python
  return [
      location
      for node in maybe(self.doc.node_at(T.Point.from_lsp(pos)))
      for location in self.find_definition(node)
  ]
  ```

- To dispatch on types, use `match` / `case`. Do not use chains of `isinstance`. If other cases are possible, add `case _:` at the end.
- To bind a value and test it in one expression, use the walrus operator: `if (child := node.child_by_field_name(name)) is None:`.
- After a guard that raises an exception, put the normal path in an explicit `else:` block:

  ```python
  if node.type not in node_types:
      raise MalformedError(...)
  else:
      return node
  ```

- For a short choice between two values, use a conditional expression. If the expression is too long for one line, put it in parentheses on more than one line.
- If you must restore a state, use `with` and `@contextmanager`. Examples are the current scope and the breadcrumb of symbols (`activate`).
- If a constructor has many arguments of the same type, give each argument as a keyword argument on its own line. Examples are `L.DocumentSymbol(...)` and `T.Field(...)`.

## Errors

- If a parse fails, raise `MalformedError`. Put the node type in quotes in the message: `f'Expected {expected}, but got "{node.type}".'`.
- `Tree.from_cst` changes a `MalformedError` into a `Malformed` node. Thus one bad subtree does not cause the full document to fail.
- Catch I/O errors on documents as `OSError` at the boundary. Change them into `None` or into a "malformed" flag. Do not send them to the LSP handlers.
- If the original exception gives no useful data, use `raise ... from None`.
- Use `assert` only for invariants that the type checker cannot see.

## Comments and docstrings

- Do not add a comment, except for a tricky corner case that is difficult to understand at a glance. Clear names and simple code are better than comments.
- Write comments and docstrings in Simplified Technical English, at about 80%. See [Text style](#text-style).
- Start a docstring with a one-line summary in the third person. For example: "Resolves importees like the file importer of Jsonnet." Then add paragraphs that tell the behavior and the constraints.
- Write a docstring for a class if its contract is not obvious. Do not write docstrings for simple methods.
- In a comment, tell why the code does something. Do not tell what it does. If a cost or a measurement is the reason, give the number:

  ```python
  # Each worker process compiles the query only one time. A compilation takes about 66 µs.
  ```

- For a long explanation, use a `# NOTE: <topic>` block. If an example helps, add one. See the note about parameter scopes in `ScopeResolver.visit_fn`.
- Put code names in backticks, for example `` `is_file` ``.

## Performance

Joule must operate on workspaces with 100k files. Thus, write hot paths carefully:

- In tight loops, use `str` paths and `os.path`. Do not make intermediate `Path` objects. Add a comment that tells why.
- To decrease memory, pack small values into one value. For example, `Span` keeps two packed `int`s, not two `Point`s.
- In a cache, put the dictionary lookup in `try` / `except KeyError`.
- Measure with `joule benchmark` before and after a change. Record the numbers in the commit message or in the task document.

## Tests

- Write test classes in the `unittest` style. pytest runs them.
- Put the tests for a module or a provider in `tests/test_<module>.py`.
- If a test parses Jsonnet, make its class a subclass of `FakeDocumentTestCase`. Use the marked-span syntax of `tests.dsl.span_markers` for positions. Do not calculate coordinates manually.
- Name assertion helpers in camelCase, as `unittest` does: `assertDefined`, `assertVarBinding`. Name test methods `test_<case>`, in snake case.
- To put related cases into one test, use `self.subTest(...)`.
- To make expected trees, use the `SpanDSL` constructors and the helpers in `tests.dsl`, for example `t.at(1).num(1)`, `bind(...)`, and `field(...)`.
- If a test needs real files, make its class a subclass of `FakeWorkspaceTestCase`. Make the documents with `fake_document(source, path=...)`, and the other files with `layout(File(...), Dir(...), SymLink(...))`.

### Self-contained tests

A reader must understand a test without other parts of the file. Write each test as a short scenario that the reader can read from top to bottom:

- **Do not write tautological tests.** A test must be able to fail if the code under test is incorrect. Do not get the expected value from the code under test, or from a copy of its logic, for example the inverted map of the edges. Do not assert only what the setup of the test made true, for example that a file exists after the test made it. Make the expected value only from the data of the test, for example the fake documents or the `SpanDSL` constructors.
- **Declare the data in the test.** Each test makes only the documents and files that it needs, next to its assertions. Do not share one large fixture, such as a module-level workspace, between tests. A shared fixture separates the data from the test that uses it. Also, a change for one test can break other tests.
- **Remove expensive setup. Do not share it.** Do not put state in `setUpClass` to make a slow setup run only one time. Instead, make the setup cheap. For example, use the sequential `ImportGraphBuilder` in tests, not the process pool of `ParallelImportGraphBuilder`.
- **Make the setup visible.** Use context managers, such as `jpaths(...)`, `layout(...)`, and `fake_workspace(...)`, in the `with` statement of the test. Python enters them in sequence. Thus put each setting before the context manager that uses it, for example `jpaths(...)` before `fake_workspace(...)`.
- **Assert at the level of the domain.** Write assertion helpers that take the objects of the test, for example `assertImports(index, f1, f2)`. Do not use raw paths or the internal dictionaries in the tests.
- **Make failures easy to read.** In each assertion helper, set `__tracebackhide__ = True`, so that a failure points to the line in the test. Show paths relative to the workspace root.
- **Let the names and the sources tell the case.** If a comment must explain the data, the data is too far from the test. Comment only a corner case that the source cannot show.

## Shell scripts

- Write scripts for POSIX `sh`. Start each script with `#!/bin/sh`.
- Run tools through `uv`, for example `uv run --frozen` or `uv tool run`.

## Commits

- Start the subject with a [Conventional Commits](https://www.conventionalcommits.org/) prefix: `feat`, `fix`, `refactor`, `test`, `docs`, or `style`.
- After the prefix, write the subject as an imperative sentence. Start it with a capital letter. Put code in backticks. Do not put a period at the end. For example: ``refactor: Split `ImportGraphBuilder` out of `ImportGraph` ``.
- Write the commit message in Simplified Technical English. See [Text style](#text-style).
- Make each commit do one thing. After each commit, all tests must pass.
- For a large change, write a plan in a task document in `docs/tasks/`. Divide the plan into a sequence of commits.

## Documents

- Write documents in Simplified Technical English. See [Text style](#text-style).
- Use short paragraphs, lists, and tables. To refer to information in a different section, link to that section. Do not repeat the information.
- Record each design decision in a `#### Design decision: <question>` section. Give numbered options, each with **Pros:** and **Cons:**. Then write "Joule takes option N." and give the reason.
- If a section is not complete, mark it with `TODO:`. Record open work in `TODO.md`.

## Text style

Write comments, docstrings, commit messages, and documents in [ASD-STE100 Simplified Technical English](https://www.asd-ste100.org/) (STE). STE makes text clear for all readers. This includes readers whose first language is not English.

Apply STE at about 80%. Obey the rules below in most text. Break a rule only if the STE form is less clear.

### Rules

- **Short sentences.** Write a maximum of 20 words in an instruction, and a maximum of 25 words in a description.
- **One topic.** Write one instruction or one topic in each sentence. Write one topic in each paragraph, with a maximum of 6 sentences.
- **Active voice.** Write "The builder caches the lookups.", not "The lookups are cached."
- **Imperative for instructions.** Write "Create one resolver for each build."
- **Simple tenses.** Use the simple present, the simple past, and the future. Do not use "-ing" forms as verbs or as nouns. Write "When Joule resolves an import, ...", not "When resolving an import, ...".
- **No contractions.** Write "do not" and "is not", not "don't" and "isn't".
- **Articles.** Keep "a", "an", and "the". Do not remove them to make a sentence shorter. Headings and short list items can omit them.
- **One word for one thing.** Use the same word for the same thing in a text. Do not use that word for a different thing. In Joule, a _document_ is a Jsonnet source file that discovery found, and a _file_ is any file on the disk.
- **Single-word verbs.** If a single verb has the same meaning as a phrasal verb, use the single verb. Write "remove", not "get rid of". Write "find", not "look up".
- **Conditions first.** Put the condition before the instruction: "If the file does not exist, return `None`."
- **Lists.** Use a vertical list for a sequence of steps, or for three or more items.
- **Simple words.** Write "use", not "utilize". Write "start", not "commence". Write "help", not "facilitate". Write "about", not "approximately".

### What the other 20% permits

- **Technical names and technical verbs.** You can use domain terms and code names that are not in the STE dictionary. Examples are "importee", "jpath", "CST", "parse", "resolve", and all text in backticks. STE also permits technical names and technical verbs.
- **Longer sentences.** A sentence can be longer than the limit if a split makes the logic more difficult to follow. An example is a trade-off together with its reason.
- **Terms of the field.** You can use established terms such as "cache hit", "hot path", and "time-to-initial-intelligence".
- **Docstring summaries.** These use the third person, as Python convention recommends: "Returns a list of child nodes."

### Example

Before:

> Lookups are cached. The caches record only whether files exist, so they go stale once a file is created or deleted.

After:

> The resolver caches its lookups. The caches record only if files exist. After somebody creates or deletes a file, the caches are incorrect.
