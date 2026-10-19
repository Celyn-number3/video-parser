"""Rebuild the portable single-file prototype using only the Python standard library."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    template = (ROOT / 'index.template.html').read_text(encoding='utf-8')
    styles = (ROOT / 'styles.css').read_text(encoding='utf-8')
    script = (ROOT / 'app.js').read_text(encoding='utf-8')
    if '</style' in styles.lower():
        raise SystemExit('styles.css must not contain a closing </style> tag')
    if '</script' in script.lower():
        raise SystemExit('app.js must not contain a closing </script> tag')
    html = template.replace('__STYLES__', styles.rstrip('\n')).replace('__SCRIPT__', script.rstrip('\n'))
    (ROOT / 'index.html').write_text(html, encoding='utf-8', newline='\n')
    print('Self-contained HTML:', len(html.encode('utf-8')), 'bytes')


if __name__ == '__main__':
    main()
