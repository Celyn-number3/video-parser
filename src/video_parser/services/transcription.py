"""Local Whisper bridge. No model imports, shell execution or cloud fallback."""
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import subprocess
from threading import Lock, Thread
import time
from uuid import uuid4

from video_parser.services import library as library
from video_parser.services import task_runtime
from video_parser.core.paths import ROOT
BUNDLED_ROOT = ROOT / 'src/video_parser/integrations/whisper'
TOOL_ROOT = Path(os.getenv('WHISPER_ROOT') or BUNDLED_ROOT)
OUTPUT_ROOT = ROOT / 'outputs/transcriptions'
UPLOAD_ROOT = ROOT / 'cache/react-workspace/transcription-inputs'
MAX_UPLOAD_BYTES = 512 * 1024 * 1024
JOB_TTL = 24 * 60 * 60
MAX_JOBS = 100
EXTENSIONS = {'.wav', '.mp3', '.m4a', '.flac', '.ogg', '.opus', '.aac', '.wma',
              '.mp4', '.mkv', '.webm', '.mov', '.avi', '.m4v'}
jobs_lock = Lock()
worker_lock = Lock()


def runtime_python():
    return ROOT / 'runtimes/whisper/Scripts/python.exe' if TOOL_ROOT == BUNDLED_ROOT else TOOL_ROOT / '.venv/Scripts/python.exe'


def model_directory():
    return ROOT / 'models/whisper/large-v3-turbo' if TOOL_ROOT == BUNDLED_ROOT else TOOL_ROOT / 'models/large-v3-turbo'


def available():
    return all(p.is_file() for p in (runtime_python(), TOOL_ROOT / 'cli.py', model_directory() / 'model.bin'))


def require_tool():
    if not available():
        raise FileNotFoundError('未找到项目内 Whisper 环境或模型，请运行 scripts/setup-local-tools.ps1 -DownloadModel；使用旧外部环境时检查 WHISPER_ROOT。')


def validate_language(language):
    if language not in ('auto', 'zh', 'en'):
        raise ValueError('识别语言应为 auto、zh 或 en。')


def upload_name(filename):
    if (not filename or len(filename) > 255 or any(c in filename for c in ('/', '\\', ':'))
            or any(ord(c) < 32 for c in filename) or Path(filename).suffix.lower() not in EXTENSIONS):
        raise ValueError('请上传有效的音频或视频文件名，不能包含路径。')
    return filename


def validated_outputs(source, directory):
    paths = {extension: directory / (source.stem + '.' + extension) for extension in ('txt', 'srt', 'json')}
    for path in paths.values():
        if (path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(directory.resolve())
                or path.stat().st_size > 64 * 1024 * 1024):
            raise ValueError('转录输出缺失或不安全，未发布任何结果。')
    data = json.loads(paths['json'].read_text(encoding='utf-8'))
    text, segments, language = data.get('text'), data.get('segments'), data.get('language')
    if not isinstance(text, str) or not isinstance(segments, list) or not isinstance(language, str):
        raise ValueError('转录输出格式错误。')
    for segment in segments:
        if not isinstance(segment, dict): raise ValueError('转录片段格式错误。')
        start, end = segment.get('start'), segment.get('end')
        if (type(start) not in (int, float) or type(end) not in (int, float)
                or not math.isfinite(start) or not math.isfinite(end) or not 0 <= start <= end
                or not isinstance(segment.get('text'), str)):
            raise ValueError('转录片段时间戳无效。')
    if text.strip() != '\n'.join(segment['text'].strip() for segment in segments).strip():
        raise ValueError('转录正文与片段不一致。')
    if text.strip() and any(not paths[fmt].read_text(encoding='utf-8').strip() for fmt in ('txt', 'srt')):
        raise ValueError('TXT 或 SRT 输出不完整。')
    return {'text': text, 'language': language, 'segments': segments,
            'directory': str(directory), 'files': {fmt: str(paths[fmt]) for fmt in ('txt', 'srt')}}



def run_whisper(command):
    with subprocess.Popen(command, cwd=TOOL_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                          text=True, encoding='utf-8', errors='replace') as process:
        _,log=task_runtime.communicate(process,7200)
        return subprocess.CompletedProcess(command,process.returncode,stderr=log)


