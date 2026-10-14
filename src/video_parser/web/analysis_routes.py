"""AI 分析：模型设置、分析素材、画面预览，以及分析记录（历史、追问、导出）。"""
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, field_validator

from video_parser.services import ai_analysis, ai_settings, docx_export, library, task_runtime, workflows
from video_parser.web import routes
from video_parser.web.security import local_request

router = APIRouter(prefix='/api/workspace', dependencies=[Depends(local_request)])
NOT_CONFIGURED = '尚未配置 AI 模型，请在“设置 → AI 模型”里填写。'


def handled(action, *args):
    try:
        return action(*args)
    except ai_analysis.AnalysisError as error:
        raise HTTPException(400, error.user_message) from None
    except KeyError:
        raise HTTPException(404, '找不到这条分析记录或文件，可能已被删除。') from None
    except BlockingIOError as error:
        raise HTTPException(409, str(error)) from None
    except ValueError as error:
        raise HTTPException(400, str(error)) from None
    except FileNotFoundError:
        raise HTTPException(503, '所需本机工具（ffmpeg）缺失，请检查安装。') from None
    except OSError:
        raise HTTPException(507, '无法写入文件，请检查空间与目录权限。') from None
    except RuntimeError as error:  # ai_settings raises short, key-free messages.
        raise HTTPException(502, str(error)) from None


def explicit(value):
    if value is not True:
        raise ValueError('请明确同意把分析材料发送到所选模型服务。')
    return value


class AnalysisTaskBody(routes.PrepareBody):
    consent: Literal[True]
    template: Literal[tuple(ai_analysis.TEMPLATES)] = 'summary'
    source: Literal['both', 'transcript', 'frames'] = 'both'
    transcript_resource: str | None = Field(default=None, max_length=500)
    frame_mode: Literal['scene', 'uniform'] = 'scene'
    count: int = Field(default=0, ge=0, le=16, strict=True)
    preview_token: str | None = Field(default=None, pattern=r'^[0-9a-f]{32}$')
    frames: list[Annotated[str, Field(pattern=r'^frame_\d{3}\.jpg$')]] | None = Field(default=None, min_length=1, max_length=16)
    prompt: str = Field(default='', max_length=4000)

    @field_validator('consent', mode='before')
    @classmethod
    def explicit_consent(cls, value):
        return explicit(value)


class PreviewBody(routes.PrepareBody):
    mode: Literal['scene', 'uniform'] = 'scene'
    count: int = Field(default=0, ge=0, le=16, strict=True)


class AskBody(BaseModel):
    consent: Literal[True]
    question: str = Field(min_length=1, max_length=2000)

    @field_validator('consent', mode='before')
    @classmethod
    def explicit_consent(cls, value):
        return explicit(value)


class ConfirmBody(BaseModel):
    confirm: Literal[True]


class SettingsBody(BaseModel):
    provider: Literal[tuple(ai_settings.PRESETS)]
    base_url: str = Field(min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=500)
    clear_key: bool = False
    price_input: float | None = Field(default=None, ge=0, le=10000)
    price_output: float | None = Field(default=None, ge=0, le=10000)


def archived_video(identifier, quality_id):
    entry = routes.get_entry(identifier)
    choice = routes.select_session(entry, quality_id or (entry.media['quality_id'] if entry.media else None))
    if not choice['media']:
        raise HTTPException(409, '请先下载并归档所选视频。')
    return entry, choice


def start_analysis(entry, choice, body):
    if not ai_settings.configured():
        raise HTTPException(503, NOT_CONFIGURED)
    if body.template == 'custom' and not body.prompt.strip():
        raise HTTPException(400, '自定义分析需要写下分析要求。')
    handled(ai_settings.remember_consent)
    payload = {'resource': choice['media']['resource'], 'quality_id': choice['id'], 'template': body.template, 'source': body.source,
               'transcript_resource': body.transcript_resource, 'frame_mode': body.frame_mode, 'count': body.count,
               'preview_token': body.preview_token, 'frames': body.frames, 'prompt': body.prompt.strip(), 'consent': True}
    return handled(workflows.start, 'analysis', entry.project_id, entry.parsed.metadata['title'], payload)


# ---- Model settings -------------------------------------------------------------

@router.get('/ai/settings')
def get_settings():
    return ai_settings.public()


@router.post('/ai/settings')
def save_settings(body: SettingsBody):
    return handled(ai_settings.save, body.provider, body.base_url, body.model, body.api_key, body.clear_key, body.price_input, body.price_output)


@router.post('/ai/settings/test')
def test_settings():
    if not ai_settings.configured():
        raise HTTPException(503, NOT_CONFIGURED)
    return handled(ai_settings.test)


# ---- Material, preview and analysis ---------------------------------------------

@router.get('/projects/{project_id}/analysis/context')
def analysis_context(project_id: str, resource: str = ''):
    return {**handled(ai_analysis.context, project_id, resource), 'ai': ai_settings.public()}


@router.post('/videos/{identifier}/analysis/frames')
def preview_frames(identifier: str, body: PreviewBody):
    entry, choice = archived_video(identifier, body.quality_id)
    return handled(ai_analysis.create_preview, entry.project_id, choice['media']['resource'], body.mode, body.count)


@router.get('/analysis/previews/{token}/{name}')
def preview_image(token: str, name: str):
    return FileResponse(handled(ai_analysis.preview_file, token, name), media_type='image/jpeg', headers={'Cache-Control': 'private, max-age=600'})


# ---- Records ------------------------------------------------------------------

def project_busy(project_id):
    with workflows.lock:
        return any(job.project_id == project_id and job.kind == 'analysis' and job.state in task_runtime.ACTIVE for job in workflows.jobs.values())


@router.get('/projects/{project_id}/analyses')
def list_records(project_id: str):
    return {'records': handled(ai_analysis.records, project_id)}


@router.post('/projects/{project_id}/analyses/{record_id}/delete')
def delete_record(project_id: str, record_id: str, body: ConfirmBody):
    if project_busy(project_id):
        raise HTTPException(409, '这个视频正在分析或追问，请完成后再删除记录。')
    handled(ai_analysis.delete, project_id, record_id)
    return {'records': handled(ai_analysis.records, project_id)}


@router.post('/projects/{project_id}/analyses/{record_id}/ask-task', status_code=202)
def ask_task(project_id: str, record_id: str, body: AskBody):
    if not ai_settings.configured():
        raise HTTPException(503, NOT_CONFIGURED)
    handled(ai_analysis.record, project_id, record_id)
    project = handled(library.get, project_id)
    handled(ai_settings.remember_consent)
    return handled(workflows.start, 'analysis', project_id, project['title'],
                   {'mode': 'ask', 'record': record_id, 'question': body.question.strip(), 'consent': True})


@router.get('/projects/{project_id}/analyses/{record_id}/export')
def export_record(project_id: str, record_id: str, format: Literal['md', 'docx'] = 'md'):
    markdown, filename = handled(ai_analysis.export_markdown, project_id, record_id)
    if format == 'docx':
        content = docx_export.build(markdown, filename)
        media = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    else:
        content, media = markdown.encode('utf-8'), 'text/markdown; charset=utf-8'
    name = f'{filename}.{format}'
    return Response(content, media_type=media, headers={
        'Content-Disposition': f"attachment; filename=\"analysis.{format}\"; filename*=UTF-8''{quote(name)}",
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
