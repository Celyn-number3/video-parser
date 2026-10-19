"""AI 分析：模型设置、分析素材、画面预览，以及分析记录（历史、追问、导出）。"""
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, field_validator

from video_parser.services import ai_analysis, conversations, ai_settings, ai_startup, ai_runtime, ai_files, docx_export, library, task_runtime, workflows, local_agents, model_calls
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


class AgentTargetBody(BaseModel):
    model_config = {'extra': 'forbid'}
    engine: Literal['api', 'claude', 'codex', 'opencode'] = 'api'
    model: str = Field(default='', max_length=200, strict=True)
    effort: str = Field(default='', max_length=32, strict=True)

    @field_validator('model', 'effort')
    @classmethod
    def valid_selection(cls, value, info):
        local_agents.normalize({'engine': 'codex', info.field_name: value})
        return value


class AgentDiscoveryBody(BaseModel):
    model_config = {'extra': 'forbid'}
    confirm: Literal[True]
    engine: Literal['all', 'claude', 'codex', 'opencode'] = 'all'
    model: str = Field(default='', max_length=200, strict=True)

    @field_validator('confirm', mode='before')
    @classmethod
    def explicit_discovery(cls, value):
        return explicit(value)

    @field_validator('model')
    @classmethod
    def valid_model(cls, value):
        local_agents.normalize({'engine': 'codex', 'model': value})
        return value


def selected_agent(value=None, fallback=None):
    target = handled(model_calls.target, value.model_dump() if value is not None else fallback)
    if target['engine'] == 'api' and not ai_settings.configured():
        raise HTTPException(503, NOT_CONFIGURED)
    return handled(local_agents.require, target)


class AnalysisTaskBody(routes.PrepareBody):
    agent: AgentTargetBody | None = None
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
    agent: AgentTargetBody | None = None
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
    startup: dict | None = None


class RuntimeStartBody(BaseModel):
    model_config = {'extra': 'forbid'}
    confirm: Literal[True]

    @field_validator('confirm', mode='before')
    @classmethod
    def explicit_start(cls, value):
        if value is not True:
            raise ValueError('请明确确认启动本机模型。')
        return value


class ModelFileBody(BaseModel):
    model_config = {'extra': 'forbid'}
    field: Literal['model_path', 'vision_path', 'server_path']


class StartupCheckBody(BaseModel):
    startup: dict
    model: str = Field(min_length=1, max_length=200)


def archived_video(identifier, quality_id):
    entry = routes.get_entry(identifier)
    choice = routes.select_session(entry, quality_id or (entry.media['quality_id'] if entry.media else None))
    if not choice['media']:
        raise HTTPException(409, '请先下载并归档所选视频。')
    return entry, choice


def start_analysis(entry, choice, body):
    agent = selected_agent(body.agent)
    if body.template == 'custom' and not body.prompt.strip():
        raise HTTPException(400, '自定义分析需要写下分析要求。')
    handled(model_calls.consent, agent)
    payload = {'resource': choice['media']['resource'], 'quality_id': choice['id'], 'template': body.template, 'source': body.source,
               'transcript_resource': body.transcript_resource, 'frame_mode': body.frame_mode, 'count': body.count,
               'preview_token': body.preview_token, 'frames': body.frames, 'prompt': body.prompt.strip(), 'consent': True}
    if agent['engine'] != 'api':
        payload['agent'] = agent
    return handled(workflows.start, 'analysis', entry.project_id, entry.parsed.metadata['title'], payload)


# ---- Model settings -------------------------------------------------------------

@router.get('/ai/agents')
def agent_inventory():
    return handled(local_agents.inventory)


@router.post('/ai/agents/discover')
def discover_agents(body: AgentDiscoveryBody):
    # Metadata only. Never send a course, user question, authentication details or account object here.
    return handled(local_agents.discover, body.engine, body.model)


@router.get('/ai/settings')
def get_settings():
    return ai_settings.public()


