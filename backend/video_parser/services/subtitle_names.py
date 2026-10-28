"""Readable names from current episode metadata, separate from stable resource IDs."""
from pathlib import Path
import re
from video_parser.services import library

LANGUAGES = {'zh': '中文', 'zh-cn': '中文', 'zh-tw': '繁体中文', 'en': '英文',
             'ja': '日语', 'ko': '韩语', 'yue': '粤语', 'auto': '语言未标注'}


def language_label(code):
    code = str(code or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9-]{1,35}', code): return ''
    return LANGUAGES.get(code.lower(), code)


def base_title(project_id, fallback, owned_input=False):
    # Re-read at publication: the user may have renamed a project after a job was created.
    title = Path(fallback).stem if owned_input else fallback
    if project_id and not owned_input:
        project = library.get(project_id)
        title = library.episode_title(project) or project.get('title') or title
    return library.safe_name(title)[:60] or '字幕'


def suffix(kind, language='', source_kind=None, platform='bilibili'):
    origin = source_kind if kind == 'translation' else kind
    # A correction is a proofread copy of another subtitle, not a new source of its own.
    label = {'transcription': '本地转写', 'correction': '校对',
             'subtitle': 'B站平台字幕' if platform == 'bilibili' else '平台字幕'}.get(origin, '来源未确认')
    parts = [language_label(language)]
    if kind == 'translation': parts.append('AI译文')
    parts.append(label)
    return ''.join('-' + part for part in parts if part)
