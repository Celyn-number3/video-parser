"""Disposable process for downloads/AI: killing its process tree stops local work."""
import json
from pathlib import Path
import sys
from video_parser.services import videos,library,task_runtime


def execute(payload):
    directory=Path(payload['directory']);project_id=payload['project_id']
    project=library.get(project_id)
    if payload['kind']=='video':
        parsed=videos.ParsedVideo(**payload['parsed'])
        selected=videos.select_quality(parsed,payload['quality_id'])
        if library.ensure(selected.metadata)['id']!=project_id:raise ValueError('Project identity mismatch')
        task_runtime.progress('downloading','正在下载所选视频…')
        result=videos.archive_video(selected,staging_root=directory)
        from video_parser.web.routes import media_response
        return media_response(project_id,result['relative'],payload['quality_id'])
    if payload['kind']!='analysis' or payload.get('consent') is not True:raise ValueError('Explicit consent required')
    source=library.resource(project_id,payload['resource'])
    if project['resources'][payload['resource']]['kind']!='video':raise ValueError('Not video')
    from video_parser.services.analysis import analyze_video
    frames=directory/'frames';frames.mkdir()
    task_runtime.progress('analyzing','正在提取画面并发送到已配置的模型服务…')
    text=analyze_video(str(source),prompt=payload.get('prompt') or None,stream=False,
                       num_frames=payload['count'],keep_frames_dir=str(frames))
    if not isinstance(text,str) or not text.strip():raise ValueError('Empty analysis')
    task_runtime.progress('archiving','正在归档分析报告与抽样画面…')
    library.import_frames(project_id,frames)
    report=library.save_text(project_id,'analysis',text,{'frame_count':payload['count'],
        'prompt':payload.get('prompt',''),'video_resource':payload['resource'],'quality_id':payload['quality_id']})
    return {'text':text,'frame_count':payload['count'],
            'report_url':f'/api/workspace/projects/{project_id}/files/{report}',
            'project':library.public(library.get(project_id))}


def main():
    videos.load_environment()
    payload=json.loads(sys.stdin.read(4*1024*1024))
    directory=Path(payload['directory'])
    from video_parser.services.workflows import CACHE_ROOT
    if (not directory.resolve().is_relative_to(CACHE_ROOT.resolve()) or directory.is_symlink()
            or not (directory/'.task-owner.json').is_file()):raise ValueError('Unsafe task directory')
    try:
        result=execute(payload)
        task_runtime.atomic(directory/'result.json',{'ok':True,'result':result})
        return 0
    except Exception as error:
        code,message=task_runtime.classify(error)
        task_runtime.atomic(directory/'result.json',{'ok':False,'error_code':code,'message':message,'error_type':type(error).__name__})
        return 1

if __name__=='__main__':raise SystemExit(main())
