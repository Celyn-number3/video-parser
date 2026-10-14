"""Canonical single-video YouTube links; no playlists, custom hosts or credentials."""
import re
from urllib.parse import parse_qs, urlsplit


def canonical_url(url):
    parsed = urlsplit(url)
    host = (parsed.hostname or '').lower()
    if parsed.scheme not in {'http', 'https'} or parsed.username or parsed.password or parsed.port not in (None, 80, 443):
        raise ValueError('YouTube 链接不能包含认证信息或自定义端口。')
    if host not in {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'}:
        raise ValueError('不支持的 YouTube 域名。')
    parts = parsed.path.strip('/').split('/')
    if host == 'youtu.be' and len(parts) == 1:
        identifier = parts[0]
    elif parsed.path.rstrip('/') == '/watch':
        values = parse_qs(parsed.query).get('v', [])
        identifier = values[0] if len(values) == 1 else ''
    elif len(parts) == 2 and parts[0] in {'shorts', 'embed', 'live'}:
        identifier = parts[1]
    else:
        identifier = ''
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', identifier):
        raise ValueError('请提供单个 YouTube 视频链接，不支持播放列表或频道。')
    return f'https://www.youtube.com/watch?v={identifier}'
