"""Explicit OFFLINE, resumable directory migration. No overwrite, merge, or media rewrite."""
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from uuid import uuid4

from video_parser.services import library, library_index, library_layout as layout


def inventory(directory):
    """Hash every file, including manifests, unregistered sidecars and personal learning data."""
    library.contained(directory, 'project.json')
    files, directories = {}, []
    for parent, children, names in os.walk(directory, followlinks=False):
        parent = Path(parent)
        for name in children:
            path = library.contained(directory, (parent / name).relative_to(directory))
            if layout.linked(path):
                raise ValueError('Linked content cannot be migrated')
            directories.append(path.relative_to(directory).as_posix())
        for name in names:
            path = library.contained(directory, (parent / name).relative_to(directory))
            if not path.is_file():
                raise ValueError('Non-regular content cannot be migrated')
            before = path.stat()
            digest = library.digest(path)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                raise ValueError('Content changed during preflight; stop all writers and retry')
            files[path.relative_to(directory).as_posix()] = {'size': after.st_size, 'sha256': digest}
    return {'files': files, 'directories': sorted(directories)}


def _identity(project):
    info = library.identity(project)
    expected = hashlib.sha256(info['key'].encode()).hexdigest()[:32]
    if project['id'] != expected or project.get('part') != info['part']:
        raise ValueError('Project identity/part mismatch')
    return info


def plan():
    """Read-only preflight. Invalid manifests, duplicate IDs and occupied targets abort the whole plan."""
    platform = library.contained(library.LIBRARY_ROOT, 'bilibili')
    if platform.is_dir():
        for child in platform.iterdir():
            if layout.linked(child) or layout.linked(child / 'project.json'):
                raise ValueError('Linked project directory/manifest cannot be migrated')
            if child.is_dir():
                for episode in child.iterdir():
                    if layout.episode_directory(episode.name) and layout.linked(episode):
                        raise ValueError('Linked episode directory cannot be migrated')
    projects = [library.load(path) for path in library.manifests()]
    if len({p['id'] for p in projects}) != len(projects):
        raise ValueError('Duplicate project identities; migration refused')
    rows, targets = [], set()
    for project in projects:
        if project.get('platform') != 'bilibili':
            continue
        info = _identity(project)
        relative = project['directory'].relative_to(library.LIBRARY_ROOT)
        if len(relative.parts) == 3:
            if not layout.episode_directory(relative.name):
                raise ValueError('Unexpected nested episode directory')
            continue
        if len(relative.parts) == 2 and layout.single_episode(project, [p for p in projects if p.get('video_id') == info['video_id']]) and relative.name.endswith('__' + info['video_id']):
            continue
        if len(relative.parts) != 2:
            raise ValueError('Unexpected project directory')
        siblings = [p for p in projects if p.get('platform') == 'bilibili' and p.get('video_id') == info['video_id']]
        parent = layout.series_directory(info, project['title'], siblings)
        target = library.contained(parent, f"P{info['part']:03d}")
        key = str(target).casefold()
        if target.exists() or key in targets:
            raise FileExistsError(f'迁移目标已存在，未覆盖：{target}')
        # A pre-existing course folder must belong to this BV, not arbitrary user content.
        known_parent = any(p['directory'].parent == parent for p in siblings)
        if parent.exists() and any(parent.iterdir()) and not known_parent:
            raise FileExistsError(f'项目父目录包含未知内容：{parent}')
        targets.add(key)
        snapshot = inventory(project['directory'])
        # Registered resources must still match the authoritative manifest before moving.
        for key, item in project['resources'].items():
            physical = library.resource_path(project, key).relative_to(project['directory']).as_posix()
            actual = snapshot['files'].get(physical)
            if not actual or actual['size'] != item.get('size_bytes') or actual['sha256'] != item.get('sha256'):
                raise ValueError(f'项目资源完整性不符：{project["id"]} / {key}')
        rows.append({'project_id': project['id'], 'old': relative.as_posix(),
                     'new': target.relative_to(library.LIBRARY_ROOT).as_posix(),
                     'inventory': snapshot})
    return {'version': 1, 'id': uuid4().hex, 'root': str(library.LIBRARY_ROOT.resolve()),
            'created_at': datetime.now(timezone.utc).isoformat(), 'state': 'planned',
            'total_projects': len(projects), 'entries': rows}


def journal_path(identifier):
    if not re.fullmatch(r'[a-f0-9]{32}', identifier):
        raise ValueError('Invalid migration ID')
    return library.contained(library.LIBRARY_ROOT, f'.layout-migrations/{identifier}.json')


def read_journal(identifier):
    path = journal_path(identifier)
    if not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('Migration journal unavailable')
    return json.loads(path.read_text(encoding='utf-8'))


