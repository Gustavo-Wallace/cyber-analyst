"""Display labels only; source names, identifiers and values stay unchanged."""
import math


def format_number(value: int | float) -> str:
    """Concise display text; callers retain the original value in details/tooltips.

    Floats use twelve significant digits, including scientific notation at the
    extremes. Integers retain every digit; no result or evidence is changed.
    """
    if type(value) is not float:
        return str(value)
    if math.isnan(value):
        return 'NaN'
    if math.isinf(value):
        return '-Infinity' if value < 0 else 'Infinity'
    return format(value, '.12g') if value else '0'


def human_label(value: str) -> str:
    return value.replace('_', ' ').strip().capitalize()


def finding_supporting_label(value: str) -> str:
    """Humanize the operation field in an existing recommendation caption."""
    parts = value.split(' | ', 2)
    if len(parts) >= 2:
        parts[1] = ', '.join(human_label(operation) for operation in parts[1].split(', '))
    return ' | '.join(parts)