def transcribe(source, language='auto', output_dir=None, timestamps=False, reuse_model=False):
    require_tool()
    validate_language(language)
    source = Path(source).expanduser().resolve(strict=True)
    if not source.is_file() or not source.stat().st_size:
        raise ValueError('音视频文件不存在或为空。')
    if source.suffix.lower() not in EXTENSIONS:
        raise ValueError('不支持此音视频文件扩展名。')
    directory = Path(output_dir).expanduser().resolve() if output_dir else OUTPUT_ROOT / uuid4().hex
    directory.mkdir(parents=True, exist_ok=True)
    for fmt in ('txt', 'srt', 'json', 'whisper.log'):
        if (directory / (source.stem + '.' + fmt)).exists():
            raise FileExistsError('转录输出已存在，拒绝覆盖；请选择新的输出目录。')
    command = [str(runtime_python()), '-X', 'utf8', str(TOOL_ROOT / 'cli.py'),
               'transcribe', str(source), '--language', language, '--format', 'txt,srt,json',
               '--output-dir', str(directory), *(['--timestamps'] if timestamps else [])]
    # OS file locks serialize CLI and web invocations, and release even after a crash.
    try:
        with library.file_lock((ROOT / 'cache/whisper/.transcription.lock') if TOOL_ROOT == BUNDLED_ROOT else (TOOL_ROOT / 'work/.video-parser-transcription.lock'), timeout=7200):
            if reuse_model and TOOL_ROOT==BUNDLED_ROOT:
                from video_parser.services import whisper_pool
                process=whisper_pool.run(command)
            else:
                if TOOL_ROOT==BUNDLED_ROOT:
                    from video_parser.services import whisper_pool
                    whisper_pool.close()
                process=run_whisper(command)
    except subprocess.TimeoutExpired:
        raise RuntimeError('Whisper 转录超时，已停止本次进程；可能保留部分输出，请使用新目录重试。') from None
    except TimeoutError:
        raise RuntimeError('等待本机 Whisper 超时，请稍后重试。') from None
    log = process.stderr or ''
    with (directory / (source.stem + '.whisper.log')).open('x', encoding='utf-8') as stream:
        stream.write(log)
    if process.returncode:
        if 'out of memory' in log.lower():
            raise RuntimeError('GPU 显存不足。请自行决定是否释放其他程序占用后重试；不会自动切换云端或模型。')
        raise RuntimeError('Whisper 转录失败，可能是文件无音轨、损坏或本机运行环境异常。详情保存在结果目录的 .whisper.log 文件；未发布部分输出。')
    try:
        result=validated_outputs(source,directory)
        if hasattr(process,'worker_metadata'):result['worker']=process.worker_metadata
        return result
    except (OSError, ValueError, TypeError, AttributeError):
        raise RuntimeError('转录输出校验失败，未发布任何结果。') from None


@dataclass
class Job:
    id: str
    source: Path
    title: str
    language: str
    project_id: str | None = None
    resource: str | None = None
    owned_input: bool = False
    created_at: float = field(default_factory=time.monotonic)
    state: str = 'queued'
    message: str = '等待本机 Whisper 串行转录…'
    text: str = ''
    detected_language: str = ''
    files: dict = field(default_factory=dict)
    created: float = field(default_factory=time.time)
    phase: str = 'queued'
    progress: dict = field(default_factory=dict)
    error_code: str = ''
    elapsed_seconds: float = 0
    kind: str = ''
    stage_timings: dict = field(default_factory=dict)
    reuse_model: bool = False
    worker: dict = field(default_factory=dict)


jobs: dict[str, Job] = {}


def view(job):
    return {**task_runtime.metadata(job), 'id': job.id, 'state': task_runtime.public_state(job), 'message': job.message, 'title': job.title,
            'text': job.text, 'language': job.detected_language, 'worker':job.worker,
            'files': [{'name': library.safe_name(Path(job.title).stem) + '.' + fmt, 'format': fmt,
                       'url': f'/api/workspace/transcriptions/{job.id}/files/{fmt}'} for fmt in job.files]}


def get(identifier):
    with jobs_lock:
        job = jobs.get(identifier)
        if job and job.state not in task_runtime.ACTIVE and time.monotonic()-job.created_at>JOB_TTL:
            jobs.pop(identifier,None);job=None
        if job is None:
            job=task_runtime.restore(OUTPUT_ROOT/'.tasks',identifier,Job,('source',))
            for item in job.files.values():item['path']=Path(item['path'])
            jobs[identifier]=job
        task_runtime.trim_memory(jobs,keep=identifier)
        return job


def start(source, language='auto', title=None, project_id=None, resource=None, owned_input=False, reuse_model=False):
    require_tool()
    validate_language(language)
    source = Path(source).resolve(strict=True)
    if not source.is_file() or not source.stat().st_size: raise ValueError('输入文件为空或不存在。')
    job = Job(uuid4().hex, source, title or source.name, language, project_id, resource, owned_input)
    job.reuse_model=reuse_model
    with jobs_lock:
        for identifier, old in list(jobs.items()):
            if old.state not in ('queued', 'running') and time.monotonic() - old.created_at > JOB_TTL:
                del jobs[identifier]
        if sum(old.state in task_runtime.ACTIVE for old in jobs.values()) >= MAX_JOBS: raise BlockingIOError('转录任务数量已达上限，请稍后重试。')
        jobs[job.id] = job
        task_runtime.trim_memory(jobs,keep=job.id)
    try:
        task_runtime.submit('transcriptions',job,worker,lambda:task_runtime.save(OUTPUT_ROOT/'.tasks',job),cleanup=lambda:cleanup_input(job))
    except Exception:
        with jobs_lock: jobs.pop(job.id, None)
        raise
    return view(job)


