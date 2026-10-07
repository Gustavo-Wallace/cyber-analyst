"""Deterministic English count labels for investigation summaries."""


def count_label(count: int, singular: str, plural: str | None = None, *, number_format: str = '') -> str:
    noun = singular if count == 1 else plural or singular + 's'
    return f'{count:{number_format}} {noun}'
