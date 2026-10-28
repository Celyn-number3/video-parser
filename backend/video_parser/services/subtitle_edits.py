"""Human proofreading of an archived subtitle; every save publishes a new file.

Whisper and platform captions get proper nouns and symbols wrong. Re-transcribing
is expensive, so a proofread copy is published next to the original: only the cues
the user actually edited change, timings and untouched text stay byte-identical,
and the source file is never rewritten.
"""
import math
from pathlib import Path
import re
import tempfile

from video_parser.services import library, subtitle_names, translations

# Translations are editable too: a mistranslated term is fixed the same way.
EDITABLE_KINDS = ('subtitle', 'transcription', 'translation', 'correction')
MAX_BYTES = 2 * 1024 * 1024
MAX_CUE_CHARS = 1000
MAX_CUE_LINES = 4
START = re.compile(r'^(?:(\d+):)?(\d{2}):(\d{2})[,.](\d{3})')


def seconds(line):
    """Start time exactly as the reader computes it, so a cue can be located by its timestamp."""
    match = START.match(line.strip())
    if not match: return None
    hours, minutes, value, millis = match.groups()
    return round(int(hours or 0) * 3600 + int(minutes) * 60 + int(value) + int(millis) / 1000, 3)


def cues(text, suffix):
    """Cue list with the original body kept verbatim; a malformed block is reported, never dropped."""
    items = []
    for index, block in enumerate(re.split(r'\n[ \t]*\n', str(text).replace('\r\n', '\n').lstrip('\ufeff').strip())):
        lines = block.splitlines()
        first = lines[0].strip() if lines else ''
        # WebVTT metadata is not a cue; an SRT block always carries its own time line.
        if suffix.lower() == '.vtt' and (
                index == 0 and re.fullmatch(r'WEBVTT(?:[ \t].*)?', first) or
                re.fullmatch(r'NOTE(?:[ \t].*)?', first) or first in ('STYLE', 'REGION')):
            continue
        found = next((position for position, line in enumerate(lines) if translations.TIME.fullmatch(line.strip())), None)
        if found is None: raise ValueError('字幕格式无法完整解析，未发布校对版本。')
        body = '\n'.join(line for line in lines[found + 1:]).strip()
        if not body: raise ValueError('字幕含空时间段，未发布校对版本。')
        items.append({'start': seconds(lines[found]), 'range': translations.srt_time(lines[found].strip()), 'text': body})
    return items


def clean(text):
    return '\n'.join(line.strip() for line in text.replace('\r\n', '\n').splitlines() if line.strip())


def save(project_id, resource, edits):
    """Apply edits keyed by cue start time and publish them as one new correction file."""
    project = library.get(project_id)
    info = project['resources'].get(resource)
    if not isinstance(info, dict) or info.get('kind') not in EDITABLE_KINDS:
        raise ValueError('只能校对已归档的字幕或转写。')
    path = library.resource_from_project(project, resource)
    if path.suffix.lower() not in ('.srt', '.vtt'):
        raise ValueError('只支持 SRT 或 WebVTT 字幕校对。')
    if path.stat().st_size > MAX_BYTES: raise ValueError('字幕超过校对大小上限。')
    try: items = cues(path.read_text(encoding='utf-8-sig'), path.suffix)
    except UnicodeDecodeError: raise ValueError('字幕不是有效的 UTF-8 文本，未发布校对版本。') from None
    if not items: raise ValueError('字幕是空的，无法校对。')
    positions = {}
    for index, item in enumerate(items): positions.setdefault(item['start'], []).append(index)
    edited, seen = 0, set()
    for edit in edits:
        time, text = edit.get('time'), edit.get('text')
        if type(time) not in (int, float) or not math.isfinite(time) or time < 0:
            raise ValueError('字幕时间轴无效，请刷新字幕后重试。')
        if not isinstance(text, str): raise ValueError('字幕文本无效。')
        body = clean(text)
        if not body: raise ValueError('单条字幕不能为空；如需删除整条，请保留原文后另行处理。')
        if '-->' in body or '\x00' in body: raise ValueError('字幕文本不能包含 --> 或空字符。')
        if len(body) > MAX_CUE_CHARS or body.count('\n') >= MAX_CUE_LINES:
            raise ValueError('单条字幕过长，请拆分为多行后再保存。')
        key = round(time, 3)
        if key in seen: raise ValueError('同一条字幕被重复提交，请刷新后重试。')
        seen.add(key)
        found = positions.get(key)
        if not found: raise ValueError('字幕时间轴已变化，请刷新字幕后重试。')
        if len(found) > 1: raise ValueError('这条字幕与其他条目时间轴重复，无法安全定位。')
        item = items[found[0]]
        if item['text'] != body: item['text'], edited = body, edited + 1
    if not edited: raise ValueError('没有需要保存的修改。')
    body = '\n\n'.join(f"{index + 1}\n{item['range']}\n{item['text']}" for index, item in enumerate(items)) + '\n'
    language = info.get('language') or ''
    name = subtitle_names.base_title(project_id, '字幕') + subtitle_names.suffix('correction', language) + '.srt'
    with tempfile.TemporaryDirectory(prefix='.correction-', dir=project['directory']) as directory:
        staged = Path(directory) / 'correction.srt'
        staged.write_text(body, encoding='utf-8', newline='\n')
        # Same publication path as translations: a new resource, never an overwrite.
        key = library.import_file(project_id, staged, 'subtitles/' + name, 'correction',
                                  {'language': language, 'video_resource': info.get('video_resource'),
                                   'source_resource': resource, 'source_sha256': info.get('sha256'), 'download_name': name})
    return {'resource': key, 'filename': name, 'edited': edited, 'cues': len(items)}
