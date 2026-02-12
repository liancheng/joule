import dataclasses as D
from typing import Any


class PrettyTree:
    """An abstract class for pretty-printing tree-like structures."""

    def node_text(self) -> str:
        """Returns a single-line string representing a tree node."""
        ...

    def children(self) -> list["PrettyTree"]:
        """Returns a list of child nodes."""
        ...

    def non_empty_fields(self, node) -> list[tuple[D.Field[Any], Any]]:
        """Returns non-empty fields and their values of a dataclass instance.

        A field is non-empty if its value is neither `None` nor an empty list.
        """
        assert D.is_dataclass(node)
        return [
            (f, v)
            for f in D.fields(node)
            if (v := getattr(node, f.name)) is not None
            if not isinstance(v, list) or len(v) > 0
        ]

    def __repr__(self):
        def grow(lines: list[str], nodes: list[PrettyTree], branches: str = ""):
            for i, node in enumerate(nodes):
                last_child = i == len(nodes) - 1
                new_branch = ".   " if last_child else "|   "
                fork = "`-- " if last_child else "|-- "

                lines.append(f"{branches}{fork}{node.node_text()}")
                grow(lines, node.children(), branches + new_branch)

        lines = [self.node_text()]
        grow(lines, self.children())

        return "\n".join(lines)
