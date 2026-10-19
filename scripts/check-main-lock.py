"""Refuse unreviewed downgrades before applying the tested Windows constraints."""
import importlib.metadata as md
from pathlib import Path
try:
    from packaging.version import Version
except ImportError:
    from pip._vendor.packaging.version import Version
root=Path(__file__).resolve().parents[1]
newer=[]
for line in (root/'configs/requirements/windows-main.lock.txt').read_text(encoding='utf-8').splitlines():
    if not line or line.startswith('#'):continue
    name,pinned=line.split('==')
    try:current=md.version(name)
    except md.PackageNotFoundError:continue
    if Version(current)>Version(pinned):newer.append(name)
if newer:raise SystemExit('Refusing automatic downgrade: '+', '.join(newer)+'. Review the lock or use a fresh isolated environment.')
print('No unreviewed main-environment downgrade required.')
