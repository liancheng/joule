from rich.text import Text


def side_by_side(lhs: Text | str, rhs: Text | str) -> Text:
    if isinstance(lhs, str):
        lhs = Text(lhs)

    if isinstance(rhs, str):
        rhs = Text(rhs)

    lhs_lines = lhs.split()
    rhs_lines = rhs.split()

    empty = Text.styled("", "default")
    shorter = lhs_lines if len(lhs_lines) < len(rhs_lines) else rhs_lines
    shorter.extend([empty] * abs(len(lhs_lines) - len(rhs_lines)))

    max_width = max(map(len, lhs.plain.splitlines()))
    sep = Text.styled(" : ", "grey50")

    return Text("\n").join(
        [
            lhs_line + padding + sep + rhs_line
            for lhs_line, rhs_line in zip(lhs_lines, rhs_lines)
            if (padding := " " * (max_width - len(lhs_line))) is not None
        ]
    )
