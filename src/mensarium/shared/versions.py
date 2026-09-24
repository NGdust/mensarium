def parse_version(value: str) -> tuple[int, ...]:
    return tuple(int(p) for p in value.split(".") if p.isdigit())
