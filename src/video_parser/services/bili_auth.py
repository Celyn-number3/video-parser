"""Local-only Bilibili QR login. Never expose upstream keys, cookies or redirect URLs."""
import base64
import json
import os
from pathlib import Path
import re
from threading import RLock
import time
from urllib.parse import urlsplit
from uuid import uuid4

import qrcode
import qrcode.image.svg
import requests

BASE = 'https://passport.bilibili.com/x/passport-login/web/qrcode/'
NAV = 'https://api.bilibili.com/x/web-interface/nav'
lock = RLock()
sessions = {}


def cookie_path():
    from video_parser.services import subtitles
    if subtitles.TOOL_ROOT == subtitles.BUNDLED_ROOT:
        return subtitles.videos.ROOT / '.local/credentials/bilibili-cookies.json'
    return subtitles.TOOL_ROOT / 'b站_cookies.json'


def client():
    s = requests.Session()
    s.trust_env = False
    s.headers.update({'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.bilibili.com/'})
    return s


def api(s, url, **kwargs):
    try:
        r = s.get(url, timeout=(5, 10), allow_redirects=False, **kwargs)
        if r.status_code != 200 or len(r.content) > 100000:
            raise ValueError()
        data = r.json()
        if url == NAV and isinstance(data, dict) and data.get('code') == -101:
            return {'isLogin': False}
        if not isinstance(data, dict) or data.get('code') != 0 or not isinstance(data.get('data'), dict):
            raise ValueError()
        return data['data']
    except (requests.RequestException, ValueError, TypeError):
        raise RuntimeError('无法连接 B站登录服务，或平台暂时限制访问；请稍后重试。') from None


def valid_domain(domain):
    return isinstance(domain, str) and domain.lstrip('.') in {'bilibili.com', 'passport.bilibili.com'}


def status():
    p = cookie_path()
    if not p.is_file() or p.is_symlink():
        return {'authenticated': False}
    try:
        if p.stat().st_size > 1000000:
            return {'authenticated': False}
        cookies = json.loads(p.read_text(encoding='utf-8'))
        if not isinstance(cookies, list):
            return {'authenticated': False}
        with client() as s:
            for c in cookies:
                if isinstance(c, dict) and valid_domain(c.get('domain')) and isinstance(c.get('name'), str) and isinstance(c.get('value'), str):
                    s.cookies.set(c['name'], c['value'], domain=c['domain'], path=c.get('path', '/'))
            if not any(c.name == 'SESSDATA' and c.value for c in s.cookies):
                return {'authenticated': False}
            return {'authenticated': api(s, NAV).get('isLogin') is True}
    except (OSError, ValueError, TypeError, KeyError):
        return {'authenticated': False}


def persist(s):
    cookies = [{'name': c.name, 'value': c.value, 'domain': c.domain, 'path': c.path or '/',
                'expires': c.expires if c.expires is not None else -1,
                'secure': bool(c.secure), 'httpOnly': c.has_nonstandard_attr('HttpOnly'), 'sameSite': 'Lax'}
               for c in s.cookies if valid_domain(c.domain)]
    if not any(c['name'] == 'SESSDATA' and c['value'] for c in cookies):
        raise RuntimeError('B站未返回有效登录凭据，请刷新二维码后重试。')
    if api(s, NAV).get('isLogin') is not True:
        raise RuntimeError('登录态未通过 B站验证，请重新扫码。')
    p = cookie_path()
    if p.is_symlink():
        raise RuntimeError('登录态文件路径不安全，未保存。')
    # Both target and temporary names match the external repository's *cookie*.json ignore rule.
    p.parent.mkdir(parents=True, exist_ok=True)
    temporary = p.with_name('.' + uuid4().hex + '-cookies.json')
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(cookies, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, p)
    except OSError:
        raise RuntimeError('无法安全保存本机登录态，请检查工具目录写入权限。') from None
    finally:
        temporary.unlink(missing_ok=True)


def discard(identifier):
    with lock:
        row = sessions.pop(identifier, None)
        if row:
            row['client'].close()
    return {'state': 'cancelled'}


def create():
    with lock:
        now = time.monotonic()
        for identifier, row in list(sessions.items()):
            if now >= row['expires']:
                discard(identifier)
        if len(sessions) >= 4:
            raise RuntimeError('正在等待扫码的窗口过多，请关闭旧窗口或等待二维码过期。')
        s = client()
        try:
            data = api(s, BASE + 'generate')
            url, key = data.get('url'), data.get('qrcode_key')
            parsed = urlsplit(url) if isinstance(url, str) else None
            if (not parsed or parsed.scheme != 'https' or parsed.netloc not in {'passport.bilibili.com', 'account.bilibili.com'}
                    or not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9]{32}', key)):
                raise RuntimeError('B站返回的二维码格式异常，请稍后重试。')
            image = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, border=4).to_string()
            identifier = uuid4().hex
            sessions[identifier] = {'client': s, 'key': key, 'expires': now + 180,
                                    'last_poll': -float('inf'), 'state': 'waiting'}
            return {'id': identifier, 'state': 'waiting', 'expires_in': 180,
                    'image': 'data:image/svg+xml;base64,' + base64.b64encode(image).decode('ascii')}
        except Exception:
            s.close()
            raise


def poll(identifier):
    with lock:
        row = sessions.get(identifier)
        if not row:
            return {'state': 'expired'}
        now = time.monotonic()
        if now >= row['expires']:
            discard(identifier)
            return {'state': 'expired'}
        if row['state'] == 'authenticated':
            return {'state': 'authenticated'}
        if now - row['last_poll'] < 2:
            return {'state': row['state']}
        row['last_poll'] = now
        data = api(row['client'], BASE + 'poll', params={'qrcode_key': row['key']})
        code = data.get('code')
        if code == 0:
            persist(row['client'])
            row['state'] = 'authenticated'
            row['key'] = ''
            row['client'].close()
        elif code == 86038:
            discard(identifier)
            return {'state': 'expired'}
        elif code in (86101, 86090):
            row['state'] = 'waiting' if code == 86101 else 'scanned'
        else:
            raise RuntimeError('B站登录状态异常，请刷新二维码后重试。')
        return {'state': row['state']}
