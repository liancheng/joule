import heapq
import multiprocessing
import os
import threading
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


def bin_pack_by_size(sources: dict[Path, str], n_bins: int) -> list[dict[Path, str]]:
    """Bin-packs source files into `n_bins` bins to minimize the largest bin's total size."""
    bins = [(0, i, {}) for i in range(n_bins)]
    heapq.heapify(bins)

    for path, source in sorted(sources.items(), key=lambda item: -len(item[1])):
        total_size, i, bin_files = heapq.heappop(bins)
        bin_files[path] = source
        heapq.heappush(bins, (total_size + len(source), i, bin_files))

    return [bin_files for _, _, bin_files in bins]


def parse_batch(batch: dict[Path, str]) -> tuple[list[T.Document], list[Path]]:
    docs: list[T.Document] = []
    failed: list[Path] = []

    for path, source in batch.items():
        try:
            docs.append(parse_document(source, path.as_uri()))
        except Exception:
            failed.append(path)

    return docs, failed


class WorkspaceIndex:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.documents: dict[T.URI, T.Document] = {}
        self.imports: dict[T.URI, T.URI] = {}
        self.importedBy: dict[T.URI, T.URI] = {}

    def discover(self) -> dict[Path, str]:
        sources: dict[Path, str] = {}
        suffixes = (
            ".jsonnet",
            ".libsonnet",
            ".jsonnet.TEMPLATE",
        )

        def scan_dirs(paths: list[str]) -> list[str]:
            dirs: list[str] = []

            print(threading.get_ident(), len(paths), len(sources))

            for path in paths:
                with os.scandir(path) as entries:
                    for entry in entries:
                        if entry.is_file():
                            if entry.path.endswith(suffixes):
                                file = Path(entry.path)
                                sources[file] = file.read_text()
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
        sources: dict[Path, str],
        parallelism: int,
    ) -> tuple[list[T.Document], list[Path]]:
        docs: list[T.Document] = []
        failed: list[Path] = []
        bins = bin_pack_by_size(sources, parallelism)

        with ProcessPoolExecutor(
            max_workers=parallelism,
            mp_context=multiprocessing.get_context("fork"),
        ) as pool:
            for batch_docs, batch_failed in pool.map(parse_batch, bins):
                docs.extend(batch_docs)
                failed.extend(batch_failed)

        return docs, failed
