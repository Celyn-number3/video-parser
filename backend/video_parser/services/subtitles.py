"""Local bridge to the existing Bilibili subtitle CLI; never returns cookies."""
from dataclasses import dataclass, field
import importlib.util
import json
import tempfile
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from threading import Lock
import time
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from video_parser.core.paths import CACHE_DIR
from video_parser.services import videos, task_runtime
from video_parser.services import library as library
videos.load_environment()
BUNDLED_ROOT = videos.ROOT / 'backend/video_parser/integrations/bilibili'
TOOL_ROOT = Path(os.getenv('BILI_SUBTITLE_ROOT') or BUNDLED_ROOT)


def resolve_checker_path(tool_root):
    """Honor explicit configuration; otherwise prefer the tool's bundled checker."""
    configured = os.getenv('BILI_SUBTITLE_CHECKER', '').strip()
    if configured:
        return Path(configured).expanduser()
    if Path(tool_root) == BUNDLED_ROOT:
        return BUNDLED_ROOT / 'checker.py'
    bundled = Path(tool_root) / 'skills/bili-subtitle-download/scripts/check_subtitles.py'
    if bundled.is_file():
        return bundled
    return Path.home() / '.codex/skills/bili-subtitle-download/scripts/check_subtitles.py'


CHECKER_PATH = resolve_checker_path(TOOL_ROOT)
CACHE_ROOT = CACHE_DIR / 'react-workspace/subtitles'
JOB_TTL = 24 * 60 * 60
MAX_JOBS = 100
cli_lock = Lock()
jobs_lock = Lock()


@dataclass
class Job:
    id: str
    url: str
    episodes: list[int] | None
    directory: Path
    created_at: float = field(default_factory=time.monotonic)
    state: str = 'running'
    message: str = '正在通过本机工具下载字幕…'
    title: str = ''
    results: list = field(default_factory=list)
    files: dict = field(default_factory=dict)
    created: float = field(default_factory=time.time)
    phase: str = 'queued'
    progress: dict = field(default_factory=dict)
    error_code: str = ''
    elapsed_seconds: float = 0
    kind: str = ''
    stage_timings: dict = field(default_factory=dict)
    skipped: list = field(default_factory=list)


jobs: dict[str, Job] = {}


def available():
    return (TOOL_ROOT / 'b站.py').is_file() and CHECKER_PATH.is_file()


def selection(text, scope, chosen):
    url, platform = videos.resolve_url(text)
    if platform != '哔哩哔哩' or not re.fullmatch(r'/video/BV[A-Za-z0-9]{10}', urlparse(url).path):
        raise ValueError('字幕下载目前只支持 B站 BV 视频链接。')
    number = parse_qs(urlparse(url).query).get('p', ['1'])[0]
    if not number.isdecimal() or not 1 <= int(number) <= 1000:
        raise ValueError('链接中的分集 p 必须是 1–1000 的整数。')
    if scope == 'all':
        return url, None
    if scope == 'current':
        return url, [int(number)]
    selected = set()
    for part in chosen.split(','):
        match = re.fullmatch(r'\s*(\d+)(?:\s*-\s*(\d+))?\s*', part)
        if not match:
            raise ValueError('指定分集格式应为 1-5,8，不允许零、负数或空项。')
        start = int(match[1])
        end = int(match[2] or match[1])
        if not 1 <= start <= end <= 1000:
            raise ValueError('指定分集应为 1–1000，范围不能倒序。')
        selected.update(range(start, end + 1))
    return url, sorted(selected)


def download_root():
    return CACHE_DIR / 'bilibili/subtitle_download' if TOOL_ROOT == BUNDLED_ROOT else TOOL_ROOT / 'subtitle_download'


def command(url, episodes):
    python = videos.ROOT / '.venv/Scripts/python.exe' if TOOL_ROOT == BUNDLED_ROOT else TOOL_ROOT / '.venv/Scripts/python.exe'
    interpreter = str(python) if python.is_file() else sys.executable
    return [interpreter, '-X', 'utf8', '-u', str(TOOL_ROOT / 'b站.py'), url,
            *(['--all'] if episodes is None else ['--ep', ','.join(map(str, episodes))])]


def runtime_environment():
    env = {**os.environ, 'BILI_HEADLESS': '1'}
    bundled_browser = videos.ROOT / 'runtimes/browsers'
    if TOOL_ROOT == BUNDLED_ROOT:
        env['PLAYWRIGHT_BROWSERS_PATH'] = str(bundled_browser)
    elif env.get('PLAYWRIGHT_BROWSERS_PATH') and Path(env['PLAYWRIGHT_BROWSERS_PATH']) == bundled_browser:
        # Explicit legacy override uses its own Playwright version/cache, not the bundled browser revision.
        env.pop('PLAYWRIGHT_BROWSERS_PATH')
    return env


