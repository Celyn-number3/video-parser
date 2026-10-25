"""Read-only result grouping. Content, provenance and recorded generation identify a result."""
from functools import lru_cache
from pathlib import Path
from collections import Counter, defaultdict
import hashlib,json,math,re
from video_parser.services import library


@lru_cache(maxsize=256)
def _job_metadata(path, modified, size):
    """Cache only small metadata, not private subtitle text or prompts."""
    try:
        record=json.loads(Path(path).read_text(encoding='utf-8'));job=record['job']
        if record.get('version')!=1 or job.get('state')!='completed' or job.get('id')!=Path(path).stem:return None
        created=job.get('created')
        if not isinstance(created,(int,float)) or not math.isfinite(created) or created<=0:return None
        files=job.get('files',{})
        return {'id':job['id'],'created':created,'project_id':job.get('project_id'),
                'files':[{'sha256':v.get('sha256'),'project_id':v.get('project_id'),'resource':v.get('relative')}
                         for v in files.values() if isinstance(v,dict)]}
    except (OSError,ValueError,KeyError,TypeError,AttributeError):return None


def _generations(project, rows):
    from video_parser.services import transcription
    matches=defaultdict(dict)
    directory=transcription.OUTPUT_ROOT/'.tasks'
    for path in directory.glob('*.json'):
        if not re.fullmatch(r'[a-f0-9]{32}',path.stem) or path.is_symlink():continue
        try:
            stat=path.stat()
            if stat.st_size>16*1024*1024:continue
            job=_job_metadata(str(path),stat.st_mtime_ns,stat.st_size)
        except OSError:continue
        if not job:continue
        for row in rows:
            if any(f['sha256'] and f['sha256']==row.get('sha256') and
                   (f['project_id'] or job['project_id'])==project['id'] and
                   f['resource']==row['resource'] for f in job['files']):
                matches[row['resource']][job['id']]=job
    # Multiple matching generations do not establish one reliable creation date.
    return {k:next(iter(v.values())) for k,v in matches.items() if len(v)==1}


def _body_hash(path):
    if path.suffix.lower() not in ('.srt','.txt'):return None
    raw=path.read_text(encoding='utf-8-sig').replace('\r\n','\n')
    if path.suffix.lower()=='.srt':
        body=[]
        for block in re.split(r'\n\s*\n',raw.strip()):
            lines=block.splitlines();offset=1 if lines and lines[0].strip().isdigit() else 0
            if len(lines)<=offset+1 or not re.fullmatch(r'\d{2,}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2,}:\d{2}:\d{2}[,.]\d{3}',lines[offset].strip()):return None
            body.extend(lines[offset+1:])
        raw='\n'.join(body)
    text=raw.strip()
    return hashlib.sha256(text.encode('utf-8')).hexdigest() if text else None


def annotate(project, rows):
    """Keep every file row/API resource; add a stable result ID and actual task date."""
    generations=_generations(project,rows);buckets=defaultdict(list)
    for row in rows:
        info=project['resources'][row['resource']];path=library.resource_from_project(project,row['resource'])
        generation=generations.get(row['resource'])
        try: body=_body_hash(path)
        except (OSError, UnicodeError): body=None
        row.update(format=path.suffix.lstrip('.').upper(),generated_at=generation['created'] if generation else None)
        source=row.get('source_resource') or info.get('source_sha256')
        # Unattributed translations cannot be confidently paired by text alone.
        if not body or (row.get('kind')=='translation' and not source):key=('file',row['resource'])
        else:key=(row.get('kind'),row.get('language'),info.get('video_resource'),source,body,generation['id'] if generation else None)
        buckets[key].append(row)
    for key,items in buckets.items():
        ambiguous=any(count>1 for count in Counter(r['format'] for r in items).values())
        for row in items:
            signature=(key,row['resource']) if ambiguous else key
            row['version_id']=hashlib.sha256(json.dumps(signature,ensure_ascii=False).encode()).hexdigest()[:24]
    return rows
