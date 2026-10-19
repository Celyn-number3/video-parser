"""Central repository, runtime and historical-task paths for the local workspace."""
import os
from pathlib import Path


def project_root(anchor: Path | None = None) -> Path:
    source = (anchor or Path(__file__)).resolve()
    for candidate in (source, *source.parents):
        if ((candidate / 'pyproject.toml').is_file()
                and (candidate / 'configs' / 'business_config.json').is_file()
                and (candidate / 'backend' / 'video_parser').is_dir()):
            return candidate
    raise RuntimeError('Project workspace not found. Use an editable installation of video-parser.')


ROOT = project_root()


def instance_id(root: Path | None = None) -> str:
    """Short stable id of an install folder; the desktop launcher only reuses a running server from the same install."""
    import hashlib
    folder = os.path.normcase(str(Path(root or ROOT).resolve()))
    return hashlib.sha256(folder.encode('utf-8')).hexdigest()[:12]
FRONTEND_DIR = ROOT / 'frontend' / 'dist'
# Portable builds ship ffmpeg/ffprobe here; developer setups keep using the copy on PATH.
BUNDLED_TOOLS_DIR = ROOT / 'runtimes' / 'ffmpeg' / 'bin'


def use_bundled_tools(environ=os.environ, folder: Path = BUNDLED_TOOLS_DIR) -> None:
    """Put bundled media tools ahead of PATH so subprocess, shutil.which and yt-dlp all find them."""
    entries = environ.get('PATH', '').split(os.pathsep)
    if folder.is_dir() and str(folder) not in entries:
        environ['PATH'] = os.pathsep.join([str(folder), *filter(None, entries)])


use_bundled_tools()


def runtime_directory(name: str, root: Path = ROOT) -> Path:
    """New work lives in .local/work; an unmigrated legacy root remains singular."""
    if name not in ('cache', 'logs'):
        raise ValueError('Unknown runtime directory')
    candidates = (root / name, root / 'var' / name, root / '.local' / 'work' / name)
    for path in candidates:
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            raise RuntimeError('Linked runtime directories are not supported')
    existing = [path for path in candidates if path.exists()]
    if len(existing) > 1:
        raise RuntimeError('Multiple runtime directories exist; resolve the migration before starting.')
    return existing[0] if existing else candidates[-1]


def restore_runtime_paths(value, root: Path = ROOT, _field=None):
    """Rebase internal task paths in memory; never edit journals or user prose.

    Only absent old roots with present new roots qualify. Relative/external paths,
    traversal, titles, prompts, messages and transcript text remain unchanged.
    """
    if isinstance(value, dict):
        return {key: restore_runtime_paths(item, root, 'files' if _field == 'files' else key)
                for key, item in value.items()}
    if isinstance(value, list):
        return [restore_runtime_paths(item, root, _field) for item in value]
    if not isinstance(value, str) or _field not in {
        'directory', 'source', 'path', 'file', 'files', 'paths', 'input_path',
        'source_path', 'output_path', 'output_dir', 'model_path', 'vision_path',
        'audio_path', 'video_path', 'subtitle_path', 'cache_dir',
    }:
        return value
    source = Path(value)
    if not source.is_absolute() or '..' in source.parts:
        return value
    for old, new in (
        (root / 'cache', root / '.local/work/cache'),
        (root / 'var/cache', root / '.local/work/cache'),
        (root / 'logs', root / '.local/work/logs'),
        (root / 'var/logs', root / '.local/work/logs'),
        (root / 'library', root / 'outputs'),
        (root / 'models', root / 'runtimes/models'),
    ):
        if old.exists() or not new.is_dir():
            continue
        try:
            return str(new / source.relative_to(old))
        except ValueError:
            continue
    return value


CACHE_DIR = runtime_directory('cache')
LOG_DIR = runtime_directory('logs')
