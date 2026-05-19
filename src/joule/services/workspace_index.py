import heapq
import multiprocessing
import os
from concurrent.futures import (
    FIRST_COMPLETED,
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    wait,
)
from pathlib import Path

import joule.trees as T
from joule.parsers import parse_document


def bin_pack_by_size(sources: dict[Path, str], n_bins: int) -> list[dict[Path, str]]:
    """LPT-pack sources into n_bins to minimize the largest bin's total size."""
    bins: list[tuple[int, int, dict[Path, str]]] = [(0, i, {}) for i in range(n_bins)]
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

    def load(self, parallelism: int) -> tuple[list[T.Document], list[Path]]:
        sources: dict[Path, str] = {}
        suffixes = (
            ".jsonnet",
            ".libsonnet",
            ".jsonnet.TEMPLATE",
        )

        def scan_dir(path: str) -> list[str]:
            dirs: list[str] = []

            with os.scandir(path) as entries:
                for entry in entries:
                    if entry.is_file():
                        if entry.path.endswith(suffixes):
                            file = Path(entry.path)
                            sources[file] = file.read_text()
                    elif not entry.name.startswith("."):
                        dirs.append(entry.path)

            return dirs

        with ThreadPoolExecutor() as io_pool:
            pending = {io_pool.submit(scan_dir, self.root.as_posix())}
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                pending.update(
                    io_pool.submit(scan_dir, subdir)
                    for future in done
                    for subdir in future.result()
                )

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