def run_cli(url, episodes):
    from video_parser.services import bili_auth
    if not bili_auth.status()['authenticated']:
        return 1, '缺少登录 Cookie'
    task_runtime.progress('reading', '正在读取课程信息…')
    events_root=CACHE_ROOT/'.events'; events_root.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=events_root) as temporary:
        event_file=Path(temporary)/'events.jsonl'; env=runtime_environment()
        if TOOL_ROOT==BUNDLED_ROOT: env['VIDEO_PARSER_EVENT_FILE']=str(event_file)
        events=[]; offset=0
        def consume():
            nonlocal offset
            if not event_file.exists():return
            if event_file.stat().st_size>4*1024*1024:raise ValueError('Too many worker events')
            with event_file.open(encoding='utf-8') as stream:
                stream.seek(offset)
                while True:
                    line=stream.readline()
                    if not line.endswith('\n'):break
                    offset=stream.tell(); row=json.loads(line)
                    if row.get('version')!=1:raise ValueError('Unsupported worker event')
                    events.append(row)
                    if row.get('event')=='progress':
                        task_runtime.progress('downloading','正在处理字幕分集…',done=row.get('done',0),total=row.get('total',0))
        with subprocess.Popen(command(url,episodes),cwd=TOOL_ROOT,env=env,stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace') as process:
            output,_=task_runtime.communicate(process,1800,consume)
            consume()
            return process.returncode, {'events':events} if TOOL_ROOT==BUNDLED_ROOT else output


def platform_name(title, suffix):
    # Same folder as local transcripts; the name tells the two sources apart.
    return (library.safe_name(title)[:60] or 'subtitle') + '.平台字幕' + suffix


def sanitize_title(title):
    return re.sub(r'[\\/:*?"<>|]', '_', title).strip().replace(' ', '_')[:100] or 'subtitle'


def safe_source(path):
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(download_root().resolve()) or not resolved.is_file():
        raise ValueError('Unsafe subtitle output')
    return resolved


def targets(job, log):
    if isinstance(log,dict):
        rows=[r for r in log.get('events',[]) if r.get('event')=='target']
        if len(rows)!=1:raise RuntimeError('未取得结构化课程信息，请检查登录或平台限制。')
        row=rows[0];title=row.get('title');total=row.get('total');bvid=row.get('bvid')
        if not isinstance(title,str) or not title or type(total)!=int or not 1<=total<=10000 or bvid!=urlparse(job.url).path.split('/')[-1]:
            raise RuntimeError('字幕工作进程返回的目标不匹配。')
        return title,download_root()/sanitize_title(title),total,job.episodes if job.episodes is not None else list(range(1,total+1)),row.get('single') is True
    series = re.search(r'^series: (.+)  \((BV[A-Za-z0-9]{10})\)$', log, re.M)
    if not series or series[2] not in job.url:
        raise RuntimeError('未能确认字幕目标，请在原字幕工具检查登录状态和视频链接。')
    title = series[1]
    directory = download_root() / sanitize_title(title)
    selected = re.search(r'^selected \d+/(\d+) episodes:', log, re.M)
    total = int(selected[1]) if selected else 1 if 'single video, cid=' in log else None
    if not total:
        raise RuntimeError('未取得视频总集数，无法核对字幕下载范围。')
    requested = job.episodes if job.episodes is not None else list(range(1, total + 1))
    return title, directory, total, requested, selected is None


def worker(job):
    try:
        before = {str(p.absolute()): (p.stat().st_mtime_ns, p.stat().st_size)
                  for p in ([] if TOOL_ROOT==BUNDLED_ROOT else download_root().rglob('*')) if p.is_file()}
        code, log = run_cli(job.url, job.episodes)
        try:
            title, directory, total, requested, single = targets(job, log)
        except RuntimeError:
            if isinstance(log,str) and ('缺少登录 Cookie' in log or 'please login manually in browser' in log):
                job.error_code='auth_required'
                job.state = 'login_required'
                job.message = '登录态缺失或已过期，请在工作台扫码登录后重试。'
                return
            raise
        spec = importlib.util.spec_from_file_location('subtitle_checker', CHECKER_PATH)
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)
        task_runtime.progress('validating','正在校验并归档字幕…')
        task_runtime.own_directory(job.directory,job.id)
        rows, downloads = [], {}
        job.results=rows;job.title=title;job.files=downloads
        for episode in requested:
            task_runtime.checkpoint()
            row = {'episode': episode, 'status': 'failed', 'message': '', 'files': []}
            rows.append(row)
            if episode > total:
                row['message'] = f'超出视频总集数（共 {total} 集），原 CLI 会过滤此分集。'
                continue
            candidates = [directory / '_json' / (sanitize_title(title) + '.json')] if single else list((directory / '_json').glob(f'P{episode:02d}_*.json'))
            if len(candidates) != 1:
                row['message'] = '未找到唯一目标字幕，可能受登录、平台限制或页面操作影响；不能据此断言没有字幕。'
                continue
            source = candidates[0]
            triplet = [source, directory / '_srt' / (source.stem + '.srt'), directory / '_md' / (source.stem + '.md')]
            try:
                for path in triplet:
                    safe_source(path)
                checked = checker.check(source)
                if not checked['ok']:
                    raise ValueError('Incomplete subtitle')
                snapshot = job.directory / f'P{episode:02d}'
                task_runtime.checkpoint()
                for path in triplet:
                    target = snapshot / ('_' + path.suffix[1:]) / path.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(safe_source(path), target)
                # Validate the snapshot too, not only files that could change during the copy.
                copied_json = snapshot / '_json' / source.name
                if not checker.check(copied_json)['ok']:
                    raise ValueError('Incomplete snapshot')
                existing = any(r.get('event')=='episode' and r.get('episode')==episode and r.get('status')=='existing' for r in log['events']) if isinstance(log,dict) else all(before.get(str(path.absolute())) == (path.stat().st_mtime_ns,path.stat().st_size) for path in triplet)
                final_status='existing' if existing else 'downloaded'
                row.update(message='正在归档已校验字幕…',lines=checked['lines'])
                task_runtime.progress('archiving','正在将已校验字幕归档到项目…',done=sum(r['status']!='failed' for r in rows),total=len(requested))
                project = library.ensure({'platform': '哔哩哔哩', 'video_id': urlparse(job.url).path.split('/')[-1],
                    'title': title + (f' P{episode:03d}' if total > 1 else ''),
                    'source_url': job.url.split('?')[0] + f'?p={episode}'})
                row['project'] = library.public(project)
                task_runtime.checkpoint()
                for path in triplet:
                    target = snapshot / ('_' + path.suffix[1:]) / path.name
                    task_runtime.checkpoint()
                    relative = library.import_file(project['id'], target, 'subtitles/' + platform_name(project['title'], path.suffix), 'subtitle', {'download_name': path.name})
                    target = library.resource(project['id'], relative)
                    token = f'{episode}-{path.suffix[1:]}'
                    downloads[token] = target
                    row['files'].append({'name': path.name, 'format': path.suffix[1:].upper(),
                                         'url': f"/api/workspace/projects/{project['id']}/files/{relative}?download=true"})
                row.update(status=final_status,message='已有，校验通过' if existing else '本次下载，校验通过')
                # Published paths are in library, so this task's validated copy is no longer needed.
                try:shutil.rmtree(snapshot)
                except OSError:pass
            except (OSError, ValueError, UnicodeError) as error:
                if task_runtime.classify(error)[0]=='disk_full':raise
                row.update(status='failed', files=[])
                row['message'] = '字幕文件缺失、不完整或校验未通过；可重试未完成分集，历史归档会保留。'
        success = sum(row['status'] != 'failed' for row in rows)
        job.progress={'done':success,'total':len(rows)}
        state = 'completed' if rows and success == len(rows) and code == 0 else 'partial' if success else 'failed'
        with jobs_lock:
            job.title, job.results, job.files = title, rows, downloads
            job.message = f'本次下载 {sum(row["status"] == "downloaded" for row in rows)} 集，已有可用 {sum(row["status"] == "existing" for row in rows)} 集，未完成 {len(rows) - success} 集。'
            if code != 0:
                job.message += ' CLI 异常退出，请核对未完成分集。'
            if job.skipped:
                job.message += f' 已跳过本地已有字幕 {len(job.skipped)} 集。'
            job.state = state
            if state=='partial':job.error_code='partial_failure'
    except task_runtime.Cancelled:
        raise
    except RuntimeError as error:
        job.error_code=task_runtime.classify(error)[0]
        job.message = str(error) + ' 未覆盖历史文件。'
        job.state = 'failed'
    except Exception as error:
        job.error_code,job.message=task_runtime.classify(error)
        job.message += ' 已归档成果保留。'
        job.state = 'failed'
    finally:
        if job.state=='completed' and job.directory.is_dir():
            try:
                if not any(p.name!='.task-owner.json' for p in job.directory.iterdir()):
                    (job.directory/'.task-owner.json').unlink(missing_ok=True)
                    job.directory.rmdir()
            except OSError:pass


