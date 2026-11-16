# Progress reports for workspace loading

The goal is to show the progress of workspace loading in the editor. For each workspace folder, Joule loads the workspace in two phases:

1. **Source discovery.** `fd` finds the sources. `fd` gives no partial results, so Joule does not know how far it is. The editor shows a spinner.
2. **Import graph construction.** Joule collects the importees of each source in a process pool. Joule knows the number of sources, so the editor shows a percentage and the count of processed files.

Joule uses the LSP work done progress (`window/workDoneProgress/create` and `$/progress`). pygls gives this API as `LanguageServer.work_done_progress`.

## Design

### Two progress tokens

A `WorkDoneProgressBegin` without a `percentage` starts an infinite progress. The LSP specification lets the client ignore the `percentage` of the subsequent reports. Thus one token cannot start as a spinner and then show a percentage. Each folder gets two tokens:

| Phase        | Title                                   | Begin           | Reports                                           |
| ------------ | --------------------------------------- | --------------- | ------------------------------------------------- |
| Discovery    | `Discovering Jsonnet sources: <folder>` | No `percentage` | None                                              |
| Import graph | `Building import graph: <folder>`       | `percentage=0`  | `percentage` and `message="<done>/<total> files"` |

The discovery ends when the discovery is done. A `finally` block ends each token that is still open. Thus a failure does not leave a spinner in the editor.

### Layers

- **Core layer.** `ImportGraph` stays synchronous and does not know LSP. The build gets an optional observer, and it calls the observer from the thread that runs the build:

  ```python
  class BuildObserver(Protocol):
      def on_discovery_done(self, sources: int) -> None: ...
      def on_source_collected(self, done: int, total: int) -> None: ...
  ```

  `_build` calls `on_discovery_done` after `discover_sources`. It calls `on_source_collected` in the loop over the results of the mapper. `executor.map` gives the results in sequence, so `done` increases by one for each source.

- **Service layer.** `FolderService.start` creates the progress reporter and gives it to the build. The build runs in a thread (`A.to_thread`), but pygls must send the messages from the event loop. Thus the reporter sends each message with `loop.call_soon_threadsafe`. The event loop runs the posted callbacks after the build returns or raises. The service then waits for a barrier on the loop, so that each `end` comes after the last report.

#### Design decision: How does the build tell its progress?

1. Split the build. The service calls `discover_sources`, and then it gives the sources to a new build method.
   - **Pros:** No observer. The service knows the end of discovery without a callback.
   - **Cons:** The callers decide which files are sources again. The refactor of `ImportGraph` removed this, so that the graph alone decides which files are sources.
2. An observer with one method for each phase.
   - **Pros:** The interface of the build does not change for callers that do not need progress. The tests can record the calls with a small fake.
   - **Cons:** The observer runs in the thread of the build. The service must move each message to the event loop.

Joule takes option 2.

#### Design decision: How often does Joule send a report?

Grafonnet has 1,413 sources. Joule targets to handle large monorepos containing over 100k Jsonnet source files. One report for each source is too many messages.

1. Send a report for each source.
   - **Pros:** Simple.
   - **Cons:** 100k messages on a large monorepo. Each message goes through the event loop and the client.
2. Send a report only when the integer percentage changes.
   - **Pros:** A maximum of 101 reports for each folder. No timer.
   - **Cons:** On a small workspace, the count in the message changes only in steps.
3. Send a report at most each 100 ms.
   - **Pros:** The rate is constant on all workspaces.
   - **Cons:** It needs a clock in the reporter, and the tests must control the clock.

Joule takes option 2. The reporter also sends the last report, at 100%, before `end`.

### Client support

- Joule sends progress only if the client sets `window.workDoneProgress` in its capabilities. If not, the service gives no observer to the build.
- Joule creates each token with `work_done_progress.create_async` before `begin`. The token must be unique, for example `joule/discovery/<folder URI>` and `joule/import-graph/<folder URI>`.
- `initialized` starts the services in sequence. Thus the editor shows the progress of one folder at a time.
- Neovim stores the `$/progress` messages. It stores them for `vim.lsp.status()` and fires the `LspProgress` autocmd. It does not show them by default. A plugin, such as noice.nvim, snacks.nvim or fidget.nvim, shows them. To check that the reports arrive, run `:lua =vim.lsp.status()` during the load.

## Manual test

1. Open a source in a large workspace, for example `~/local/src/grafonnet/generator/panel.libsonnet`.
2. Check that the editor shows the spinner of the discovery. Then check that it shows the percentage of the import graph.
3. If no progress shows, reinstall Joule first. After a dependency changes, run `uv tool install --force --editable <repo>`. A stale install crashes with `ModuleNotFoundError: No module named 'gitignore_parser'`, so no progress can show.

## Plan

Each step is one commit. After each step, `./test.sh` and `./lint.sh` must pass.

### Progress

- [x] Add `BuildObserver` to the build of `ImportGraph`
- [x] Report the progress from `FolderService`
- [x] Measure the cost of the reports

### Step: Add `BuildObserver` to the build of `ImportGraph`

- Add `BuildObserver` to `joule.analysis.imports`.
- `build` and `build_in_parallel` get an optional `observer` keyword argument. `_build` calls it as the Layers section tells.
- Tests: a fake observer records the calls during a sequential `build`. It must record one `on_discovery_done` with the number of sources, and then `done` from 1 to the number of sources.

### Step: Report the progress from `FolderService`

- Add a reporter in `joule.server` that implements `BuildObserver` with `work_done_progress`. It sends the messages with `loop.call_soon_threadsafe`, and it sends a report only when the integer percentage changes.
- `FolderService.start` creates the two tokens, begins the discovery progress, and runs the build with the reporter. The reporter ends the discovery when the discovery is done. A `finally` block ends each token that is still open.
- A workspace with no sources ends the import graph progress at once, with `message="0 files"`. Do not divide by zero.
- Tests: give the reporter a fake sender. Make sure that the begin of the discovery has no `percentage`, that the percentages increase, that there are a maximum of 101 reports, and that each token ends also if the build raises an exception.

### Step: Measure the cost of the reports

- Run the build on grafonnet, with and without an observer. The build time must not increase by more than 1%.
- Record the numbers in this document.

`joule benchmark` has no option for an observer. Thus a script timed `ImportGraph.build_in_parallel` in `A.to_thread`, as `FolderService.start` runs it. The script used the real `FolderProgress` with a sender that does nothing. It changed the sequence of the two cases in each round. The machine has 10 CPUs.

| Workspace | Sources | Edges   | Rounds | Without observer | With observer | Difference | Reports |
| --------- | ------- | ------- | ------ | ---------------- | ------------- | ---------- | ------- |
| grafonnet | 1,324   | 1,413   | 2 × 10 | 1.004 s, 0.936 s | 1.009 s, 0.935 s | +0.54 %, −0.07 % | 101 |

The times are medians. The time of one build changes by about ±10 %. Thus the cost of the reports is less than the noise, and it is in the budget of 1 %. The thread posts a maximum of 101 messages for each folder, so the cost does not increase with the number of sources.

### Out of scope

- Cancellation of the load from the editor (`cancellable=True`).
- Progress inside source discovery. `fd` gives no partial output.
- Progress for incremental updates on file events. They are fast.
