"""Bounded, explicit-consent subtitle vector search; compatible local/remote embeddings API."""
import hashlib
import json
import math
import os
from uuid import uuid4
from pathlib import Path
from urllib.parse import urlsplit
from video_parser.core.paths import ROOT
from video_parser.services import ai_analysis, ai_settings, library

SETTINGS_PATH = ROOT / '.local/ai/embedding-settings.json'
INDEX_ROOT = ROOT / '.local/ai/embedding-index'
MAX_CHUNKS = 1024


def settings():
    try:
        if SETTINGS_PATH.is_symlink() or SETTINGS_PATH.stat().st_size > 10000:
            raise ValueError()
        data = json.loads(SETTINGS_PATH.read_text(encoding='utf-8'))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {'base_url': '', 'model': '', 'api_key': ''}


def public():
    data = settings()
    return {k: data.get(k, '') for k in ('base_url', 'model')} | {'key_saved': bool(data.get('api_key')), 'configured': ai_settings.configured(data)}


def save(base_url, model, api_key=None, clear_key=False):
    base_url, model = base_url.strip().rstrip('/'), model.strip()
    parts = urlsplit(base_url)
    if parts.scheme not in ('https', 'http') or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('请填写不含凭据、查询参数的 OpenAI 兼容接口地址。')
    if parts.scheme == 'http' and not ai_settings.is_local(base_url):
        raise ValueError('远程接口必须使用 HTTPS。')
    if not model:
        raise ValueError('请填写 Embedding 模型 ID。')
    previous = settings()
    key = previous.get('api_key', '') if previous.get('base_url') == base_url else ''
    if api_key:
        if any(ch.isspace() for ch in api_key):
            raise ValueError('密钥不能包含空格或换行。')
        key = api_key
    if clear_key:
        key = ''
    private_json(SETTINGS_PATH, {'base_url': base_url, 'model': model, 'api_key': key})
    return public()


def private_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError('设置或索引路径不安全，未保存。')
    temporary = path.with_name('.' + uuid4().hex + '.tmp')
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def signature(config):
    return hashlib.sha256((config['base_url'] + '\n' + config['model']).encode()).hexdigest()


def vector(values):
    if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= 65536:
        raise ValueError('Embedding 返回的向量维度无效。')
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
        raise ValueError('Embedding 返回了无效数值。')
    norm = math.sqrt(sum(value * value for value in values))
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError('Embedding 返回了空向量。')
    return [value / norm for value in values]


def embed(texts, config):
    result = []
    try:
        with ai_settings.client(config, timeout=120) as client:
            for offset in range(0, len(texts), 32):
                batch = texts[offset:offset + 32]
                rows = sorted(client.embeddings.create(model=config['model'], input=batch).data, key=lambda row: row.index)
                if [row.index for row in rows] != list(range(len(batch))):
                    raise ValueError('Embedding 返回数量不匹配。')
                result.extend(vector(row.embedding) for row in rows)
    except ValueError:
        raise
    except Exception:
        # Provider exceptions can contain authorization headers or submitted subtitles.
        raise ValueError('Embedding 调用失败，请检查地址、模型、密钥和网络；不会自动重试。') from None
    if len({len(row) for row in result}) != 1:
        raise ValueError('Embedding 返回维度不一致。')
    return result


def chunks(cues, resource):
    rows, body, start = [], [], 0
    for time, text in cues:
        if body and (time - start >= 45 or len(' '.join([*body, text])) > 800):
            rows.append({'resource': resource, 'time': start, 'text': ' '.join(body)})
            body = []
        # Very long cues split at bounded character lengths with the same source timestamp.
        for offset in range(0, len(text), 800):
            part = text[offset:offset + 800]
            if body and len(' '.join([*body, part])) > 800:
                rows.append({'resource': resource, 'time': start, 'text': ' '.join(body)})
                body = []
            if not body:
                start = time
            body.append(part)
    if body:
        rows.append({'resource': resource, 'time': start, 'text': ' '.join(body)})
    return rows


def fingerprints(project):
    result = {}
    for source in ai_analysis.transcript_sources(project):
        path = library.resource_from_project(project, source['resource'])
        result[source['resource']] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def index(project_id):
    project = library.get(project_id)
    config = settings()
    if not ai_settings.configured(config):
        raise ValueError('请先在设置中配置 Embedding 模型。')
    before = fingerprints(project)
    if not before:
        raise ValueError('当前视频没有可索引字幕，请先获取或生成字幕。')
    rows = []
    for resource in before:
        text = library.resource_from_project(project, resource).read_text(encoding='utf-8', errors='replace')
        rows.extend(chunks(ai_analysis.parse_cues(text), resource))
    if len(rows) > MAX_CHUNKS:
        raise ValueError('字幕超过单集 1024 片段预算，请减少字幕版本后重试。未发送模型请求。')
    vectors = embed([row['text'] for row in rows], config)
    if fingerprints(library.get(project_id)) != before:
        raise ValueError('字幕在索引期间发生变化，请重新建立索引。')
    private_json(INDEX_ROOT / (project['id'] + '.json'), {'signature': signature(config), 'sources': before,
        'dimension': len(vectors[0]), 'rows': [row | {'vector': v} for row, v in zip(rows, vectors)]})
    return {'count': len(rows), 'message': '当前视频字幕索引已建立。'}


def search(project_id, query, limit=8):
    project = library.get(project_id)
    config = settings()
    path = INDEX_ROOT / (project['id'] + '.json')
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 128 * 1024 * 1024:
        raise ValueError('请先为当前视频建立字幕索引。')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('signature') != signature(config):
        raise ValueError('Embedding 模型或接口已变化，请重建索引。')
    if data.get('sources') != fingerprints(project):
        raise ValueError('字幕已新增、修改或删除，请重建索引；不会返回过期内容。')
    q = embed([query], config)[0]
    if len(q) != data['dimension']:
        raise ValueError('Embedding 维度已变化，请重建索引。')
    ranked = sorted(((sum(a*b for a, b in zip(q, row['vector'])), row) for row in data['rows']), key=lambda item: item[0], reverse=True)
    return {'results': [{key: row[key] for key in ('text', 'time', 'resource')} | {'score': score, 'project_id': project_id,
        'title': project.get('episode_title') or project['title'], 'part': project.get('part')} for score, row in ranked[:limit]]}
