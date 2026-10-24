"""Rebuildable project-id index. Resource content hashes are never bypassed."""
import json
from pathlib import Path
import re
from threading import RLock
from video_parser.services.library_layout import manifest_paths

_lock=RLock()
_cache={}


def signature(root):
    if not root.is_dir(): return []
    return sorted([p.name,p.stat().st_mtime_ns] for p in root.iterdir() if p.is_dir() and not p.is_symlink())


def _safe(root,relative):
    path=root/relative
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or path.name!='project.json':raise ValueError('Unsafe index entry')
    return path


def lookup(root,identifier,loader,writer):
    root=Path(root)
    if not re.fullmatch('[a-f0-9]{32}',identifier):raise KeyError('Unknown project')
    with _lock:
        sig=signature(root);key=str(root.resolve());record=_cache.get(key)
        if record is None:
            try:
                p=root/'.project-index.json'
                if p.is_symlink() or p.stat().st_size>16*1024*1024:raise ValueError()
                record=json.loads(p.read_text(encoding='utf-8'))
                if record.get('version')!=1 or not isinstance(record.get('projects'),dict):raise ValueError()
            except (OSError,ValueError,AttributeError):record=None
        if record and record.get('signature')==sig:
            try:
                path=_safe(root,record['projects'][identifier]);data=loader(path)
                if data['id']==identifier:
                    _cache[key]=record
                    return data
            except (OSError,ValueError,KeyError,TypeError):pass
        mapping={};found=None
        for path in manifest_paths(root):
            try:
                data=loader(_safe(root,path.relative_to(root).as_posix()))
                if data['id'] in mapping:raise ValueError('Duplicate project identity')
                mapping[data['id']]=path.relative_to(root).as_posix()
                if data['id']==identifier:found=data
            except (OSError,ValueError,KeyError,TypeError):continue
        record={'version':1,'signature':sig,'projects':mapping};_cache[key]=record
        # Index is an optimization, not authoritative. Read-only libraries remain usable.
        if root.is_dir():
            try:writer(root/'.project-index.json',record)
            except OSError:pass
        if found is None:raise KeyError('Unknown project')
        return found


def invalidate(root):
    with _lock:_cache.pop(str(Path(root).resolve()),None)
