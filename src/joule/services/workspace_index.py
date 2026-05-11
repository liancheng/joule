import os
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from itertools import batched
from pathlib import Path
from typing import Callable, Iterable

import joule.trees as T


class WorkspaceIndex:
    def __init__(self, root_uri: T.URI) -> None:
        self.root_uri = root_uri
        self.documents: dict[T.URI, T.Document] = {}
        self.imports: dict[T.URI, T.URI] = {}
        self.importedBy: dict[T.URI, T.URI] = {}

    def scan(
        self,
        on_file: Callable[[Path], None],
        on_dir: Callable[[Path], bool],
        batch_size: int = 1024,
    ):
        def batch_scan(paths: list[Path]) -> list[Path]:
            def callback(entry: os.DirEntry) -> Iterable[Path]:
                path = Path(entry.path)
                if entry.is_file():
                    on_file(path)
                elif entry.is_dir() and on_dir(path):
                    yield path

            return [
                subdir
                for path in paths
                for entry in os.scandir(path)
                for subdir in callback(entry)
            ]

        with ThreadPoolExecutor() as pool:
            pending = {pool.submit(batch_scan, [Path.from_uri(self.root_uri)])}
            while len(pending) > 0:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                subdirs = (subdir for future in done for subdir in future.result())
                pending.update(
                    pool.submit(batch_scan, list(batch))
                    for batch in batched(subdirs, batch_size)
                )
