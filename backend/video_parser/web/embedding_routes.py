"""Local-only settings and explicitly requested embedding calls."""
from typing import Literal
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from video_parser.web.security import local_request
from video_parser.web.analysis_routes import handled
from video_parser.services import embedding_search

router = APIRouter(prefix='/api/workspace', dependencies=[Depends(local_request)])

class SettingsBody(BaseModel):
    model_config = {'extra': 'forbid'}
    base_url: str = Field(min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=500)
    clear_key: bool = False

class ConsentBody(BaseModel):
    model_config = {'extra': 'forbid'}
    consent: Literal[True]
    @field_validator('consent', mode='before')
    @classmethod
    def explicit(cls, value):
        if value is not True:
            raise ValueError('请明确同意发送字幕或查询到所选 Embedding 服务。')
        return value

class SearchBody(ConsentBody):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=8, ge=1, le=30)
    @field_validator('query')
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError('请输入检索问题。')
        return value.strip()

@router.get('/embedding/settings')
def settings():
    return embedding_search.public()

@router.post('/embedding/settings')
def save(body: SettingsBody):
    return handled(embedding_search.save, body.base_url, body.model, body.api_key, body.clear_key)

@router.post('/projects/{project_id}/embedding/index')
def index(project_id: str, body: ConsentBody):
    return handled(embedding_search.index, project_id)

@router.post('/projects/{project_id}/embedding/search')
def search(project_id: str, body: SearchBody):
    return handled(embedding_search.search, project_id, body.query, body.limit)
