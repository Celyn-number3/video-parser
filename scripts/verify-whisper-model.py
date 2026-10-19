"""Verify the fixed model manifest; download missing files only with --download."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from video_parser.core.paths import CACHE_DIR, LOG_DIR
MANIFEST = ROOT / 'backend/video_parser/integrations/whisper/model-manifest.json'
TARGET = ROOT / 'runtimes/models/whisper/large-v3-turbo'


def verify(path, item):
    if path.is_symlink() or path.stat().st_size != item['size']:
        raise RuntimeError('Existing model file differs; refusing overwrite: ' + path.name)
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != item['sha256']:
        raise RuntimeError('Existing model file hash differs; refusing overwrite: ' + path.name)
    return {'path': path.name, 'size': path.stat().st_size, 'sha256': digest, 'ok': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download', action='store_true')
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    assert manifest['repo_id'] == 'dropbox-dash/faster-whisper-large-v3-turbo'
    assert manifest['revision'] == '0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf'
    assert {f['path'] for f in manifest['files']} == {'config.json','model.bin','preprocessor_config.json','tokenizer.json','vocabulary.json'}
    missing = []
    for item in manifest['files']:
        path = TARGET / item['path']
        if path.exists(): verify(path, item)
        else: missing.append(item['path'])
    if missing:
        if not args.download:
            raise RuntimeError('Model files missing; rerun setup-local-tools.ps1 -DownloadModel')
        os.environ.setdefault('HF_HOME', str(CACHE_DIR / 'huggingface'))
        os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
        from huggingface_hub import snapshot_download
        snapshot_download(repo_id=manifest['repo_id'], revision=manifest['revision'], local_dir=TARGET, allow_patterns=missing)
    rows = [verify(TARGET / item['path'], item) for item in manifest['files']]
    output = ROOT / '.local/work/artifacts/tool-setup/model-verification.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({'revision':manifest['revision'],'files':rows},indent=2),encoding='utf-8')
    print('Verified all five fixed model files (size + SHA-256).')


if __name__ == '__main__': main()
