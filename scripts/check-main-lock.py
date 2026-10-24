"""Refuse unreviewed downgrades before applying the tested Windows constraints."""
import importlib.metadata as md
import tomllib
try:
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
except ImportError:
    from pip._vendor.packaging.requirements import Requirement
    from pip._vendor.packaging.utils import canonicalize_name
from pathlib import Path
try:
    from packaging.version import Version
except ImportError:
    from pip._vendor.packaging.version import Version
root=Path(__file__).resolve().parents[1]
# Detect missing direct dependencies before a --no-deps editable install can hide them.
lock = {}
for line in (root/'configs/requirements/windows-main.lock.txt').read_text(encoding='utf-8').splitlines():
    if line and not line.startswith('#'):
        name, version = line.split('==')
        lock[canonicalize_name(name)] = version
requirements = tomllib.loads((root/'pyproject.toml').read_text(encoding='utf-8'))['project']['dependencies']
for value in requirements:
    requirement = Requirement(value)
    if requirement.marker and not requirement.marker.evaluate():
        continue
    pinned = lock.get(canonicalize_name(requirement.name))
    if pinned is None or not requirement.specifier.contains(pinned):
        raise SystemExit('Missing or incompatible dependency in main lock: ' + requirement.name)
newer=[]
for line in (root/'configs/requirements/windows-main.lock.txt').read_text(encoding='utf-8').splitlines():
    if not line or line.startswith('#'):continue
    name,pinned=line.split('==')
    try:current=md.version(name)
    except md.PackageNotFoundError:continue
    if Version(current)>Version(pinned):newer.append(name)
if newer:raise SystemExit('Refusing automatic downgrade: '+', '.join(newer)+'. Review the lock or use a fresh isolated environment.')
print('No unreviewed main-environment downgrade required.')
