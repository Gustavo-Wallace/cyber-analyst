"""Shared deterministic entity normalization."""
from ipaddress import ip_address

SUPPORTED_TYPES = frozenset({
    'username', 'email', 'user_id', 'account_id', 'ip_address', 'hostname',
    'domain', 'cve', 'hash', 'asset_id', 'device_id', 'event_id',
})
CASEFOLD_TYPES = frozenset({'username', 'email', 'hostname', 'domain'})


def canonical_value(value, kind):
    value = value.strip()
    if not value:
        return None
    if kind in CASEFOLD_TYPES:
        return value.casefold()
    if kind == 'cve':
        return value.upper()
    if kind == 'hash':
        return value.lower()
    if kind == 'ip_address':
        try:
            return str(ip_address(value))
        except ValueError:
            return None
    return value

