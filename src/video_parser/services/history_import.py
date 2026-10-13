"""Preview and copy old media into video projects. No network, deletes, moves or cookie reads."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re

from PIL import Image
from video_parser.services import videos
from video_parser.services import library as library
from video_parser.services import subtitles
MEDIA = {'.mp4', '.mkv', '.webm', '.mov', '.avi', '.m4v'}


def confirmed(path):
    # Only filename IDs are evidence; a course title alone is never an identity.
    match = re.search(r'(BV[A-Za-z0-9]{10})(?:[^A-Za-z0-9]|$)', path.name)
    if not match: return None
    part = re.search(r'(?:_p|__P)(\d+)', path.stem)
    number = int(part[1]) if part else 1
    return {'platform': '哔哩哔哩', 'video_id': match[1], 'title': path.stem,
            'source_url': f'https://www.bilibili.com/video/{match[1]}?p={number}'}


def pending(path, hashed, title=None, source_identity=False):
    identifier = hashlib.sha256(str(path.absolute()).encode()).hexdigest() if source_identity else hashed
    return {'platform': 'unknown', 'video_id': identifier, 'title': title or path.stem, 'source_url': ''}


def collect(roots):
    files = []
    for root in roots:
        root = Path(root).absolute()
        if not root.exists(): continue
        # Only caller-specified resource directories; never follow links or collect credential files.
        if root.is_symlink() or (hasattr(root, 'is_junction') and root.is_junction()): continue
        for path in root.rglob('*'):
            if not path.is_file() or path.is_symlink(): continue
            if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()) for p in path.parents if p.is_relative_to(root)): continue
            if not path.resolve().is_relative_to(root.resolve()): continue
            if path.name in {'b站_cookies.json', 'bilibili-cookies.json', '.env'} or path.suffix in {'.log', '.lock'}: continue
            files.append(path)
    return sorted(set(files))


def run(roots, apply=False):
    files = collect(roots)
    before = {str(path): {'sha256': library.digest(path), 'size_bytes': path.stat().st_size} for path in files}
    mappings, directory_media = {}, {}
    for path in files:
        if path.suffix.lower() in MEDIA:
            info = confirmed(path)
            if info:
                mappings.setdefault(before[str(path)]['sha256'], []).append(info)
    assignments = {}
    for path in files:
        if path.suffix.lower() in MEDIA:
            hashed = before[str(path)]['sha256']
            candidates = mappings.get(hashed, [])
            keys = {library.identity(item)['key'] for item in candidates}
            # Identical known bytes spanning more than one video is ambiguous: do not guess.
            info = confirmed(path) or (candidates[0] if len(keys) == 1 else pending(path, hashed))
            assignments[path] = info
            directory_media.setdefault(path.parent, []).append(info)
    spec = importlib.util.spec_from_file_location('history_subtitle_checker', subtitles.CHECKER_PATH)
    checker = importlib.util.module_from_spec(spec);spec.loader.exec_module(checker)
    rows, consumed = [], set()
    new_resources = 0
    for path in files:
        if path in consumed: continue
        hashed = before[str(path)]['sha256']
        group = [path]
        info, kind, relative, details = None, None, None, {}
        error = None
        try:
            if path.parent.name == '_json' and path.suffix == '.json':
                group = [path, path.parent.parent / '_srt' / (path.stem + '.srt'), path.parent.parent / '_md' / (path.stem + '.md')]
                consumed.update(group)
                if not checker.check(path)['ok']: raise ValueError('字幕三份文件不完整或字幕JSON无效，保留原件待修复。')
                info = confirmed(path) or pending(path, hashed, path.parent.parent.name + '__' + path.stem, source_identity=True)
                kind, relative = 'subtitle', 'subtitles/subtitle.json'
            elif path.suffix.lower() in MEDIA:
                info = assignments[path]
                media = videos.probe(path)
                videos.check_video(media, require_audio=info['platform'] == '哔哩哔哩')
                kind, relative, details = 'video', 'video' + path.suffix.lower(), {'media': media}
            else:
                try:
                    with Image.open(path) as image:
                        image.verify()
                        extension = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp', 'AVIF': '.avif'}[image.format]
                    known = directory_media.get(path.parent, [])
                    info = confirmed(path) or (known[0] if len(known) == 1 else pending(path, hashed))
                    kind, relative = 'cover', 'cover' + extension
                except (OSError, ValueError, KeyError):
                    if path.suffix.lower() in {'.md', '.srt', '.json'} and path.parent.name in {'_json', '_srt', '_md'} and not (path.suffix == '.md' and path.stem.startswith('合集_')):
                        counterpart = path.parent.parent / '_json' / (path.stem + '.json')
                        if counterpart in files: continue
                        raise ValueError('缺少字幕JSON对应文件，保留原件待确认。')
                    if not path.stat().st_size: raise ValueError('空文件，保留原件待确认。')
                    # Containers and standalone notes remain isolated pending artifacts, not invented video IDs.
                    info = pending(path, hashed)
                    kind, relative = 'legacy', 'legacy/' + library.safe_name(path.name)
            for source in group:
                if source not in files: raise ValueError('伴随文件不在允许扫描范围内。')
                if source.is_symlink() or not source.resolve().is_relative_to(source.parent.parent.resolve()):
                    raise ValueError('不允许链接资源。')
            identity = library.identity(info)
            project_id = hashlib.sha256(identity['key'].encode()).hexdigest()[:32]
            for source in group:
                name = ('subtitles/subtitle' + source.suffix) if kind == 'subtitle' else relative
                row = {'source': str(source), **before[str(source)], 'project_id': project_id,
                       'identity_status': 'pending' if info['platform'] == 'unknown' else 'confirmed',
                       'status': 'planned', 'destination_relative': name, 'kind': kind}
                if apply:
                    project = library.ensure(info)
                    old = set(project['resources'])
                    saved = library.import_file(project_id, source, name, kind, {**details, **({'download_name': source.name} if kind == 'subtitle' else {})})
                    published = library.resource(project_id, saved)
                    if library.digest(published) != before[str(source)]['sha256']: raise ValueError('复制摘要不一致。')
                    row.update(status='copied' if saved not in old else 'reused', destination=str(published))
                    new_resources += saved not in old
                rows.append(row)
        except Exception as exc:
            error = str(exc) or type(exc).__name__
        if error:
            for source in group:
                if source in files and not any(row['source'] == str(source) for row in rows):
                    rows.append({'source': str(source), **before[str(source)], 'status': 'failed', 'reason': error})
    after = {str(path): library.digest(path) for path in files}
    unchanged = all(before[path]['sha256'] == value for path, value in after.items())
    report = {'schema_version': 1, 'created_at': datetime.now(timezone.utc).isoformat(), 'mode': 'copy' if apply else 'preview',
              'roots': [str(Path(root).absolute()) for root in roots], 'sources_unchanged': unchanged,
              'source_count': len(files), 'processed_count': len(rows), 'new_resources': new_resources,
              'failed': sum(row['status'] == 'failed' for row in rows),
              'pending_identity_files': sum(row.get('identity_status') == 'pending' for row in rows), 'items': rows}
    if len(rows) != len(files): raise RuntimeError('迁移清单未覆盖全部资源，停止。')
    if not unchanged: raise RuntimeError('源文件发生变化，请检查迁移清单。')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='默认只预览；指定后复制且不删除原件')
    parser.add_argument('--roots', nargs='+', type=Path, help='只扫描指定资源目录')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    roots = args.roots or [videos.ROOT / 'downloads', videos.ROOT / 'cache', videos.ROOT / 'static/videos', subtitles.TOOL_ROOT / 'subtitle_download']
    report = run(roots, args.apply)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'items'}, ensure_ascii=False, indent=2))
    return 0 if report['sources_unchanged'] and not report['failed'] else 1


if __name__ == '__main__': raise SystemExit(main())
