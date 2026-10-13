"""One persistent directory per video. Standard library only; no credentials or signed URLs."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
from urllib.parse import parse_qs, urlsplit, urlunsplit
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from video_parser.core.paths import ROOT

LIBRARY_ROOT = Path(os.getenv('VIDEO_LIBRARY_ROOT', ROOT / 'library'))
PLATFORMS = {'哔哩哔哩': 'bilibili', '抖音': 'douyin', '小红书': 'xiaohongshu', '快手': 'kuaishou',
             '好看视频': 'haokan', '梨视频': 'pearvideo', '微视': 'weishi', '皮皮搞笑': 'pipigaoxiao'}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def safe_name(text):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(text)).strip(' .')[:65].rstrip(' .') or 'video'
    if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', name, re.I): name = '_' + name
    return name


@contextmanager
def file_lock(path, timeout=60):
    """OS releases this lock on process exit, including interrupted CLI runs."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink(): raise ValueError('Unsafe lock path')
    with path.open('a+b') as stream:
        stream.seek(0, 2)
        if not stream.tell(): stream.write(b'0'); stream.flush()
        deadline = time.monotonic() + timeout
        while True:
            from video_parser.services import task_runtime
            task_runtime.checkpoint()
            try:
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline: raise TimeoutError('视频项目正在处理中，请稍后重试。')
                time.sleep(.03)
        try: yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_UN)


def contained(directory, relative):
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts or not relative.parts:
        raise ValueError('Unsafe relative path')
    target = directory / relative
    resolved = target.resolve()
    if not resolved.is_relative_to(directory.resolve()) or not resolved.is_relative_to(LIBRARY_ROOT.resolve()):
        raise ValueError('File outside project')
    # Junctions and symlinks must never redirect a resource within or outside the project.
    for parent in [target, *target.parents]:
        if parent == LIBRARY_ROOT.parent: break
        if parent.is_symlink() or (hasattr(parent, 'is_junction') and parent.is_junction()):
            raise ValueError('Linked project paths are not allowed')
    return target


def atomic_json(path, data):
    temporary = path.with_name('.manifest-' + uuid4().hex)
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally: temporary.unlink(missing_ok=True)


def identity(metadata):
    platform = PLATFORMS.get(metadata.get('platform'), metadata.get('platform', 'unknown'))
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,25}', platform): raise ValueError('Unknown platform identity')
    source = urlsplit(metadata.get('source_url', ''))
    identifier = str(metadata.get('video_id') or '')
    if platform == 'bilibili':
        match = re.search(r'/video/(BV[A-Za-z0-9]{10})(?:/|$)', source.path)
        identifier = match[1] if match else identifier
        if not re.fullmatch(r'BV[A-Za-z0-9]{10}', identifier): raise ValueError('Missing Bilibili BV identity')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', identifier): raise ValueError('Missing stable video ID')
    part = int(parse_qs(source.query).get('p', ['1'])[0]) if platform == 'bilibili' else None
    if part is not None and not 1 <= part <= 100000: raise ValueError('Invalid episode')
    key = f'{platform}:{identifier}' + (f':p{part}' if part else '')
    if platform == 'bilibili':
        canonical = f'https://www.bilibili.com/video/{identifier}?p={part}'
    elif source.scheme in ('https', 'http') and source.hostname:
        canonical = urlunsplit(('https', source.hostname, source.path, '', ''))
    else: canonical = ''
    return {'key': key, 'platform': platform, 'video_id': identifier, 'part': part, 'source_url': canonical}


def manifests():
    if not LIBRARY_ROOT.exists(): return []
    return sorted(LIBRARY_ROOT.glob('*/*/project.json'))


def load(path):
    contained(path.parent, 'project.json')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema_version') != 1 or not re.fullmatch(r'[0-9a-f]{32}', data.get('id', '')):
        raise ValueError('Invalid project manifest')
    return {**data, 'directory': path.parent}


def get(identifier):
    from video_parser.services import library_index
    return library_index.lookup(LIBRARY_ROOT, identifier, load, atomic_json)


def ensure(metadata):
    info = identity(metadata)
    identifier = hashlib.sha256(info['key'].encode()).hexdigest()[:32]
    with file_lock(LIBRARY_ROOT / '.library.lock'):
        try: return get(identifier)
        except KeyError: pass
        suffix = info['video_id'] + (f"__P{info['part']:03d}" if info['part'] else '')
        directory = LIBRARY_ROOT / info['platform'] / (safe_name(metadata.get('title') or 'video') + '__' + suffix)
        if directory.exists():
            directory = directory.with_name(directory.name + '__' + identifier[:8])
        contained(directory, 'project.json')
        directory.mkdir(parents=True, exist_ok=False)
        data = {'schema_version': 1, 'id': identifier, **info, 'title': str(metadata.get('title') or 'video'),
                'created_at': datetime.now(timezone.utc).isoformat(), 'resources': {},
                'identity_status': 'pending' if info['platform'] in ('unknown', 'local') else 'confirmed'}
        atomic_json(directory / 'project.json', data)
        return {**data, 'directory': directory}


