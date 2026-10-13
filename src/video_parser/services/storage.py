"""Conservative cleanup: owned, inactive scratch only, with expiring preview tokens."""
import hashlib
import json
from pathlib import Path
import re
import shutil
from threading import Lock
import time
from uuid import uuid4
from video_parser.core.paths import ROOT
from video_parser.services import task_runtime,library

_plans={}
_lock=Lock()
MIN_AGE=24*60*60


def roots():
    from video_parser.services import subtitles,workflows
    return {'subtitle_scratch':subtitles.CACHE_ROOT,'workflow_scratch':workflows.CACHE_ROOT}


def fingerprint(directory):
    if directory.is_symlink() or (hasattr(directory,'is_junction') and directory.is_junction()):raise ValueError('Linked cache')
    rows=[];total=0
    for path in sorted(directory.rglob('*')):
        if path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction()):raise ValueError('Linked cache')
        if not path.resolve().is_relative_to(directory.resolve()):raise ValueError('Outside cache')
        if path.is_file():
            stat=path.stat();total+=stat.st_size
            rows.append([path.relative_to(directory).as_posix(),stat.st_size,stat.st_mtime_ns,stat.st_ino])
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest(),total


def _size(directory):
    try:return fingerprint(directory)[1] if directory.is_dir() else 0
    except (OSError,ValueError):return None


def preview():
    entries=[];internal=[];usage={};now=time.time()
    for kind,root in roots().items():
        usage[kind]=_size(root)
        if not root.is_dir() or root.is_symlink() or (hasattr(root,'is_junction') and root.is_junction()):continue
        for path in root.iterdir():
            if path.resolve().is_relative_to(library.LIBRARY_ROOT.resolve()):continue
            if not path.is_dir() or not re.fullmatch('[a-f0-9]{32}',path.name) or task_runtime.active_id(path.name):continue
            try:
                owner=json.loads((path/'.task-owner.json').read_text(encoding='utf-8'))
                if owner.get('owner')!='video-parser' or owner.get('id')!=path.name or now-owner['created']<MIN_AGE:continue
                stamp,size=fingerprint(path)
                row={'kind':kind,'id':path.name,'size_bytes':size,'age_hours':round((now-owner['created'])/3600,1)}
                entries.append(row);internal.append((path,stamp,size))
            except (OSError,ValueError,KeyError,TypeError):continue
    from video_parser.services import subtitles
    usage['subtitle_reuse_cache']=_size(subtitles.download_root())
    token=uuid4().hex
    with _lock:
        for key,plan in list(_plans.items()):
            if plan['expires']<now:_plans.pop(key)
        while len(_plans)>=10:_plans.pop(next(iter(_plans)))
        _plans[token]={'expires':now+600,'items':internal}
    return {'plan_id':token,'expires_in_seconds':600,'usage':usage,'entries':entries,
            'size_bytes':sum(row['size_bytes'] for row in entries),
            'protected':['library','models','Cookies','原始音视频','outputs/transcriptions','可复用字幕缓存','任务记录'],
            'note':'只列出 24 小时前本程序创建的、已停止任务临时副本；未知目录和链接不清理。预览后文件变化则跳过。'}


def clean(token):
    with _lock:plan=_plans.pop(token,None)
    if not plan or plan['expires']<time.time():raise ValueError('清理预览已过期，请重新预览。')
    removed=[];skipped=[];total=0
    # Prevent a new managed job from starting between the active check and deletion.
    with task_runtime.maintenance():
        for path,stamp,size in plan['items']:
            try:
                if path.resolve().is_relative_to(library.LIBRARY_ROOT.resolve()) or path.parent not in roots().values() or fingerprint(path)[0]!=stamp:
                    skipped.append(path.name);continue
                shutil.rmtree(path);removed.append(path.name);total+=size
            except (OSError,ValueError):skipped.append(path.name)
    return {'removed':removed,'skipped':skipped,'size_bytes':total}