def _validate(plan):
    if (plan.get('version') != 1 or plan.get('root') != str(library.LIBRARY_ROOT.resolve())
            or not isinstance(plan.get('entries'), list)):
        raise ValueError('Migration plan does not belong to this library')
    journal_path(plan['id'])
    ids, sources, targets = set(), set(), set()
    for row in plan['entries']:
        old, new = layout.validate_move(row)
        if row['project_id'] in ids or str(old).casefold() in sources or str(new).casefold() in targets:
            raise ValueError('Duplicate migration entry')
        ids.add(row['project_id']); sources.add(str(old).casefold()); targets.add(str(new).casefold())
        if not isinstance(row.get('inventory', {}).get('files'), dict) or 'project.json' not in row['inventory']['files']:
            raise ValueError('Missing manifest inventory')


def _preflight(row):
    old, new = layout.validate_move(row)
    if old.exists() == new.exists():
        raise FileExistsError('Exactly one source/target must exist; no merge or overwrite is allowed')
    current = old if old.exists() else new
    project = library.load(current / 'project.json')
    info = _identity(project)
    if (project['id'] != row['project_id'] or new.name != f"P{info['part']:03d}"
            or not new.parent.name.endswith('__' + info['video_id'])):
        raise ValueError('Migration destination identity mismatch')
    if new.parent.exists() and any(new.parent.iterdir()):
        belongs = False
        for child in layout.directories(new.parent):
            manifest = child / 'project.json'
            if layout.episode_directory(child.name) and manifest.is_file():
                sibling = library.load(manifest)
                if sibling.get('platform') == 'bilibili' and sibling.get('video_id') == info['video_id']:
                    _identity(sibling)
                    belongs = True
        if not belongs:
            raise FileExistsError('Project parent contains unknown content; migration refused')
    if inventory(current) != row['inventory']:
        raise ValueError('Files changed since the plan; migration/rollback refused')
    return old, new


def _move(source, target):
    """Atomic no-clobber directory rename on Windows/Linux. Never fall back to copy/delete."""
    library.contained(library.LIBRARY_ROOT, target.relative_to(library.LIBRARY_ROOT))
    if target.exists():
        raise FileExistsError(str(target))
    if os.name == 'nt':
        os.rename(source, target)  # Windows refuses an existing destination, including empty directories.
    else:
        libc = ctypes.CDLL(None, use_errno=True)
        rename = getattr(libc, 'renameat2', None)
        if rename is None:
            raise OSError('Atomic no-overwrite directory move is unavailable on this system')
        if rename(-100, os.fsencode(source), -100, os.fsencode(target), 1) != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), str(target))


def _save(record):
    path = journal_path(record['id'])
    path.parent.mkdir(exist_ok=True)
    library.atomic_json(path, record)


def execute(proposal, *, undo=False, offline=False):
    """Caller MUST stop all writers. Journals allow retry after any interrupted directory rename."""
    if not offline:
        raise ValueError('请先停止本项目服务和所有写入，再显式指定离线迁移。')
    _validate(proposal)
    with library.file_lock(library.LIBRARY_ROOT / '.library.lock', timeout=3):
        path = journal_path(proposal['id'])
        record = read_journal(proposal['id']) if path.exists() else dict(proposal)
        if any(record.get(key) != proposal.get(key) for key in ('id', 'root', 'entries', 'version')):
            raise ValueError('Plan differs from durable migration journal')
        if undo and not path.exists():
            raise ValueError('No applied migration to undo')
        _validate(record)
        # Validate the entire batch before any mutation, including already moved entries on resume.
        pairs = [_preflight(row) for row in record['entries']]
        aliases = layout.read_aliases()
        for row in aliases['moves']:
            layout.validate_move(row)
        for row in record['entries']:
            alias = {key: row[key] for key in ('project_id', 'old', 'new')}
            if any(a['old'] == alias['old'] and a != alias for a in aliases['moves']):
                raise ValueError('Conflicting historical directory alias')
            if alias not in aliases['moves']:
                aliases['moves'].append(alias)
        record['state'] = 'undoing' if undo else 'applying'
        record['updated_at'] = datetime.now(timezone.utc).isoformat()
        _save(record)
        # Publish aliases before moves. They are inactive while the source exists, and survive a crash.
        library.atomic_json(library.contained(library.LIBRARY_ROOT, layout.ALIAS_FILE), aliases)
        try:
            for row, (old, new) in zip(record['entries'], pairs):
                source, target = (new, old) if undo else (old, new)
                if target.exists():
                    continue  # Verified by the whole-batch preflight: resumed/idempotent operation.
                # Close the preflight window; also validates all ancestors immediately before rename.
                _preflight(row)
                target.parent.mkdir(parents=True, exist_ok=True)
                _move(source, target)
                if inventory(target) != row['inventory']:
                    raise ValueError('Post-move integrity check failed; keep journal for recovery')
                record['last_verified'] = row['project_id']
                _save(record)
            library_index.invalidate(library.LIBRARY_ROOT)
            for row in record['entries']:
                expected = row['old'] if undo else row['new']
                if library.public(library.get(row['project_id']))['location'] != expected:
                    raise ValueError('Project index verification failed')
            record['state'] = 'undone' if undo else 'completed'
            _save(record)
        except BaseException:
            record['state'] = 'interrupted_undo' if undo else 'interrupted'
            _save(record)
            raise
        return record
