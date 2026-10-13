"""Read-only reuse of the subtitle tool's login, scoped to Bilibili HTTPS video pages."""
import json
import math
import os
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlsplit

import requests
from video_parser.core.paths import ROOT

DOMAINS = {'bilibili.com', '.bilibili.com', 'www.bilibili.com', '.www.bilibili.com'}
COOKIE_NAME = re.compile(r'[A-Za-z0-9_\-]{1,100}')


def cookie_path():
    configured = os.getenv('BILI_SUBTITLE_ROOT')
    bundled = ROOT / 'src/video_parser/integrations/bilibili'
    if configured and Path(configured) != bundled:
        return Path(configured) / 'b站_cookies.json'
    return ROOT / '.local/credentials/bilibili-cookies.json'


def load_cookies():
    jar = requests.cookies.RequestsCookieJar()
    path = cookie_path()
    try:
        if not path.is_file(): return jar, 'missing'
        if path.stat().st_size > 4 * 1024 * 1024: return jar, 'invalid'
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, list) or len(data) > 512: return jar, 'invalid'
    except (OSError, UnicodeError, ValueError):
        return jar, 'invalid'
    expired_session = False
    for item in data:
        if not isinstance(item, dict) or item.get('domain') not in DOMAINS: continue
        name, value = item.get('name'), item.get('value')
        if not isinstance(name, str) or not COOKIE_NAME.fullmatch(name): continue
        if not isinstance(value, str) or not value or len(value) > 8192 or any(char in value for char in '\r\n;\x00'): continue
        try:
            expires = float(item.get('expires', -1))
            if not math.isfinite(expires): continue
        except (ValueError, TypeError): continue
        if expires >= 0 and expires <= time.time():
            expired_session |= name == 'SESSDATA'
            continue
        # Never inherit an unrestricted or third-party exported domain, nor use cookies over HTTP.
        jar.set(name, value, domain='www.bilibili.com', path='/', secure=True,
                expires=int(expires) if expires >= 0 else None)
    if not any(cookie.name == 'SESSDATA' for cookie in jar):
        return requests.cookies.RequestsCookieJar(), 'expired' if expired_session else 'missing_session'
    return jar, 'reused_unverified'


def allowed_page(url):
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == 'https' and parsed.hostname == 'www.bilibili.com'
                and parsed.port in (None, 443) and not parsed.username and not parsed.password
                and parsed.path.startswith('/video/'))
    except ValueError:
        return False


def fetch_page(url, headers):
    if not allowed_page(url): raise ValueError('B站登录态仅用于官方 HTTPS 视频页。')
    cookies, status = load_cookies()
    # Request exceptions can contain credentials or signed URLs: callers get a fixed safe error instead.
    try:
        with requests.Session() as client:
            for _ in range(4):
                response = client.get(url, headers=headers, cookies=cookies, timeout=(10, 30), allow_redirects=False)
                if response.status_code in (301, 302, 303, 307, 308):
                    redirected = urljoin(url, response.headers.get('Location', ''))
                    if not allowed_page(redirected):
                        raise RuntimeError('Unsafe Bilibili redirect')
                    url = redirected
                    continue
                response.raise_for_status()
                return response.text, status
    except Exception:
        raise RuntimeError('B站页面读取失败，请检查网络或在原字幕工具重新登录后重试。') from None
    raise RuntimeError('B站视频页跳转过多，请使用完整视频链接重试。')
