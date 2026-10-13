"""Stable repository paths for the supported editable, local-workspace installation."""
from pathlib import Path


def project_root(anchor: Path | None = None) -> Path:
    """Locate the repository by markers, never by the process working directory."""
    source = (anchor or Path(__file__)).resolve()
    for candidate in (source, *source.parents):
        if ((candidate / 'pyproject.toml').is_file()
                and (candidate / 'configs' / 'business_config.json').is_file()
                and (candidate / 'src' / 'video_parser').is_dir()):
            return candidate
    raise RuntimeError('Project workspace not found. Use an editable installation of video-parser.')


ROOT = project_root()
FRONTEND_DIR = ROOT / 'frontend' / 'dist'