@router.post('/ai/settings')
def save_settings(body: SettingsBody):
    return handled(ai_settings.save, body.provider, body.base_url, body.model, body.api_key, body.clear_key, body.price_input, body.price_output, body.startup)


@router.post('/ai/startup/check')
def check_startup(body: StartupCheckBody):
    return handled(ai_startup.inspect, body.startup, body.model)


@router.post('/ai/files/pick')
def pick_model_file(body: ModelFileBody):
    return {'path': handled(ai_files.pick, body.field)}


@router.get('/ai/runtime')
def model_runtime():
    return handled(ai_runtime.status)


@router.post('/ai/runtime/start', status_code=202)
def start_model(body: RuntimeStartBody):
    return handled(ai_runtime.start)


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
    agent = selected_agent(body.agent)
    handled(ai_analysis.record, project_id, record_id)
    project = handled(library.get, project_id)
    handled(model_calls.consent, agent)
    payload = {'mode': 'ask', 'record': record_id, 'question': body.question.strip(), 'consent': True}
    if agent['engine'] != 'api':
        payload['agent'] = agent
    return handled(workflows.start, 'analysis', project_id, project['title'], payload)


@router.post('/projects/{project_id}/analyses/{record_id}/clear-context')
def clear_context(project_id: str, record_id: str):
    if project_busy(project_id):
        raise HTTPException(409, '这个视频正在分析或追问，请完成后再清空上下文。')
    handled(ai_analysis.clear_context, project_id, record_id)
    return {'records': handled(ai_analysis.records, project_id)}


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


# ---- Independent video conversations -------------------------------------------

class ConversationBody(BaseModel):
    model_config = {'extra': 'forbid'}
    agent: AgentTargetBody | None = None
    resource: str = Field(min_length=1, max_length=1000)


class ConversationAskBody(AskBody):
    model_config = {'extra': 'forbid'}
    resource: str = Field(min_length=1, max_length=1000)
    position: float = Field(ge=0, allow_inf_nan=False)

    @field_validator('question')
    @classmethod
    def nonempty_question(cls, value):
        if not value.strip():
            raise ValueError('请输入问题。')
        return value.strip()


@router.get('/projects/{project_id}/conversations')
def conversation_list(project_id: str):
    return {'conversations': handled(conversations.list_sessions, project_id)}


@router.get('/projects/{project_id}/conversations/context')
def conversation_context(project_id: str, resource: str):
    return handled(conversations.availability, project_id, resource)


@router.post('/projects/{project_id}/conversations/migrate')
def migrate_conversations(project_id: str):
    if project_busy(project_id):
        raise HTTPException(409, '请等待当前视频任务结束后再读取历史对话。')
    return {'conversations': handled(conversations.migrate, project_id)}


@router.post('/projects/{project_id}/conversations')
def new_conversation(project_id: str, body: ConversationBody):
    return {'conversation': handled(conversations.create, project_id, body.resource, body.agent.model_dump() if body.agent else None)}


@router.post('/projects/{project_id}/conversations/{conversation_id}/ask-task', status_code=202)
def ask_conversation(project_id: str, conversation_id: str, body: ConversationAskBody):
    session = handled(conversations.get, project_id, conversation_id)
    agent = selected_agent(body.agent, session.get('agent'))
    handled(conversations.check_agent, session, agent)
    if session.get('video_resource') not in (None, body.resource):
        raise HTTPException(400, '这个对话属于另一个视频，请切换对话或新建。')
    handled(conversations.require_ready, project_id, body.resource)
    project = handled(library.get, project_id)
    info = handled(ai_analysis.video_info, project, body.resource)
    if body.position > info['duration']:
        raise HTTPException(400, '视频时间超出时长，请重新提问。')
    handled(model_calls.consent, agent)
    payload = {'mode': 'conversation', 'conversation': conversation_id, 'resource': body.resource,
        'position': body.position, 'question': body.question, 'consent': True}
    if agent['engine'] != 'api':
        payload['agent'] = agent
    return handled(workflows.start, 'analysis', project_id, project['title'], payload)
