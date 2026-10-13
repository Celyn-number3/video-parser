"""Capture the installed active dependency closure; no installation/network or private paths."""
import importlib.metadata as md
from pathlib import Path
import sys
import tomllib
try:
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
except ImportError:
    from pip._vendor.packaging.requirements import Requirement
    from pip._vendor.packaging.utils import canonicalize_name

ROOT=Path(__file__).resolve().parents[1]
config=tomllib.loads((ROOT/'pyproject.toml').read_text(encoding='utf-8'))
pending=[Requirement(text) for text in config['project']['dependencies']+config['project']['optional-dependencies']['test']]
extras={};locked={}
while pending:
    requirement=pending.pop();name=canonicalize_name(requirement.name)
    previous=extras.get(name);wanted=set(requirement.extras)|{''}
    if previous is not None and wanted<=previous:continue
    extras[name]=(previous or set())|wanted
    distribution=md.distribution(name)
    if requirement.specifier and distribution.version not in requirement.specifier:raise RuntimeError(f'Installed {name} violates project constraints')
    locked[name]=distribution.version
    for text in distribution.requires or []:
        child=Requirement(text)
        if child.marker is None or any(child.marker.evaluate({'extra':extra}) for extra in extras[name]):pending.append(child)
output=ROOT/'requirements/windows-main.lock.txt'
output.write_text('# Tested installed dependency closure. Windows; Python '+sys.version.split()[0]+'\n# Generated without upgrading packages; frontend and isolated Whisper use their own locks.\n'+''.join(f'{name}=={version}\n' for name,version in sorted(locked.items())),encoding='utf-8')
print(f'Pinned {len(locked)} runtime/test dependencies; no packages installed or changed.')
