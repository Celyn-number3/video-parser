"""Local-only HTTP bridge for the React workspace, sharing business operations with the CLI."""
from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from threading import Lock
import time
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel, Field, field_validator

from video_parser.services import videos
from video_parser.services import library as library
from video_parser.platforms.downloaders.douyin_downloader import DouyinAccessError

videos.load_environment()
from video_parser.services import subtitles, bili_auth
from video_parser.services import transcription
logger = logging.getLogger(__name__)
WORKSPACE_ROOT = videos.ROOT / 'cache' / 'react-workspace'
SESSION_TTL = 24 * 60 * 60
MAX_SESSIONS = 100
from video_parser.web.security import FILE_HEADERS, local_request


router = APIRouter(prefix='/api/workspace', dependencies=[Depends(local_request)])


class ParseBody(BaseModel):
    text: str = Field(min_length=1, max_length=8192)

    @field_validator('text')
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError('请粘贴视频链接。')
        return value.strip()


class PrepareBody(BaseModel):
    quality_id: str | None = Field(default=None, max_length=80)


class AnalyzeBody(PrepareBody):
    consent: Literal[True]
    count: int = Field(default=6, ge=1, le=16, strict=True)
    prompt: str = Field(default='', max_length=4000)

    @field_validator('consent', mode='before')
    @classmethod
    def explicit_consent(cls, value):
        if value is not True:
            raise ValueError('请明确同意发送画面与可能的费用。')
        return value


@dataclass
class Entry:
    parsed: videos.ParsedVideo
    directory: Path
    project_id: str | None = None
    created_at: float = field(default_factory=time.monotonic)
    cover_type: str | None = None
    cover_extension: str = '.jpg'
    media: dict | None = None
    lock: Lock = field(default_factory=Lock)


entries: dict[str, Entry] = {}
entries_lock = Lock()


def get_entry(identifier):
    with entries_lock:
        entry = entries.get(identifier)
        if entry is None or time.monotonic() - entry.created_at > SESSION_TTL:
            entries.pop(identifier, None)
            raise HTTPException(404, '视频会话已失效，请重新解析链接。')
        return entry


def safe_file(entry, filename):
    try:
        if entry.project_id:
            kind = 'video' if filename == 'video.mp4' else 'cover'
            if kind == 'video' and entry.media:
                return library.resource(entry.project_id, entry.media['resource'])
            found = library.find(entry.project_id, kind)
            if not found: raise OSError('Resource missing')
            return found[1]
        path = (entry.directory / filename).resolve(strict=True)
        if (not path.is_relative_to(entry.directory.absolute())
                or not path.is_relative_to(WORKSPACE_ROOT.resolve()) or not path.is_file()):
            raise OSError('Outside workspace')
        return path
    except (OSError, ValueError, KeyError):
        raise HTTPException(404, '文件尚未准备好，请重新加载。') from None


def media_response(identifier, relative=None, quality_id=None):
    saved = videos.archived_videos(identifier)
    item = next((video for video in saved if relative is None or video['path'] == relative), None)
    if item is None: return None
    media = item['media']
    url = f"/api/workspace/projects/{identifier}/files/{item['path']}"
    return {'preview_url': url, 'download_url': url + '?download=true', 'resource': item['path'],
            'quality_id': quality_id or item['id'],
            'filename': videos.safe_name(library.get(identifier)['title']) + (f"_{item['height']}p" if item['height'] else '') + '.mp4',
            'size_bytes': item['size_bytes'], 'duration': float(media['format']['duration']), 'width': item['width'], 'height': item['height']}


def session_qualities(entry):
    options = []
    used = set()
    if entry.parsed.video_urls:
        for choice in videos.quality_options(entry.parsed):
            saved = videos.saved_quality(entry.project_id, choice)
            if saved: used.add(saved['path'])
            options.append({**choice, 'media': media_response(entry.project_id, saved['path'], choice['id']) if saved else None})
    for saved in videos.archived_videos(entry.project_id):
        if saved['path'] in used: continue
        choice = {key: saved[key] for key in ('id','label','width','height','codec')}
        options.append({**choice, 'media': media_response(entry.project_id, saved['path'], choice['id'])})
    return options


