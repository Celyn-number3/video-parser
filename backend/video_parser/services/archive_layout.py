"""Named episode directories and explicit, resumable single-episode flattening.

No media is rewritten. Offline migrations pin every byte; naming transactions own
only directory names and carry all subsequently created learning files with them.
"""
import json
from pathlib import Path
import re
from uuid import uuid4

from video_parser.services import library, library_index, library_layout as layout, library_migration as base


def desired(project, siblings=(), title=None):
    current = project['directory']
    if project.get('platform') != 'bilibili':
        return current
    parts = current.relative_to(library.LIBRARY_ROOT).parts
    single = layout.single_episode(project, siblings)
    if len(parts) == 2:
        if single:
            return current
        raise ValueError('旧式平铺多集项目须先按旧目录迁移流程整理，未改动文件。')
    if len(parts) != 3 or not layout.episode_directory(current.name):
        raise ValueError('无法安全识别分集目录，未改动文件。')
    return current.parent if single else current.with_name(layout.episode_folder(project['part'], title or library.episode_title(project) or project.get('title') or '视频'))


def row_for(project, target):
    return {'project_id': project['id'], 'old': project['directory'].relative_to(library.LIBRARY_ROOT).as_posix(),
            'new': target.relative_to(library.LIBRARY_ROOT).as_posix()}


def check_identity(row, path):
    project = library.load(path / 'project.json')
    if project['id'] != row['project_id']:
        raise ValueError('目录项目身份不符，未覆盖文件。')
    base._identity(project)
    return project


def check_simple(row):
    old, new = layout.validate_move(row)
    if old.is_relative_to(new) or new.is_relative_to(old):
        raise ValueError('嵌套目录调整需要离线迁移。')
    if old.exists() == new.exists():
        raise FileExistsError('目录源与目标必须恰有一个存在，禁止合并或覆盖。')
    current = old if old.exists() else new
    project = check_identity(row, current)
    if old.parent != new.parent or any(not re.match(rf"^P{project['part']:03d}(?:-|$)", p.name) for p in (old, new)):
        raise ValueError('分集目录目标与项目身份不符。')
    return old, new


def publish_aliases(rows):
    aliases = layout.read_aliases()
    for row in rows:
        layout.validate_move(row)
        alias = {key: row[key] for key in ('project_id', 'old', 'new')}
        # Paths may be reused by a later undo/re-rename of the SAME stable project.
        if any(a['project_id'] != alias['project_id'] and
               {a['old'], a['new']} & {alias['old'], alias['new']} for a in aliases['moves']):
            raise ValueError('目录路径已经属于其他项目，禁止重定向。')
        if alias not in aliases['moves']:
            aliases['moves'].append(alias)
    library.atomic_json(library.contained(library.LIBRARY_ROOT, layout.ALIAS_FILE), aliases)


def rename_directories(rows, undo=False):
    if not rows:
        return
    pairs = [check_simple(row) for row in rows]
    publish_aliases(rows)
    for row, (old, new) in zip(rows, pairs):
        source, target = (new, old) if undo else (old, new)
        if not target.exists():
            check_simple(row)
            base._move(source, target)
            check_identity(row, target)
    library_index.invalidate(library.LIBRARY_ROOT)


def naming_moves(projects, rows):
    moves = []
    for row in rows:
        project = projects[row['project_id']]
        siblings = list(library._bilibili_projects(project.get('video_id')).values()) if project.get('platform') == 'bilibili' else []
        target = desired(project, siblings, (row['number'] + ' ' if row['number'] else '') + row['title'])
        if target == project['directory']:
            continue
        if project['directory'].is_relative_to(target):
            raise ValueError('单集旧目录尚未完成离线整理，请先完成目录迁移再重命名。')
        move = row_for(project, target)
        check_simple(move)
        if target.name.casefold() == project['directory'].name.casefold():
            raise ValueError('不执行仅大小写不同的目录改名。')
        # All resources and sidecars move together, not just the selected video/subtitle pair.
        for path in project['directory'].rglob('*'):
            library.contained(project['directory'], path.relative_to(project['directory']))
            if len(str(target / path.relative_to(project['directory'])).encode('utf-16-le')) // 2 > 240:
                raise ValueError('新目录完整路径过长，请缩短名称。')
        moves.append(move)
    return moves


def _children(snapshot):
    return {Path(name).parts[0] for name in [*snapshot['files'], *snapshot['directories']]}


def check_flat(row):
    """Validate a whole or partially flattened project without merging unknown content."""
    old, new = layout.validate_move(row)
    if old.parent != new:
        raise ValueError('只允许已确认单集目录上移一层。')
    children = _children(row['inventory'])
    if old.name in children:
        raise ValueError('内部目录与旧分集目录重名，迁移拒绝。')
    for directory, allowed in ((old, children), (new, children | {old.name})):
        if directory.exists() and ({p.name for p in directory.iterdir()} - allowed):
            raise FileExistsError('单集父目录含未知内容，禁止合并。')
    actual = {'files': {}, 'directories': []}
    placements = []
    for child in sorted(children):
        a, b = library.contained(old, child), library.contained(new, child)
        if a.exists() == b.exists():
            raise FileExistsError('单集源与目标内容冲突或缺失，禁止覆盖。')
        current = a if a.exists() else b
        if layout.linked(current):
            raise ValueError('链接内容禁止迁移。')
        placements.append((a, b))
        if current.is_dir():
            nested = base.inventory(current)
            actual['directories'].append(child)
            actual['directories'].extend(child + '/' + name for name in nested['directories'])
            actual['files'].update({child + '/' + name: value for name, value in nested['files'].items()})
        elif current.is_file():
            stat = current.stat(); digest = library.digest(current)
            after = current.stat()
            if (after.st_size, after.st_mtime_ns, after.st_ino) != (stat.st_size, stat.st_mtime_ns, stat.st_ino):
                raise ValueError('核对时内容发生变化。')
            actual['files'][child] = {'size': stat.st_size, 'sha256': digest}
        else:
            raise ValueError('非普通文件禁止迁移。')
    actual['directories'].sort()
    if actual != row['inventory']:
        raise ValueError('文件自预览后发生变化，迁移/回退拒绝。')
    project = check_identity(row, old if (old / 'project.json').exists() else new)
    if not layout.single_episode(project):
        raise ValueError('不是解析确认的单集，不能取消分集层。')
    return placements


