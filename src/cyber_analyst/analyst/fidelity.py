"""Conservative exact-token checks, not a semantic truth verifier."""
import ipaddress
import json
import re
from decimal import Decimal

_EXACT = re.compile(
    r'\bCVE-\d{4}-\d{4,}\b|'
    r'[\w.+-]+@[\w.-]+\.[\w-]+|'
    r'(?<!\w)(?:\d{1,3}\.){3}\d{1,3}(?!\w)|'
    r'(?<!\w)(?:[0-9a-fA-F]{0,4}:){2,}[0-9a-fA-F:.]*(?!\w)|'
    r'\b(?=[\w.-]*\d)[a-zA-Z][\w]*(?:[-.][\w]+)+\b', re.IGNORECASE)
_NUMBER = re.compile(r'(?<![\w])[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?(?![\w])')


def _tokens(text):
    exact = set()
    def mask(match):
        token = match.group()
        try:
            token = str(ipaddress.ip_address(token))
        except ValueError:
            pass
        exact.add(token)
        return ' ' * len(match.group())
    remainder = _EXACT.sub(mask, text)
    return exact, {Decimal(m.group().replace(',', '.')) for m in _NUMBER.finditer(remainder)}


def validate_text(text, evidence):
    exact, numbers = set(), set()
    def values(value):
        if isinstance(value, dict):
            for child in value.values():
                yield from values(child)
        elif isinstance(value, list):
            for child in value:
                yield from values(child)
        elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
            yield str(value)
    for item in evidence:
        for value in values(json.loads(item.content_json)):
            e, n = _tokens(value)
            exact.update(e)
            numbers.update(n)
    claimed, numeric = _tokens(text)
    if claimed - exact:
        raise ValueError('Unsupported exact identifier token in generated text')
    if numeric - numbers:
        raise ValueError('Unsupported numeric token in generated text')