def select_session(entry, quality_id=None):
    options = session_qualities(entry)
    key = quality_id or (options[0]['id'] if options else None)
    choice = next((item for item in options if item['id'] == key), None)
    if choice is None: raise HTTPException(400, '所选清晰度不在可用列表中，请重新解析。')
    return choice


@router.get('/config')
def configuration():
    return {'platforms': list(videos.CONFIG['PLATFORM_MAP']),
            'ai_configured': bool(os.getenv('QWEN_API_KEY', '').strip()),
            'media_ready': bool(shutil.which('ffmpeg') and shutil.which('ffprobe')),
            'subtitles_ready': subtitles.available(), 'transcription_ready': transcription.available(),
            'transcription_upload_limit': transcription.MAX_UPLOAD_BYTES,
            'archive_root': str(library.LIBRARY_ROOT.resolve())}


@router.post('/parse')
def parse(body: ParseBody):
    with entries_lock:
        expired = [key for key, entry in entries.items() if time.monotonic() - entry.created_at > SESSION_TTL]
        for key in expired:
            entries.pop(key)
        if len(entries) >= MAX_SESSIONS:
            raise HTTPException(429, '工作台会话已满，请稍后重试或重启本地服务。')
        identifier = uuid4().hex
        # Reserve before network I/O, so concurrent parses cannot bypass the limit.
        entry = Entry(videos.ParsedVideo({}, {}, [], []), WORKSPACE_ROOT / identifier)
        entries[identifier] = entry
    try:
        entry.parsed = videos.parse_link(body.text)
        entry.directory.mkdir(parents=True, exist_ok=False)
        entry.project_id = library.ensure(entry.parsed.metadata)['id']
    except Exception as error:
        with entries_lock:
            entries.pop(identifier, None)
        logger.warning('Workspace parse failed: %s', type(error).__name__)
        if isinstance(error, DouyinAccessError):
            raise HTTPException(502, str(error)) from None
        if isinstance(error, ValueError):
            raise HTTPException(400, '链接无效或平台暂不支持，请检查后重试。') from None
        raise HTTPException(502, '解析失败，请检查网络或平台限制后重试。') from None
    warning = None
    if entry.parsed.metadata.get('cover_url'):
        try:
            with library.operation(entry.project_id):
                saved = library.find(entry.project_id, 'cover')
                if saved:
                    cover_path = saved[1]
                else:
                    videos.save_cover(entry.parsed, entry.directory / 'cover')
                    cover_path = entry.directory / 'cover'
                with Image.open(cover_path) as image:
                    image_format = image.format
            with Image.open(cover_path) as image:
                formats = {'JPEG': ('image/jpeg', '.jpg'), 'PNG': ('image/png', '.png'),
                           'WEBP': ('image/webp', '.webp'), 'AVIF': ('image/avif', '.avif')}
                entry.cover_type, entry.cover_extension = formats[image_format]
            library.import_file(entry.project_id, cover_path, 'cover' + entry.cover_extension, 'cover')
        except Exception as error:
            logger.warning('Workspace cover failed: %s', type(error).__name__)
            warning = '封面暂时无法加载，仍可预览和下载视频。'
    else:
        warning = '平台未提供封面，仍可预览和下载视频。'
    metadata = entry.parsed.metadata
    saved_cover = library.find(entry.project_id, 'cover')
    cover_url = f'/api/workspace/projects/{entry.project_id}/files/{saved_cover[0]}' if saved_cover else None
    choices = session_qualities(entry)
    entry.media = choices[0]['media'] if choices else None
    return {'id': identifier, 'title': metadata['title'], 'platform': metadata['platform'],
            'source_url': metadata['source_url'], 'cover_url': cover_url,
            'cover_download_url': cover_url + '?download=true' if cover_url else None, 'warning': warning,
            'project': library.public(library.get(entry.project_id)), 'media': entry.media,
            'qualities': choices, 'default_quality_id': choices[0]['id'] if choices else None,
            'bilibili_cookie_status': metadata.get('bilibili_cookie_status')}