def local_inventory(text):
    """Read-only and offline: the BV id is read from the pasted text; short links are not resolved."""
    match = re.search(r'BV[A-Za-z0-9]{10}', text or '')
    if not match: return {'video_id': None, 'total': None, 'archived': [], 'episodes': []}
    return library.subtitle_inventory(match[0])


def skip_archived(url, requested):
    """Remove episodes whose verified platform subtitles are already in the library.

    Returns (remaining, skipped). An unknown 'all' range stays None so the CLI still decides."""
    inventory = library.subtitle_inventory(urlparse(url).path.split('/')[-1])
    archived = set(inventory['archived'])
    if not archived: return requested, []
    if requested is None:
        requested = [episode['part'] for episode in inventory['episodes']]
        if not requested: return None, []
    skipped = [number for number in requested if number in archived]
    remaining = [number for number in requested if number not in archived]
    if not remaining:
        raise ValueError('所选分集都已有校验通过的平台字幕，无需重复下载；可在项目文件夹或任务中心查看。')
    return remaining, skipped


def start(text, scope, episodes):
    if not available():
        raise FileNotFoundError('未找到本机 B站字幕 CLI 或 skill 校验脚本。')
    url, requested = selection(text, scope, episodes)
    if cli_lock.locked():raise BlockingIOError('字幕旧调用正在运行，请稍后重试。')
    requested, skipped = skip_archived(url, requested)
    identifier=uuid4().hex
    with jobs_lock:
        for key,old in list(jobs.items()):
            if old.state not in task_runtime.ACTIVE and time.monotonic()-old.created_at>JOB_TTL:jobs.pop(key)
        if sum(old.state in task_runtime.ACTIVE for old in jobs.values())>=MAX_JOBS:raise BlockingIOError('字幕任务记录已满，请稍后重试。')
        job=Job(identifier,url,requested,CACHE_ROOT/identifier,skipped=skipped);jobs[identifier]=job
        task_runtime.trim_memory(jobs,keep=identifier)
    try:task_runtime.submit('subtitles',job,worker,lambda:task_runtime.save(CACHE_ROOT/'.tasks',job))
    except Exception:
        with jobs_lock:jobs.pop(identifier,None)
        raise
    return view(job)


