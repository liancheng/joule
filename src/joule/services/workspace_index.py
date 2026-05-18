import heapq
import os
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from functools import reduce
from pathlib import Path

import joule.trees as T
from joule.parsers import parse_document


def partition_by_sizes(sources: dict[Path, str], n_bins: int) -> list[dict[Path, str]]:
    bins = [(0, i, {}) for i in range(n_bins)]
    heapq.heapify(bins)

    for path, source in sorted(
        sources.items(),
        key=lambda item: len(item[1]),
        reverse=True,
    ):
        total_size, i, bin_files = heapq.heappop(bins)
        bin_files[path] = source
        heapq.heappush(bins, (total_size + len(source), i, bin_files))

    return [bin_files for _, _, bin_files in bins]


class WorkspaceIndex:
    def __init__(self, root_uri: T.URI) -> None:
        self.root_uri = root_uri
        self.documents: dict[T.URI, T.Document] = {}
        self.imports: dict[T.URI, T.URI] = {}
        self.importedBy: dict[T.URI, T.URI] = {}

    def load(self):
        sources = {}
        suffixies = [".jsonnet", ".libsonnet", ".jsonnet.TEMPLATE"]

        def scan_dir(path: str) -> list[str]:
            dirs = []

            with os.scandir(path) as entries:
                for entry in entries:
                    if entry.is_file():
                        if any(entry.path.endswith(suffix) for suffix in suffixies):
                            file = Path(entry.path)
                            sources[file] = file.read_text()
                    else:
                        if not entry.name.startswith("."):
                            dirs.append(entry.path)

            return dirs

        def batch_parse(sources: dict[Path, str]):
            return {
                doc.uri: doc
                for path, source in sources.items()
                if (doc := parse_document(source, path.as_uri()))
            }

        N_CPU = os.cpu_count() or 1

        with (
            ThreadPoolExecutor(max_workers=N_CPU * 4) as parsing_pool,
            ThreadPoolExecutor() as io_pool,
        ):
            root_path = Path.from_uri(self.root_uri)
            pending = {io_pool.submit(scan_dir, root_path.as_posix())}

            while len(pending) > 0:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                pending.update(
                    io_pool.submit(scan_dir, subdir)
                    for future in done
                    for subdir in future.result()
                )

            bins = partition_by_sizes(sources, os.cpu_count() or 1)
            return reduce(lambda a, b: a | b, parsing_pool.map(batch_parse, bins))
