"""Task and maintenance endpoints for the existing local-only workbench."""
from dataclasses import asdict
import os
from pathlib import Path
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field,field_validator
from video_parser.web.security import local_request
from video_parser.web import routes,analysis_routes
from video_parser.services import task_runtime,subtitles,transcription,workflows,storage,library,naming

router=APIRouter(prefix='/api/workspace',dependencies=[Depends(local_request)])


def guarded(action,*args):
    try:return action(*args)
    except KeyError:raise HTTPException(404,'找不到任务记录。') from None
    except BlockingIOError as error:raise HTTPException(409,str(error)) from None
    except ValueError as error:raise HTTPException(400,str(error)) from None
    except FileNotFoundError:raise HTTPException(503,'所需本机工具或文件缺失，请检查安装。') from None
    except OSError:raise HTTPException(507,'无法写入任务或缓存信息，请检查空间与目录权限。') from None


@router.post('/videos/{identifier}/prepare-task',status_code=202)
def prepare_task(identifier:str,body:routes.PrepareBody):
    entry=routes.get_entry(identifier);choice=routes.select_session(entry,body.quality_id)
    if not choice['media'] and not entry.parsed.video_urls:raise HTTPException(409,'请先重新解析链接。')
    return guarded(workflows.start,'video',entry.project_id,entry.parsed.metadata['title'],
                   {'parsed':asdict(entry.parsed),'quality_id':choice['id']})


@router.post('/videos/{identifier}/analyze-task',status_code=202)
def analyze_task(identifier:str,body:analysis_routes.AnalysisTaskBody):
    entry,choice=analysis_routes.archived_video(identifier,body.quality_id)
    return analysis_routes.start_analysis(entry,choice,body)


def catalog():
    return {'subtitles':(subtitles,subtitles.CACHE_ROOT/'.tasks'),'transcriptions':(transcription,transcription.OUTPUT_ROOT/'.tasks'),
            'workflows':(workflows,workflows.RECORD_ROOT),'naming':(naming,naming.RECORD_ROOT)}


def project_labels():
    """Current project title/part, so renamed courses and their episodes read correctly in old task records."""
    cache={}
    def label(identifier):
        if not identifier:return {'project_title':None,'part':None}
        if identifier not in cache:
            try:
                project=library.get(identifier)
                title=' · '.join(project[key] for key in ('title','episode_title') if project.get(key))
                cache[identifier]={'project_title':title or None,'part':project.get('part')}
            except (KeyError,OSError,ValueError,TypeError):cache[identifier]={'project_title':None,'part':None}
        return cache[identifier]
    return label


@router.get('/tasks')
def tasks():
    result=[];label=project_labels()
    for category,(service,root) in catalog().items():
        mutex=getattr(service,'jobs_lock',None) or service.lock
        with mutex:cached=list(service.jobs)
        identifiers=list(dict.fromkeys([*cached,*task_runtime.recent_ids(root)]))
        for identifier in identifiers:
            try:
                job=service.get(identifier);data=service.view(job)
                result.append({key:data.get(key) for key in ('id','state','message','title','phase','progress','error_code','created','elapsed_seconds','queue_position','stage_timings','operation')}|
                    {'kind':job.kind or category,'project_id':getattr(job,'project_id',None)}|label(getattr(job,'project_id',None)))
            except (KeyError,OSError,ValueError):continue
    return {'jobs':sorted(result,key=lambda row:row['created'] or 0,reverse=True)[:100]}


@router.get('/tasks/{identifier}')
def workflow_status(identifier:str):return guarded(lambda:workflows.view(workflows.get(identifier)))


def domain(kind):
    if kind in ('video','analysis'):return workflows
    if kind=='subtitles':return subtitles
    if kind=='transcriptions':return transcription
    if kind=='naming':return naming
    raise HTTPException(404,'未知任务类别。')


@router.post('/tasks/{kind}/{identifier}/cancel')
def cancel_task(kind:str,identifier:str):
    service=domain(kind);job=guarded(service.get,identifier)
    task_runtime.cancel(identifier)
    return service.view(job)


CLEARABLE={'failed','cancelled','interrupted'}


class ClearTasksBody(BaseModel):
    confirm:Literal[True]

    @field_validator('confirm',mode='before')
    @classmethod
    def explicit_confirmation(cls,value):
        if value is not True:raise ValueError('请明确确认清理任务记录。')
        return value


@router.post('/tasks/clear')
def clear_tasks(body:ClearTasksBody):
    # Deletes only the journals of tasks that ended without a result (failed / cancelled / interrupted).
    # Output files, archives and successful or running tasks are never touched.
    removed=0
    for category,(service,root) in catalog().items():
        mutex=getattr(service,'jobs_lock',None) or service.lock
        with mutex:cached=list(service.jobs)
        for identifier in dict.fromkeys([*cached,*task_runtime.recent_ids(root,limit=100000)]):
            try:job=service.get(identifier)
            except (KeyError,OSError,ValueError):continue
            if job.state not in CLEARABLE or task_runtime.active_id(identifier):continue
            try:(Path(root)/(identifier+'.json')).unlink(missing_ok=True)
            except OSError:continue
            with mutex:service.jobs.pop(identifier,None)
            removed+=1
    return {'removed':removed}


@router.post('/tasks/subtitles/{identifier}/retry',status_code=202)
def retry_subtitles(identifier:str):return guarded(subtitles.retry_failed,identifier)


class CleanupBody(BaseModel):
    plan_id:str=Field(pattern=r'^[a-f0-9]{32}$')
    confirm:Literal[True]

    @field_validator('confirm',mode='before')
    @classmethod
    def explicit_confirmation(cls,value):
        if value is not True:raise ValueError('请明确确认清理所列缓存。')
        return value


@router.post('/cache/preview')
def cache_preview():return guarded(storage.preview)


@router.post('/cache/clean')
def cache_clean(body:CleanupBody):return guarded(storage.clean,body.plan_id)
