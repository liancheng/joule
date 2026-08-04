type Maybe[U] = tuple[U] | tuple[()]


def maybe[U](v: U | None) -> Maybe[U]:
    return () if v is None else (v,)


def just[U](v: U | None) -> U:
    assert v is not None
    return v
