"""Test-only stand-in for the external check(path) contract, not a production validator."""
import json
import math
from pathlib import Path


def check(path):
    source = Path(path)
    try:
        body = json.loads(source.read_text(encoding='utf-8'))['body']
        valid = isinstance(body, list) and bool(body)
        for segment in body if isinstance(body, list) else []:
            valid = valid and isinstance(segment, dict)
            if not valid:
                break
            start, end = segment.get('from'), segment.get('to')
            valid = (type(start) in (int, float) and type(end) in (int, float)
                     and math.isfinite(start) and math.isfinite(end) and 0 <= start < end
                     and isinstance(segment.get('content'), str) and bool(segment['content'].strip()))
            if not valid:
                break
        for extension in ('srt', 'md'):
            companion = source.parent.parent / ('_' + extension) / (source.stem + '.' + extension)
            valid = valid and companion.is_file() and bool(companion.read_text(encoding='utf-8').strip())
        return {'ok': bool(valid), 'lines': len(body) if valid else 0}
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        return {'ok': False, 'lines': 0}
