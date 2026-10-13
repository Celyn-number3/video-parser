"""Bounded local task lanes, atomic journals, cooperative cancellation and owned processes."""
from dataclasses import asdict, fields
from contextlib import contextmanager
from collections import deque
import contextvars
import errno
import json
import logging
import os
from pathlib import Path
from queue import Queue, Full
import re
import subprocess
from threading import Event, Lock, Thread
import time
from uuid import uuid4

ACTIVE = {'queued', 'running', 'cancelling'}
_context = contextvars.ContextVar('local_task', default=None)
_lock = Lock()
_lanes = {}
_controls = {}
_accepting = True
logger = logging.getLogger(__name__)
_last_emit = 0
_last_phase = None


class Cancelled(RuntimeError):
    pass


def classify(error):
    if isinstance(error, Cancelled): return 'cancelled', '任务已取消；已归档成果保留。'
    if isinstance(error, PermissionError): return 'permission_denied', '目录不可写，请检查本机文件权限。'
    if isinstance(error, OSError) and error.errno == errno.ENOSPC: return 'disk_full', '磁盘空间不足，请释放空间后重试。'
    if isinstance(error, (TimeoutError, subprocess.TimeoutExpired)): return 'timeout', '操作超时，请检查网络或本机运行环境后重试。'
    if isinstance(error, FileNotFoundError): return 'missing_input', '输入文件或运行组件缺失，请检查环境。'
    if isinstance(error, ValueError): return 'invalid_input', '输入或结果校验失败，未发布不完整结果。'
    if type(error).__module__.startswith(('openai.','requests.')):return 'network_error','网络或模型服务请求失败；不会自动重放付费分析。'
    if type(error).__name__ in {'ConnectionError','ConnectTimeout','ReadTimeout','APIConnectionError','APITimeoutError','HTTPError','APIStatusError'}:return 'network_error','网络或模型服务请求失败；不会自动重放付费分析。'
    return 'operation_failed', '操作失败，请检查本机诊断；不会自动重放付费分析。'


def atomic(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink(): raise ValueError('Unsafe journal')
    temporary = path.with_name('.' + uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, default=str)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def save(root, job):
    data = asdict(job)
    # Workflow inputs may include short-lived signed source URLs. Never persist them in the journal.
    data.pop('payload', None)
    atomic(Path(root) / (job.id + '.json'), {'version': 1, 'saved_at': time.time(), 'job': data})


def restore(root, identifier, factory, path_fields=()):
    if not re.fullmatch('[a-f0-9]{32}', identifier): raise KeyError('Unknown task')
    path = Path(root) / (identifier + '.json')
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 16*1024*1024: raise KeyError('Unknown task')
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
        if record.get('version') != 1 or record['job']['id'] != identifier: raise ValueError()
        allowed = {f.name for f in fields(factory)}
        data = {k:v for k,v in record['job'].items() if k in allowed}
        for name in path_fields:
            if data.get(name): data[name] = Path(data[name])
        data['created_at'] = time.monotonic()
        job = factory(**data)
        if job.state in ACTIVE:
            job.state = 'interrupted'; job.phase = 'interrupted'
            job.message = '服务曾重启，任务已中断；请重新提交，不会自动重复执行。'
            job.error_code = 'interrupted'
            save(root, job)
        return job
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise KeyError('Task journal unavailable') from None


def recent_ids(root, limit=100):
    root=Path(root);rows=[]
    if not root.is_dir():return []
    for path in root.glob('*.json'):
        try:
            if re.fullmatch('[a-f0-9]{32}',path.stem) and path.is_file() and not path.is_symlink():rows.append((path.stat().st_mtime,path.stem))
        except OSError:continue
    return [identifier for _,identifier in sorted(rows,reverse=True)[:limit]]


def checkpoint():
    control = _context.get()
    if control and control['cancel'].is_set(): raise Cancelled('任务已取消；已归档成果保留。')


def progress(phase, message=None, **numbers):
    control = _context.get()
    if not control:
        global _last_emit,_last_phase
        target=os.getenv('VIDEO_PARSER_STAGE_FILE')
        if target and (_last_phase!=phase or time.monotonic()-_last_emit>=.5):
            _last_emit=time.monotonic();_last_phase=phase
            atomic(Path(target),{'phase':phase,'message':message,'progress':numbers})
        return
    checkpoint()
    job=control['job']
    if job.phase!=phase:
        now=time.monotonic()
        job.stage_timings[job.phase]=job.stage_timings.get(job.phase,0)+(now-control['phase_start'])
        control['phase_start']=now
    job.phase = phase
    if message: job.message = message
    if numbers: job.progress = {k:v for k,v in numbers.items() if k in {'done','total','bytes','total_bytes'} and isinstance(v,(int,float)) and v>=0}
    control['persist']()


def metadata(job):
    with _lock:
        current=_controls.get(job.id)
        elapsed=time.monotonic()-current['started'] if current and current.get('started') else getattr(job,'elapsed_seconds',0)
        waiting = [c for c in _controls.values() if c['lane'] == getattr(job,'kind','') and c['job'].state == 'queued']
    position = next((i+1 for i,c in enumerate(waiting) if c['job'].id==job.id),0)
    return {'phase':getattr(job,'phase',job.state), 'progress':getattr(job,'progress',{}),
            'error_code':getattr(job,'error_code',''), 'queue_position':position,
            'stage_timings':{k:round(v,3) for k,v in getattr(job,'stage_timings',{}).copy().items()}, 'created':getattr(job,'created',0), 'elapsed_seconds':round(elapsed,3)}


def _consume(queue):
    while True:
        control = queue.get()
        job = control['job']; token = _context.set(control); started = time.monotonic()
        control['started']=started
        job.stage_timings['queued']=started-control['phase_start'];control['phase_start']=started
        try:
            checkpoint(); job.state = 'running'; job.phase = 'starting'; control['persist']()
            control['worker'](job)
        except BaseException as error:
            code,message = classify(error)
            job.state = 'cancelled' if isinstance(error,Cancelled) else 'failed'
            if isinstance(error,Cancelled) and control.get('interrupted'):
                job.state='interrupted';code='interrupted';message='服务已停止，任务中断；已归档成果保留，不会自动重新执行。'
            job.error_code = code; job.message = message
            logger.warning('task_id=%s kind=%s phase=%s error_type=%s code=%s',job.id,control['lane'],getattr(job,'phase',''),type(error).__name__,code)
        finally:
            if hasattr(job,'payload'):job.payload.clear()
            if control.get('cleanup'):
                try:control['cleanup']()
                except OSError:logger.warning('task_id=%s scratch_cleanup_failed',job.id)
            job.stage_timings[job.phase]=job.stage_timings.get(job.phase,0)+time.monotonic()-control['phase_start']
            if job.state=='failed' and not job.error_code:job.error_code='operation_failed'
            job.elapsed_seconds = time.monotonic()-started
            if job.state in ACTIVE: job.state='failed'; job.message='任务未正常结束，请检查本机诊断。';job.error_code='incomplete'
            job.phase = job.state
            try: control['persist']()
            except OSError: logger.error('task_id=%s journal_write_failed',job.id)
            logger.info('task_id=%s kind=%s state=%s elapsed=%.3f',job.id,control['lane'],job.state,job.elapsed_seconds)
            _context.reset(token)
            with _lock: _controls.pop(job.id,None)
            queue.task_done()


def submit(lane, job, worker, persist, capacity=32, cleanup=None):
    with _lock:
        if not _accepting:raise BlockingIOError('服务正在停止，请重新启动后再提交任务。')
        queue = _lanes.get(lane)
        if queue is None:
            queue = Queue(maxsize=capacity); _lanes[lane]=queue
            Thread(target=_consume,args=(queue,),name='task-'+lane,daemon=True).start()
        if queue.full(): raise BlockingIOError('任务队列已满，请等待完成后重试。')
        job.state='queued'; job.phase='queued'; job.kind=lane
        control={'job':job,'worker':worker,'persist':persist,'cancel':Event(),'lane':lane,'phase_start':time.monotonic(),'cleanup':cleanup}
        persist()
        _controls[job.id]=control
        queue.put_nowait(control)


def cancel(identifier):
    with _lock:
        control = _controls.get(identifier)
        if not control or control['job'].state not in ACTIVE:return False
        control['cancel'].set()
        control['job'].message='正在取消，等待本任务子进程退出；已归档成果保留。'
    return True


def any_active():
    with _lock: return bool(_controls)


def active_id(identifier):
    with _lock: return identifier in _controls


def stop_process(process):
    if process.poll() is not None: return
    if os.name == 'nt':
        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15)
    if process.poll() is None: process.kill()
    process.wait(timeout=15)