def check(row):
    old, new = layout.validate_move(row)
    if old.parent == new:
        return check_flat(row)
    old, new = check_simple(row)
    if base.inventory(old if old.exists() else new) != row['inventory']:
        raise ValueError('内容自预览后变化，迁移/回退拒绝。')
    return [(old, new)]


def plan():
    platform = library.contained(library.LIBRARY_ROOT, 'bilibili')
    if platform.is_dir():
        for folder in platform.iterdir():
            if layout.linked(folder) or layout.linked(folder / 'project.json'):
                raise ValueError('链接目录不能迁移。')
            if folder.is_dir():
                for child in folder.iterdir():
                    if layout.episode_directory(child.name) and layout.linked(child):
                        raise ValueError('链接分集目录不能迁移。')
    paths = library.manifests()
    projects = [library.load(path) for path in paths]
    if len({p['id'] for p in projects}) != len(projects):
        raise ValueError('项目身份重复，迁移拒绝。')
    entries, targets = [], set()
    for project in projects:
        if project.get('platform') != 'bilibili':
            continue
        siblings = [p for p in projects if p.get('video_id') == project.get('video_id') and p.get('platform') == 'bilibili']
        target = desired(project, siblings)
        if target == project['directory']:
            continue
        key = str(target).casefold()
        if key in targets:
            raise FileExistsError('迁移目标重复。')
        targets.add(key)
        row = row_for(project, target)
        row['inventory'] = base.inventory(project['directory'])
        for resource, item in project['resources'].items():
            relative = library.resource_path(project, resource).relative_to(project['directory']).as_posix()
            actual = row['inventory']['files'].get(relative)
            if not actual or actual['sha256'] != item.get('sha256') or actual['size'] != item.get('size_bytes'):
                raise ValueError('归档资源完整性不符，迁移拒绝。')
        for name in row['inventory']['files']:
            if len(str(target / name).encode('utf-16-le')) // 2 > 240:
                raise ValueError('迁移目标路径过长。')
        check(row)
        entries.append(row)
    return {'version': 2, 'id': uuid4().hex, 'root': str(library.LIBRARY_ROOT.resolve()),
            'state': 'planned', 'total_projects': len(projects), 'entries': entries}


def journal_path(identifier):
    if not re.fullmatch('[a-f0-9]{32}', identifier):
        raise ValueError('无效迁移编号。')
    return library.contained(library.LIBRARY_ROOT, '.archive-layout-migrations/' + identifier + '.json')


def execute(proposal, *, offline=False, undo=False):
    if not offline:
        raise ValueError('必须停止服务与所有写入，再明确执行离线迁移。')
    if proposal.get('version') != 2 or proposal.get('root') != str(library.LIBRARY_ROOT.resolve()):
        raise ValueError('迁移计划不属于本库。')
    path = journal_path(proposal['id'])
    with library.file_lock(library.LIBRARY_ROOT / '.library.lock', timeout=3):
        record = json.loads(path.read_text(encoding='utf-8')) if path.exists() else dict(proposal)
        if any(record.get(key) != proposal.get(key) for key in ('version', 'id', 'root', 'entries')):
            raise ValueError('迁移记录与预览不一致。')
        if undo and not path.exists():
            raise ValueError('没有已执行记录可回退。')
        rows = record['entries']
        if len({r['project_id'] for r in rows}) != len(rows):
            raise ValueError('重复项目迁移。')
        for row in rows:
            check(row)
        path.parent.mkdir(exist_ok=True)
        record['state'] = 'undoing' if undo else 'applying'
        library.atomic_json(path, record)
        publish_aliases(rows)
        try:
            for row in rows:
                pairs = check(row)
                # Publish the manifest last so intermediate layouts never have duplicate identities.
                pairs.sort(key=lambda pair: pair[0].name == 'project.json')
                old, new = layout.validate_move(row)
                for a, b in pairs:
                    source, target = (b, a) if undo else (a, b)
                    if target.exists():
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    base._move(source, target)
                if old.parent == new and not undo and old.exists():
                    old.rmdir()  # Only an empty shell; never recursively delete.
                check(row)
                record['last_verified'] = row['project_id']
                library.atomic_json(path, record)
            library_index.invalidate(library.LIBRARY_ROOT)
            for row in rows:
                expected = row['old'] if undo else row['new']
                if library.public(library.get(row['project_id']))['location'] != expected:
                    raise ValueError('索引位置核对失败。')
            record['state'] = 'undone' if undo else 'completed'
            library.atomic_json(path, record)
        except BaseException:
            record['state'] = 'interrupted_undo' if undo else 'interrupted'
            library.atomic_json(path, record)
            raise
        return record
