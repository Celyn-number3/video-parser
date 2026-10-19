"""Write THIRD-PARTY-NOTICES.txt for a staged portable build; run with the staged interpreter.

Usage: python write-third-party-notices.py <stage> <ffmpeg-zip-name> <ffmpeg-url>
"""
import importlib.metadata as metadata
from pathlib import Path
import sys


def license_of(meta):
    for field in ('License-Expression', 'License'):
        value = (meta.get(field) or '').strip().splitlines()
        if value and len(value[0]) <= 80 and value[0].upper() != 'UNKNOWN':
            return value[0]
    classifiers = [item.split('::')[-1].strip() for item in meta.get_all('Classifier') or [] if item.startswith('License ::')]
    return ', '.join(classifiers) or 'see package metadata'


def main(stage, ffmpeg_zip, ffmpeg_url):
    site = stage / 'python' / 'Lib' / 'site-packages'
    rows = sorted({(dist.metadata['Name'], dist.version, license_of(dist.metadata))
                   for dist in metadata.distributions(path=[str(site)])}, key=lambda row: row[0].lower())
    revision = ffmpeg_zip.split('-')[3] if ffmpeg_zip.count('-') > 3 else ''
    lines = [
        'Video Parser — third-party software notices',
        '============================================',
        '',
        'Video Parser itself is released under the MIT License (see LICENSE).',
        'This package bundles the following third-party software, each under its own license.',
        '',
        f'Python {sys.version.split()[0]} (embeddable distribution) — Python Software Foundation License',
        '  https://www.python.org/  ·  license: python/LICENSE.txt',
        '',
        'FFmpeg (ffmpeg.exe, ffprobe.exe and libav* DLLs in runtimes/ffmpeg/bin) — LGPL v2.1 or later',
        f'  Build: {ffmpeg_zip}',
        f'  Binary source: {ffmpeg_url}',
        '  Build scripts: https://github.com/BtbN/FFmpeg-Builds',
        f'  Corresponding source: https://github.com/FFmpeg/FFmpeg/tree/{revision[1:] if revision.startswith("g") else revision}'
        if revision else '  Corresponding source: https://ffmpeg.org/download.html',
        '  This is an LGPL build without GPL-only components. License text: runtimes/ffmpeg/LICENSE.txt',
        '',
        'Python packages (python/Lib/site-packages; full license texts are in each *.dist-info folder):',
        '',
    ]
    width = max(len(name) for name, _, _ in rows)
    lines += [f'  {name.ljust(width)}  {version:<14} {license_}' for name, version, license_ in rows]
    lines += ['', 'Microsoft Edge WebView2 and Microsoft Edge are provided by the operating system and are not redistributed.', '']
    (stage / 'THIRD-PARTY-NOTICES.txt').write_text('\n'.join(lines), encoding='utf-8')
    print(f'THIRD-PARTY-NOTICES.txt: {len(rows)} Python packages')


if __name__ == '__main__':
    main(Path(sys.argv[1]), sys.argv[2], sys.argv[3])
