#!/usr/bin/env python3
"""Run video-parser using its own environment without requiring a Web server."""
import os
from pathlib import Path
import subprocess
import sys


def main():
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')
    root = Path(os.environ.get('VIDEO_PARSER_ROOT') or Path(__file__).resolve().parents[3]).expanduser().resolve()
    entry = root / 'cli.py'
    if not entry.is_file():
        print(f'找不到项目 CLI：{entry}。请确认项目路径，或设置 VIDEO_PARSER_ROOT。', file=sys.stderr)
        return 1
    candidates = [root / '.venv' / 'Scripts' / 'python.exe', root / '.venv' / 'bin' / 'python']
    python = next((str(path) for path in candidates if path.is_file()), sys.executable)
    environment = dict(os.environ, PYTHONIOENCODING='utf-8')
    return subprocess.run([python, str(entry), *sys.argv[1:]], cwd=root, env=environment).returncode


if __name__ == '__main__':
    raise SystemExit(main())