def get(identifier):
    with jobs_lock:
        job = jobs.get(identifier)
        if job and job.state not in task_runtime.ACTIVE and time.monotonic()-job.created_at>JOB_TTL:
            jobs.pop(identifier,None);job=None
        if job is None:
            job=task_runtime.restore(CACHE_ROOT/'.tasks',identifier,Job,('directory',))
            job.files={k:Path(v) for k,v in job.files.items()};jobs[identifier]=job
        task_runtime.trim_memory(jobs,keep=identifier)
        return job


def view(job):
    with jobs_lock:
        return {**task_runtime.metadata(job), 'id': job.id, 'state': task_runtime.public_state(job), 'message': job.message, 'title': job.title,
                'results': job.results, 'skipped': job.skipped,
                'downloaded': sum(row['status'] == 'downloaded' for row in job.results),
                'existing': sum(row['status'] == 'existing' for row in job.results),
                'failed': sum(row['status'] == 'failed' for row in job.results)}


def download_file(identifier, token):
    job = get(identifier)
    path = job.files.get(token)
    if path is None:
        raise KeyError('未找到已校验的字幕文件。')
    resolved = path.resolve(strict=True)
    if resolved.is_relative_to(library.LIBRARY_ROOT.resolve()):
        project = library.owner(resolved)
        if project: return library.resource(project['id'], resolved.relative_to(project['directory']).as_posix())
    if not resolved.is_relative_to(job.directory.absolute()) or not resolved.is_relative_to(CACHE_ROOT.resolve()):
        raise KeyError('字幕文件不在受控目录中。')
    return resolved


def retry_failed(identifier):
    job=get(identifier)
    if job.state in task_runtime.ACTIVE:raise BlockingIOError('任务尚未完成。')
    completed={row['episode'] for row in job.results if row['status']!='failed'}
    failed=[number for number in (job.episodes or list(range(1,int(job.progress.get('total',0))+1)) or [r['episode'] for r in job.results]) if number not in completed]
    if not failed and job.state in {'failed','cancelled','interrupted','login_required'}:
        failed=job.episodes
    if not failed:
        if job.state=='completed':raise ValueError('没有失败分集需要重试。')
        return start(job.url,'all','')
    return start(job.url,'custom',','.join(map(str,failed)))
