import heapq
import multiprocessing
import os
import threading
from collections.abc import Callable
from concurrent.futures import (
    FIRST_COMPLETED,
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    wait,
)
from itertools import batched
from pathlib import Path

import joule.trees as T
from joule.parsers import parse_document

progress_queue: multiprocessing.Queue[int | None] | None = None


def bin_pack_by_size(sizes: dict[Path, int], n_bins: int) -> list[list[Path]]:
    """Bin-packs source files into `n_bins` bins to minimize the largest bin's total size."""
    bins: list[tuple[int, int, list[Path]]] = [(0, i, []) for i in range(n_bins)]
    heapq.heapify(bins)

    for path, size in sorted(sizes.items(), key=lambda item: -item[1]):
        total_size, i, bin_paths = heapq.heappop(bins)
        bin_paths.append(path)
        heapq.heappush(bins, (total_size + size, i, bin_paths))

    return [bin_paths for _, _, bin_paths in bins]


def parse_batch(batch: dict[Path, str]) -> tuple[list[T.Document], list[Path]]:
    docs: list[T.Document] = []
    failed: list[Path] = []

    for path, source in batch.items():
        try:
            docs.append(parse_document(source, path.as_uri()))
        except Exception:
            failed.append(path)
        if progress_queue is not None:
            progress_queue.put(1)

    return docs, failed


class WorkspaceIndex:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.documents: dict[T.URI, T.Document] = {}
        self.imports: dict[T.URI, T.URI] = {}
        self.importedBy: dict[T.URI, T.URI] = {}

    def discover(
        self,
        advance: Callable[[int], None] = lambda _: None,
    ) -> dict[Path, int]:
        sources: dict[Path, int] = {}
        suffixes = (
            ".jsonnet",
            ".libsonnet",
            ".jsonnet.TEMPLATE",
        )

        def scan_dirs(paths: list[str]) -> list[str]:
            dirs: list[str] = []

            for path in paths:
                with os.scandir(path) as entries:
                    for entry in entries:
                        if entry.is_file():
                            if entry.path.endswith(suffixes):
                                sources[Path(entry.path)] = entry.stat().st_size
                                advance(1)
                        elif not entry.name.startswith((".", "experimental")):
                            dirs.append(entry.path)

            return dirs

        with ThreadPoolExecutor(max_workers=(os.cpu_count() or 1) * 2) as pool:
            pending = {pool.submit(scan_dirs, [self.root.as_posix()])}
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                subdirs = [subdir for future in done for subdir in future.result()]
                batches = batched(subdirs, 1024)
                pending.update(pool.submit(scan_dirs, batch) for batch in batches)

        return sources

    def load(
        self,
        sources: dict[Path, int],
        parallelism: int,
        advance: Callable[[int], None] = lambda _: None,
    ) -> tuple[list[T.Document], list[Path]]:
        docs: list[T.Document] = []
        failed: list[Path] = []

        bins: list[dict[Path, str]] = [
            {path: path.read_text() for path in bin_paths}
            for bin_paths in bin_pack_by_size(sources, parallelism)
        ]

        mp_context = multiprocessing.get_context("fork")
        progress_queue: multiprocessing.Queue[int | None] = mp_context.Queue()

        def init_worker(queue: multiprocessing.Queue[int | None]) -> None:
            global progress_queue
            progress_queue = queue

        def drain() -> None:
            while (n := progress_queue.get()) is not None:
                advance(n)

        drain_thread = threading.Thread(target=drain)
        drain_thread.start()

        try:
            with ProcessPoolExecutor(
                max_workers=parallelism,
                mp_context=mp_context,
                initializer=init_worker,
                initargs=(progress_queue,),
            ) as pool:
                for batch_docs, batch_failed in pool.map(parse_batch, bins):
                    docs.extend(batch_docs)
                    failed.extend(batch_failed)
        finally:
            progress_queue.put(None)
            drain_thread.join()

        return docs, failed