def worker(job):
    state, message = 'failed', '本机转录失败，未发布结果；请检查音轨、Whisper 环境或磁盘空间。'
    try:
        with worker_lock:
            task_runtime.checkpoint()
            task_runtime.progress('transcribing','正在加载模型并转录；完成后校验归档…')
            job.state = 'running'
            job.message = '正在等待或运行本机 Whisper，首次加载模型需要一些时间…'
            source = library.resource(job.project_id, job.resource) if job.project_id else job.source
            result = transcribe(source,job.language,OUTPUT_ROOT/job.id,**({'reuse_model':True} if job.reuse_model else {}))
            job.worker=result.get('worker',{})
        task_runtime.checkpoint()
        task_runtime.progress('validating','正在校验并保存转录结果…')
        job.text = result['text']
        job.detected_language = result['language']
        if not job.text.strip():
            state, message = 'empty', '未识别到有效语音；可能是静音、弱语音或无可识别内容。'
        else:
            files = {}
            task_runtime.progress('archiving','正在归档已校验的转录结果…')
            for fmt, filename in result['files'].items():
                task_runtime.checkpoint()
                path = Path(filename)
                relative = None
                if job.project_id:
                    relative = library.import_file(job.project_id, path, f'transcriptions/{job.id}/{path.name}',
                        'transcription', {'language': job.detected_language, 'video_resource': job.resource})
                    path = library.resource(job.project_id, relative)
                files[fmt] = {'path': path, 'sha256': library.digest(path), 'relative': relative}
            job.files = files
            state, message = 'completed', '转录完成。时间戳为片段级，请人工校对识别结果。'
    except task_runtime.Cancelled:
        raise
    except RuntimeError as error:
        job.error_code='gpu_memory' if '显存不足' in str(error) else task_runtime.classify(error)[0]
        message = str(error)
    except Exception as error:
        job.error_code,message=task_runtime.classify(error)
    finally:
        if job.owned_input:
            try: cleanup_input(job)
            except OSError: message += ' 临时上传文件清理失败，请检查本机缓存。'
        job.message = message
        job.state = state


def download_file(identifier, token):
    job = get(identifier)
    if job.state != 'completed' or token not in job.files: raise KeyError('Unknown output')
    item = job.files[token]
    path = library.resource(job.project_id, item['relative']) if job.project_id else item['path']
    if (path.is_symlink() or not path.is_file()
            or (not job.project_id and not path.resolve().is_relative_to((OUTPUT_ROOT / job.id).resolve()))
            or library.digest(path) != item['sha256']):
        raise ValueError('转录文件已变化。')
    return path


def cleanup_input(job):
    if job.owned_input and not job.source.is_symlink() and job.source.resolve().is_relative_to(UPLOAD_ROOT.resolve()):
        job.source.unlink(missing_ok=True)


def transcribe_batch(sources, language='auto', output_dir=None, timestamps=False):
    """One warm CUDA model per batch. Bad/missing files do not suppress later jobs."""
    from video_parser.services import whisper_pool
    validate_language(language)
    directory=Path(output_dir).expanduser().resolve() if output_dir else OUTPUT_ROOT/uuid4().hex
    directory.mkdir(parents=True,exist_ok=True)
    rows=[]
    try:
        for index,source in enumerate(sources,1):
            task_runtime.checkpoint()
            destination=directory/(f'{index:03d}-'+uuid4().hex[:12])
            try:
                result=transcribe(source,language,destination,timestamps,reuse_model=True)
                rows.append({'source':str(source),'state':'completed',**result})
            except task_runtime.Cancelled:raise
            except Exception as error:
                code,message=task_runtime.classify(error)
                rows.append({'source':str(source),'state':'failed','error_code':code,'message':message})
    finally:whisper_pool.close()
    failed=sum(row['state']=='failed' for row in rows)
    result={'state':'partial' if failed and failed<len(rows) else 'failed' if failed else 'completed',
            'completed':len(rows)-failed,'failed':failed,'results':rows,'directory':str(directory)}
    # Immutable per-batch report, without overwriting earlier batches or output files.
    task_runtime.atomic(directory/('batch-'+uuid4().hex+'.json'),result)
    return result
