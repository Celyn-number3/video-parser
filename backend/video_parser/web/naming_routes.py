"""Local-only endpoints for explicit subtitle naming previews and file transactions."""
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from video_parser.services import naming, resource_renames as names
from video_parser.web.security import local_request

router = APIRouter(prefix='/api/workspace', dependencies=[Depends(local_request)])
Identifier = Annotated[str, Field(pattern=r'^[a-f0-9]{32}$')]


class AgentBody(BaseModel):
    engine: Literal['api', 'claude', 'codex', 'opencode'] = 'api'
    model: str = Field(default='', max_length=200)
    effort: str = Field(default='', max_length=40)


class SuggestBody(BaseModel):
    consent: Literal[True]
    agent: AgentBody | None = None
    selected_ids: list[Identifier] | None = Field(default=None, min_length=1, max_length=150)

    @field_validator('consent', mode='before')
    @classmethod
    def explicit_consent(cls, value):
        if value is not True: raise ValueError('请明确同意发送本次课程字幕及可能的联网费用。')
        return value


class Row(BaseModel):
    model_config = {'extra': 'forbid'}
    project_id: Identifier
    number: str = Field(min_length=0, max_length=60)
    title: str = Field(min_length=1, max_length=200)


class ReuseBody(BaseModel):
    model_config = {'extra': 'forbid'}
    selected_ids: list[Identifier] | None = Field(default=None, min_length=1, max_length=150)


class AdjustBody(BaseModel):
    model_config = {'extra': 'forbid'}
    plan_id: Identifier


class PreviewBody(BaseModel):
    rows: list[Row] = Field(min_length=1, max_length=150)


class ConfirmBody(BaseModel):
    confirm: Literal[True]

    @field_validator('confirm', mode='before')
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True: raise ValueError('请明确确认修改所列真实文件名。')
        return value


class ApplyBody(ConfirmBody):
    preview_token: Identifier


def guarded(action, *args):
    try: return action(*args)
    except KeyError: raise HTTPException(404, '项目、命名预览或任务不存在。') from None
    except BlockingIOError as error: raise HTTPException(409, str(error)) from None
    except TimeoutError: raise HTTPException(409, '项目正在被其他操作使用，请稍后重试。') from None
    except ValueError as error: raise HTTPException(400, str(error)) from None
    except OSError: raise HTTPException(507, '文件操作未完成，请检查占用、磁盘空间与目录权限，并查看命名恢复状态。') from None


@router.get('/projects/{identifier}/naming')
def inventory(identifier: str):
    return {**guarded(names.inventory, identifier), 'history': guarded(names.history, identifier)}


@router.post('/projects/{identifier}/naming/plan', status_code=202)
def suggest(identifier: str, body: SuggestBody):
    return guarded(naming.start_plan, identifier, body.consent, body.agent.model_dump() if body.agent else None, body.selected_ids)


@router.post('/projects/{identifier}/naming/reuse', status_code=201)
def reuse(identifier: str, body: ReuseBody):
    return guarded(names.reuse_subtitles, identifier, body.selected_ids)


@router.post('/projects/{identifier}/naming/adjust', status_code=201)
def adjust(identifier: str, body: AdjustBody):
    return guarded(names.adjust_plan, identifier, body.plan_id)


@router.get('/naming/plans/{identifier}')
def read_plan(identifier: str):
    plan = guarded(names.load_plan, identifier)
    public = {key: plan.get(key) for key in ('id', 'project_id', 'title', 'state', 'source', 'adjusted_from', 'rows', 'entries', 'excerpted', 'last_error', 'preview', 'preview_token')}
    public['job_id'] = plan.get('active_job_id') or plan.get('job_id')
    return public


@router.post('/naming/plans/{identifier}/preview')
def preview(identifier: str, body: PreviewBody):
    return guarded(names.validate, identifier, [row.model_dump() for row in body.rows])


@router.post('/naming/plans/{identifier}/apply', status_code=202)
def apply(identifier: str, body: ApplyBody):
    return guarded(naming.start_apply, identifier, body.preview_token, body.confirm)


@router.post('/naming/plans/{identifier}/restore', status_code=202)
def restore(identifier: str, body: ConfirmBody):
    return guarded(naming.start_restore, identifier, body.confirm)


@router.get('/naming/tasks/{identifier}')
def task(identifier: str):
    return guarded(lambda: naming.view(naming.get(identifier)))