@router.post('/videos/{identifier}/prepare')
def prepare(identifier: str, body: PrepareBody):
    entry = get_entry(identifier)
    if not entry.lock.acquire(blocking=False):
        raise HTTPException(409, '视频正在处理中，请等待当前操作完成。')
    try:
        choice = select_session(entry, body.quality_id)
        try:
            entry.media = choice['media']
            if entry.media is None:
                if not entry.parsed.video_urls:
                    raise ValueError('请重新解析链接以获取下载地址。')
                selected = videos.select_quality(entry.parsed, choice['id'])
                result = videos.archive_video(selected)
                entry.media = media_response(entry.project_id, result['relative'], choice['id'])
        except Exception as error:
            logger.warning('Workspace prepare failed: %s', type(error).__name__)
            raise HTTPException(502, '视频准备失败，请检查网络、ffmpeg 或重新解析链接。') from None
        safe_file(entry, 'video.mp4')
        return entry.media
    finally:
        entry.lock.release()


@router.post('/videos/{identifier}/analyze')
def analyze(identifier: str, body: AnalyzeBody):
    entry = get_entry(identifier)
    if not os.getenv('QWEN_API_KEY', '').strip():
        raise HTTPException(503, '尚未配置 AI 密钥，请在本机 .env 中配置 QWEN_API_KEY 并重启服务。')
    choice = select_session(entry, body.quality_id or (entry.media['quality_id'] if entry.media else None))
    if not choice['media']:
        raise HTTPException(409, '请先下载并归档所选视频，再分析画面。')
    if not entry.lock.acquire(blocking=False):
        raise HTTPException(409, '视频正在处理中，请等待当前操作完成。')
    try:
        entry.media = choice['media']
        path = safe_file(entry, 'video.mp4')
        try:
            from video_parser.services.analysis import analyze_video
            with tempfile.TemporaryDirectory(prefix='.analysis-', dir=entry.directory) as directory:
                text = analyze_video(str(path), prompt=body.prompt.strip() or None, stream=False, num_frames=body.count, keep_frames_dir=directory)
                library.import_frames(entry.project_id, directory)
            report = library.save_text(entry.project_id, 'analysis', text, {'frame_count': body.count, 'prompt': body.prompt, 'video_resource': entry.media['resource'], 'quality_id': entry.media['quality_id']})
            if not text:
                raise RuntimeError('Empty analysis')
            return {'text': text, 'frame_count': body.count, 'report_url': f'/api/workspace/projects/{entry.project_id}/files/{report}', 'project': library.public(library.get(entry.project_id))}
        except Exception as error:
            logger.warning('Workspace analysis failed: %s', type(error).__name__)
            raise HTTPException(502, '分析失败，请检查模型服务配置后重试。') from None
    finally:
        entry.lock.release()


@router.get('/files/{identifier}/{kind}')
def file(identifier: str, kind: str, download: bool = False):
    entry = get_entry(identifier)
    if kind == 'video' and entry.media:
        path, media_type = safe_file(entry, 'video.mp4'), 'video/mp4'
        filename = entry.media['filename']
    elif kind == 'cover' and entry.cover_type:
        path, media_type = safe_file(entry, 'cover'), entry.cover_type
        filename = videos.safe_name(entry.parsed.metadata['title']) + entry.cover_extension
    else:
        raise HTTPException(404, '文件尚未准备好。')
    return FileResponse(path, media_type=media_type, filename=filename,
                        content_disposition_type='attachment' if download else 'inline', headers=FILE_HEADERS)


class SubtitleBody(ParseBody):
    scope: Literal['current', 'all', 'custom'] = 'current'
    episodes: str = Field(default='', max_length=500)


@router.post('/subtitles', status_code=202)
def start_subtitles(body: SubtitleBody):
    try:
        return subtitles.start(body.text, body.scope, body.episodes)
    except FileNotFoundError:
        raise HTTPException(503, '未找到集成字幕模块或校验器，请检查项目安装。') from None
    except ValueError as error:
        raise HTTPException(400, str(error)) from None
    except BlockingIOError as error:
        raise HTTPException(409, str(error)) from None
    except Exception:
        raise HTTPException(502, '无法启动字幕任务，请检查本机工具或视频链接后重试。') from None


@router.get('/subtitles/{identifier}')
def subtitle_status(identifier: str):
    try:
        return subtitles.view(subtitles.get(identifier))
    except KeyError:
        raise HTTPException(404, '字幕任务已失效，请重新下载。') from None


