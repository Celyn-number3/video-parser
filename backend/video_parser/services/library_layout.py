"""Bounded old/new project discovery and read-only compatibility for directory moves."""
import json
from pathlib import Path
import re

from video_parser.core.paths import canonical

ALIAS_FILE = '.directory-aliases.json'
PATH_FIELDS = {'directory', 'source', 'path', 'file', 'files', 'paths', 'input_path',
               'source_path', 'output_path', 'output_dir', 'audio_path', 'video_path',
               'subtitle_path', 'cache_dir', 'location'}


def linked(path):
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def directories(path):
    if not path.is_dir() or linked(path):
        return []
    return sorted(p for p in path.iterdir() if not p.name.startswith('.') and p.is_dir() and not linked(p))


def manifest_paths(root):
    """Do not recursively walk videos, personal data, links, or arbitrary directory depths."""
    result = []
    for platform in directories(Path(root)):
        for project in directories(platform):
            manifest = project / 'project.json'
            if manifest.is_file() and not linked(manifest):
                result.append(manifest)
            if platform.name == 'bilibili':
                for episode in directories(project):
                    if episode_directory(episode.name):
                        manifest = episode / 'project.json'
                        if manifest.is_file() and not linked(manifest):
                            result.append(manifest)
    return sorted(result)


def episode_directory(name):
    return bool(re.fullmatch(r'P\d{3,6}(?:-[^<>:"/\\|?*\x00-\x1f]+)?', name)) and not name.endswith((' ', '.'))


def single_episode(project, siblings=()):
    """Use parsed catalog, never the number of downloaded resources. Unknown stays numbered."""
    from video_parser.services import library
    if project.get('platform') != 'bilibili':
        return True
    catalogs = [library.normalize_episodes(item.get('episodes')) for item in (project, *siblings)]
    parts = {entry['part'] for catalog in catalogs for entry in catalog}
    parts.update(item.get('part') for item in (project, *siblings) if item.get('part'))
    return bool(any(catalogs)) and parts == {1}


def episode_folder(part, title):
    from video_parser.services import library
    # Keep stable P identity as well as the current confirmed/display filename stem.
    return f'P{part:03d}-' + library.safe_name(title)


def series_directory(info, title, siblings):
    from video_parser.services import library
    nested = {p['directory'].parent for p in siblings
              if len(p['directory'].relative_to(library.LIBRARY_ROOT).parts) == 3}
    if len(nested) > 1:
        raise ValueError('同一 BV 的分集分散在多个项目目录，请先检查目录。')
    if nested:
        return next(iter(nested))
    # Old parts may have a user-confirmed course title. A new parsed title must not split the course.
    first = min(siblings, key=lambda p: p['part']) if siblings else None
    title = first['title'] if first else title
    return library.LIBRARY_ROOT / 'bilibili' / (library.safe_name(title or 'video') + '__' + info['video_id'])


def read_aliases():
    from video_parser.services import library
    path = library.contained(library.LIBRARY_ROOT, ALIAS_FILE)
    if not path.exists():
        return {'version': 1, 'moves': []}
    if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('Invalid project directory aliases')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('version') != 1 or not isinstance(data.get('moves'), list):
        raise ValueError('Invalid project directory aliases')
    return data


def validate_move(row):
    from video_parser.services import library
    if not re.fullmatch(r'[a-f0-9]{32}', row.get('project_id', '')):
        raise ValueError('Invalid project identity')
    old, new = Path(row['old']), Path(row['new'])
    for path in (old, new):
        if (path.is_absolute() or '..' in path.parts or len(path.parts) not in (2, 3)
                or path.parts[0] not in library.PLATFORMS.values() or any(part.startswith('.') for part in path.parts)
                or (len(path.parts) == 3 and (path.parts[0] != 'bilibili' or not episode_directory(path.name)))):
            raise ValueError('Invalid project directory move')
    if old.parts[0] != new.parts[0]:
        raise ValueError('Cross-platform directory move forbidden')
    if old == new:
        raise ValueError('Identical directory move')
    return library.contained(library.LIBRARY_ROOT, old), library.contained(library.LIBRARY_ROOT, new)


def restore_task_paths(value):
    """Resolve only known path fields in memory. Journals and user prose are never rewritten.

    Both directions are supported: a verified rollback keeps tasks created after migration usable.
    Existing old directories take precedence; links, escapes and wrong project identities cannot redirect.
    """
    from video_parser.services import library
    aliases = read_aliases()
    groups = {}
    for row in aliases['moves']:
        old, new = validate_move(row)
        groups.setdefault(row['project_id'], set()).update((old, new))
    active = []
    for identifier, locations in groups.items():
        present = []
        for path in locations:
            manifest = path / 'project.json'
            if manifest.exists():
                project = library.load(manifest)
                if project['id'] != identifier:
                    raise ValueError('Project directory alias identity mismatch')
                present.append(path)
        if len(present) > 1:
            raise ValueError('Multiple directory alias identities exist')
        if present:
            active.extend((path, present[0]) for path in locations if path != present[0])
    # Resolve the most specific old path first (flattening leaves its parent alive).
    active.sort(key=lambda pair: len(pair[0].parts), reverse=True)
    if not active:
        return value
    root = library.LIBRARY_ROOT

    def convert(text, field):
        if not isinstance(text, str) or field not in PATH_FIELDS:
            return text
        path = Path(text)
        if '..' in path.parts or (path.is_absolute() and path.exists()):
            return text
        for source, target in active:
            # Absolute persisted filesystem paths.
            if path.is_absolute():
                try:
                    suffix = canonical(path).relative_to(canonical(source))
                except ValueError:
                    continue
                candidate = library.contained(target, suffix) if suffix.parts else target
                return str(candidate)
            # Public project locations are library-relative, or displayed with an outputs/ prefix.
            if field == 'location':
                for prefix in ('', 'outputs/'):
                    old = prefix + source.relative_to(root).as_posix()
                    if text == old or text.startswith(old + '/'):
                        suffix = text[len(old):]
                        if suffix:
                            library.contained(target, suffix.lstrip('/'))
                        return prefix + target.relative_to(root).as_posix() + suffix
        return text

    def visit(item, field=None):
        if isinstance(item, dict):
            return {key: visit(child, 'files' if field == 'files' and isinstance(child, str) else key)
                    for key, child in item.items()}
        if isinstance(item, list):
            return [visit(child, field) for child in item]
        return convert(item, field)
    return visit(value)
