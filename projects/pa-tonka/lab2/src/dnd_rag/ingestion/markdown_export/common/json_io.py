"""Unambiguous UTF-8 JSON decoding shared by input and output boundaries."""

import json
import math
import re


def strict_json(raw):
    """Reject ambiguous objects and non-JSON numeric constants at the boundary."""

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f'Duplicate JSON key: {key!r}')
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f'Invalid JSON constant: {value}')

    def number(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError(f'Nonfinite JSON number: {value}')
        return result

    surrogate = re.compile('[\ud800-\udfff]')

    def unicode_values(value):
        if isinstance(value, str):
            if surrogate.search(value):
                raise ValueError('Unpaired Unicode surrogate in JSON string')
        elif isinstance(value, dict):
            for key, child in value.items():
                unicode_values(key)
                unicode_values(child)
        elif isinstance(value, list):
            for child in value:
                unicode_values(child)

    if isinstance(raw, bytes):
        raw = raw.decode('utf-8')
    result = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant, parse_float=number)
    unicode_values(result)
    return result