@router.get('/subtitles/{identifier}/files/{token}')
def subtitle_file(identifier: str, token: str):
    try:
        path = subtitles.download_file(identifier, token)
    except (KeyError, OSError, ValueError):
        raise HTTPException(404, '未找到已校验的字幕文件。') from None
    types = {'.json': 'application/json',
             '.srt': 'application/x-subrip', '.md': 'text/markdown'}
    return FileResponse(path, filename=path.name, media_type=types[path.suffix], headers=FILE_HEADERS)




class TranscriptionBody(BaseModel):
    project_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    resource: str = Field(min_length=1, max_length=500)
    language: Literal['auto', 'zh', 'en'] = 'auto'
    reuse_model: bool = False


@router.post('/transcriptions', status_code=202)
def start_transcription(body: TranscriptionBody):
    try:
        transcription.require_tool()
        project = library.get(body.project_id)
        source = library.resource(body.project_id, body.resource)
        if project['resources'][body.resource]['kind'] != 'video':
            raise HTTPException(400, '只能转写已归档的视频资源。')
        return transcription.start(source,body.language,project['title'],body.project_id,body.resource,reuse_model=body.reuse_model)
    except FileNotFoundError:
        raise HTTPException(503, '未找到项目内 Whisper 环境或模型，请运行 scripts/setup-local-tools.ps1 -DownloadModel。') from None
    except (KeyError, ValueError, OSError) as error:
        if isinstance(error, BlockingIOError): raise HTTPException(429, str(error)) from None
        raise HTTPException(404, '所选视频尚未归档或已变化，请重新下载。') from None


@router.post('/transcriptions/upload', status_code=202)
async def upload_transcription(request: Request, filename: str, language: Literal['auto', 'zh', 'en'] = 'auto', reuse_model: bool = False):
    try:
        transcription.require_tool()
        transcription.upload_name(filename)
        length = request.headers.get('content-length')
        if length is not None:
            if not length.isdecimal(): raise ValueError('上传长度无效。')
            if int(length) > transcription.MAX_UPLOAD_BYTES: raise HTTPException(413, '音视频超过上传大小上限。')
    except FileNotFoundError:
        raise HTTPException(503, '未找到项目内 Whisper 环境或模型，请运行 scripts/setup-local-tools.ps1 -DownloadModel。') from None
    except ValueError as error:
        raise HTTPException(400, str(error)) from None
    transcription.UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    path = transcription.UPLOAD_ROOT / (uuid4().hex + Path(filename).suffix.lower())
    handed_off = False
    try:
        size = 0
        # Stream and count the actual bytes; do not trust Content-Length or load the file into RAM.
        with path.open('xb') as stream:
            async for chunk in request.stream():
                size += len(chunk)
                if size > transcription.MAX_UPLOAD_BYTES: raise HTTPException(413, '音视频超过上传大小上限。')
                stream.write(chunk)
        if not size: raise HTTPException(400, '上传文件为空。')
        result = transcription.start(path,language,filename,owned_input=True,reuse_model=reuse_model)
        handed_off = True
        return result
    except BlockingIOError as error:
        raise HTTPException(429, str(error)) from None
    except OSError:
        raise HTTPException(500, '无法保存上传文件，请检查磁盘空间与目录权限。') from None
    finally:
        if not handed_off: path.unlink(missing_ok=True)


@router.get('/transcriptions/{identifier}')
def transcription_status(identifier: str):
    try:
        return transcription.view(transcription.get(identifier))
    except KeyError:
        raise HTTPException(404, '转录任务已失效；已生成的结果仍保留在本机目录。') from None


@router.get('/transcriptions/{identifier}/files/{token}')
def transcription_file(identifier: str, token: str):
    try:
        path = transcription.download_file(identifier, token)
        title = transcription.get(identifier).title
    except (KeyError, OSError, ValueError):
        raise HTTPException(404, '转录文件不存在或已变化。') from None
    return FileResponse(path, filename=library.safe_name(Path(title).stem) + path.suffix,
                        media_type='text/plain' if token == 'txt' else 'application/x-subrip', headers=FILE_HEADERS)


@router.get('/projects/{identifier}')
def project_details(identifier: str):
    try:
        project = library.get(identifier)
        response = library.public(project)
        response['media'] = media_response(identifier)
        return response
    except (KeyError, ValueError, OSError):
        raise HTTPException(404, '视频项目不存在或资源未通过校验。') from None


