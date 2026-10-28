"""Anki-importable CSV and plain table CSV.

Anki reads UTF-8 CSV with optional `#separator`/`#html`/`#tags column` headers. Cards are
written as Basic notes (front, back, tags); the caller decides what belongs on each side.
No third-party dependency and no file access happens here.
"""
import csv
import io
from html import escape

ANKI_HEADER = ('#separator:Comma', '#html:true', '#tags column:3')


def html(text):
    """Escape text for an Anki field and keep line breaks visible."""
    value = str(text if text is not None else '').replace('\r\n', '\n').replace('\r', '\n')
    return escape(value).replace('\n', '<br>')


def cards_csv(cards):
    """cards: [{'front': str, 'back': str, 'tags': str}] → UTF-8 CSV bytes."""
    buffer = io.StringIO(newline='')
    writer = csv.writer(buffer, lineterminator='\n')
    for line in ANKI_HEADER:
        writer.writerow([line])
    for card in cards:
        writer.writerow([card.get('front', ''), card.get('back', ''), card.get('tags', '')])
    return buffer.getvalue().encode('utf-8')


def table_csv(header, rows, bom=False):
    """Plain spreadsheet CSV. A BOM helps Excel detect UTF-8; Anki exports do not use it."""
    buffer = io.StringIO(newline='')
    writer = csv.writer(buffer, lineterminator='\n')
    writer.writerow(header)
    writer.writerows(rows)
    data = buffer.getvalue().encode('utf-8')
    return (b'\xef\xbb\xbf' + data) if bom else data