def communicate(process, timeout, event_reader=None, input=None):
    deadline = time.monotonic()+timeout
    first=True
    try:
        while True:
            checkpoint()
            if event_reader: event_reader()
            remaining=deadline-time.monotonic()
            if remaining<=0: raise subprocess.TimeoutExpired(process.args,timeout)
            try:
                kwargs={'input':input} if first and input is not None else {}
                first=False
                return process.communicate(timeout=min(.25,remaining),**kwargs)
            except subprocess.TimeoutExpired: continue
    except BaseException:
        stop_process(process)
        try: process.communicate(timeout=15)
        except subprocess.TimeoutExpired: pass
        raise


def own_directory(path, identifier):
    path=Path(path); path.mkdir(parents=True,exist_ok=True)
    atomic(path/'.task-owner.json',{'owner':'video-parser','id':identifier,'created':time.time()})


@contextmanager
def maintenance():
    with _lock:
        if _controls:raise BlockingIOError('仍有任务运行或排队，请全部完成后再清理缓存。')
        yield


def public_state(job):
    with _lock:
        # Do not advertise a terminal result before the final journal is durable.
        return 'running' if job.id in _controls and job.state not in ACTIVE else job.state


def trim_memory(mapping,keep=None,limit=100):
    """Journals remain durable; only evict old terminal Python objects."""
    if len(mapping)<=limit:return
    done=sorted((job for job in mapping.values() if job.id!=keep and job.state not in ACTIVE and not active_id(job.id)),key=lambda job:job.created)
    for job in done:
        if len(mapping)<=limit:break
        mapping.pop(job.id,None)


def startup():
    global _accepting
    with _lock:
        if _controls:raise RuntimeError('Previous workers have not stopped')
        _accepting=True


def shutdown(timeout=20):
    global _accepting
    with _lock:
        _accepting=False
        for control in _controls.values():
            if control['job'].state in ACTIVE:
                if not control['cancel'].is_set():control['interrupted']=True
                control['cancel'].set()
    deadline=time.monotonic()+timeout
    while any_active() and time.monotonic()<deadline:time.sleep(.05)
    return not any_active()