@router.get('/projects/{identifier}/files/{relative:path}')
def project_file(identifier: str, relative: str, download: bool = False):
    try:
        project = library.get(identifier)
        path = library.resource(identifier, relative)
    except (KeyError, ValueError, OSError):
        raise HTTPException(404, '未找到已校验的项目资源。') from None
    info = project['resources'][relative]
    filename = info.get('download_name', path.name)
    if info['kind'] == 'video':
        current = media_response(identifier, relative)
        if current: filename = current['filename']
    return FileResponse(path, filename=filename, content_disposition_type='attachment' if download else 'inline', headers=FILE_HEADERS)


@router.get('/projects/{identifier}/archive')
def project_archive(identifier: str):
    try:
        project = library.get(identifier)
        path = library.archive(identifier)
    except (KeyError, ValueError, OSError):
        raise HTTPException(404, '视频项目或资源缺失，无法导出。') from None
    from starlette.background import BackgroundTask
    return FileResponse(path, filename=videos.safe_name(project['title']) + '_项目.zip', media_type='application/zip',
                        headers=FILE_HEADERS, background=BackgroundTask(path.unlink, missing_ok=True))


@router.post('/projects/{identifier}/open')
def open_project(identifier: str):
    try:
        project = library.get(identifier)
        path = library.contained(project['directory'], 'project.json').parent
        if sys.platform == 'win32': os.startfile(str(path))
        else: subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(path)])
        return {'message': '已请求打开项目文件夹。'}
    except (KeyError, ValueError, OSError):
        raise HTTPException(404, '无法打开项目文件夹。') from None


@router.get('/projects/{identifier}/resume')
def resume_project(identifier: str, quality_id: str | None = None):
    try:
        project = library.get(identifier)
        metadata = {'title': project['title'], 'platform': next((label for label, slug in library.PLATFORMS.items() if slug == project['platform']), project['platform']),
                    'video_id': project['video_id'], 'source_url': project['source_url']}
        entry = Entry(videos.ParsedVideo(metadata, {}, [], []), WORKSPACE_ROOT / identifier, project_id=identifier)
        entry.directory.mkdir(parents=True, exist_ok=True)
        choices = session_qualities(entry)
        selected = next((choice for choice in choices if choice['id'] == quality_id or (choice['media'] and choice['media']['resource'] == quality_id)), None)
        selected = selected or (choices[0] if choices else None)
        entry.media = selected['media'] if selected else None
        cover = library.find(identifier, 'cover')
        if cover:
            entry.cover_type = {'.jpg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp', '.avif': 'image/avif'}.get(cover[1].suffix, 'image/jpeg')
        with entries_lock: entries[identifier] = entry
        cover_url = f'/api/workspace/projects/{identifier}/files/{cover[0]}' if cover else None
        reports = [name for name, item in project['resources'].items() if item['kind'] == 'analysis' and (not item.get('video_resource') or (entry.media and item['video_resource'] == entry.media['resource']))]
        text = library.resource(identifier, reports[-1]).read_text(encoding='utf-8') if reports else ''
        return {'id': identifier, **metadata, 'project': library.public(project), 'media': entry.media,
                'cover_url': cover_url, 'cover_download_url': cover_url + '?download=true' if cover_url else None,
                'warning': None, 'analysis': text, 'qualities': choices, 'default_quality_id': selected['id'] if selected else None}
    except (KeyError, ValueError, OSError):
        raise HTTPException(404, '项目已失效或资源缺失，请重新解析。') from None


# Same-origin / loopback guard and no-store headers apply to every login route.
def login_call(function, *args):
    try:
        return function(*args)
    except (RuntimeError, OSError):
        raise HTTPException(502, 'B站登录服务暂时不可用，请检查网络或稍后刷新二维码。') from None


@router.get('/bili-login/status')
def bili_login_status():
    return login_call(bili_auth.status)


@router.post('/bili-login')
def bili_login_create():
    return login_call(bili_auth.create)


@router.post('/bili-login/{identifier}/poll')
def bili_login_poll(identifier: str):
    return login_call(bili_auth.poll, identifier)


@router.post('/bili-login/{identifier}/cancel')
def bili_login_cancel(identifier: str):
    return bili_auth.discard(identifier)