@contextmanager
def operation(identifier):
    project = get(identifier)
    with file_lock(contained(project['directory'], '.operation.lock'), timeout=1800): yield get(identifier)


def import_file(identifier, source, relative, kind, details=None):
    source = Path(source)
    if not source.is_file() or not source.stat().st_size: raise ValueError('Missing or empty resource')
    project = get(identifier)
    with file_lock(contained(project['directory'], '.manifest.lock')):
        project = get(identifier)
        directory = project['directory']
        target = contained(directory, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.publish-', dir=directory) as temporary:
            staged = Path(temporary) / 'resource'
            shutil.copyfile(source, staged)
            hashed = digest(staged)
            if target.exists() and digest(target) != hashed:
                target = contained(directory, str(Path(relative).with_name(Path(relative).stem + '__' + hashed[:12] + Path(relative).suffix)))
            if not target.exists(): os.link(staged, target)
            if digest(target) != hashed: raise ValueError('Published resource mismatch')
            key = target.relative_to(directory).as_posix()
            project['resources'][key] = {'kind': kind, 'size_bytes': target.stat().st_size, 'sha256': hashed,
                                         'validated': True, **(details or {})}
            atomic_json(directory / 'project.json', {k: v for k, v in project.items() if k != 'directory'})
        return key


def resource(identifier, relative):
    return resource_from_project(get(identifier), relative)


def resource_from_project(project, relative):
    info = project['resources'].get(relative)
    if not info: raise KeyError('Unregistered resource')
    path = contained(project['directory'], relative)
    if not path.is_file() or path.stat().st_size != info['size_bytes'] or digest(path) != info['sha256']:
        raise ValueError('项目资源缺失或已变化，请重新校验或获取。')
    return path


def find(identifier, kind):
    project = get(identifier)
    for name, info in project['resources'].items():
        if info['kind'] == kind:
            try: return name, resource_from_project(project, name)
            except (ValueError, OSError): continue
    return None


def save_text(identifier, kind, text, details=None):
    if not text.strip(): raise ValueError('Empty report')
    project = get(identifier)
    with tempfile.TemporaryDirectory(prefix='.report-', dir=project['directory']) as directory:
        source = Path(directory) / 'report.md'
        source.write_text(text, encoding='utf-8')
        batch = datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:8]
        return import_file(identifier, source, f'{kind}/{batch}.md', kind, details)


def local_project(path):
    owner_project = owner(path)
    if owner_project: return owner_project
    return ensure({'platform': 'local', 'video_id': digest(path), 'title': Path(path).stem})


def owner(path):
    path = Path(path).resolve()
    if not path.is_relative_to(LIBRARY_ROOT.resolve()): return None
    for parent in path.parents:
        if parent == LIBRARY_ROOT.resolve(): break
        manifest = parent / 'project.json'
        if manifest.is_file(): return load(manifest)
    return None


def public(project):
    return {'id': project['id'], 'title': project['title'], 'platform': project['platform'],
            'part': project['part'], 'location': project['directory'].relative_to(LIBRARY_ROOT).as_posix(),
            'identity_status': project['identity_status'],
            'resources': [{'path': name, 'kind': item['kind'], 'size_bytes': item['size_bytes'],
                           'url': f"/api/workspace/projects/{project['id']}/files/{name}"}
                          for name, item in project['resources'].items()],
            'archive_url': f"/api/workspace/projects/{project['id']}/archive"}


def archive(identifier):
    project = get(identifier)
    with file_lock(contained(project['directory'], '.manifest.lock')):
        project = get(identifier)
        export = LIBRARY_ROOT / '.exports'
        export.mkdir(exist_ok=True)
        target = export / (identifier + '-' + uuid4().hex + '.zip')
        try:
            with ZipFile(target, 'x', compression=ZIP_DEFLATED) as zipped:
                for name in project['resources']:
                    zipped.write(resource(identifier, name), name)
                zipped.write(project['directory'] / 'project.json', 'project.json')
        except Exception:
            target.unlink(missing_ok=True); raise
        return target


def import_frames(identifier, directory):
    files = sorted(Path(directory).glob('*.jpg'))
    if not files: return []
    batch = datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:8]
    return [import_file(identifier, path, f'frames/{batch}/{path.name}', 'frame') for path in files]
