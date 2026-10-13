"""Read the requested public video's already-rendered data in an isolated Chromium.

No personal profile, Cookie export, third-party parser, CAPTCHA solving or auth bypass.
The browser/SSR/DOM fallback approach is also used by the open-source projects linked
in README; this implementation uses only Playwright and the page's current data.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import math
import re
from threading import Lock
from urllib.parse import urlparse

_browser_lock = Lock()


class BrowserParseError(RuntimeError):
    pass


def extraction_script(identifier):
    if not re.fullmatch(r'\d{1,25}', str(identifier)):
        raise BrowserParseError('抖音视频编号无效。')
    # React data is used only when the object's video ID exactly matches the request.
    return r"""(() => {
      const expected = IDENTIFIER;
      let found = null, remaining = 12000;
      const seen = new WeakSet();
      function walk(value, depth = 0) {
        if (found || !value || typeof value !== 'object' || depth > 6 || remaining-- <= 0 || seen.has(value)) return;
        seen.add(value);
        const id = String(value.awemeId || value.aweme_id || '');
        if (id === expected && value.video && typeof value.desc === 'string' && value.desc.trim()) {
          found = value; return;
        }
        for (const [key, item] of Object.entries(value)) {
          if (!['return', 'child', 'sibling', 'alternate', '_owner', 'stateNode'].includes(key)) walk(item, depth + 1);
        }
      }
      for (const id of ['RENDER_DATA', '__NEXT_DATA__']) {
        const tag = document.getElementById(id);
        if (tag) { try { walk(JSON.parse(decodeURIComponent(tag.textContent))); } catch {} }
      }
      for (const video of document.querySelectorAll('video')) {
        let element = video;
        for (let i = 0; i < 6 && element && !found; i++, element = element.parentElement) {
          const key = Object.keys(element).find(k => k.startsWith('__reactFiber$'));
          let fiber = key ? element[key] : null;
          for (let j = 0; j < 25 && fiber && !found; j++, fiber = fiber.return) walk(fiber.memoizedProps);
        }
      }
      if (!found) return null;
      const video = found.video;
      const play = video.playAddr || video.play_addr?.url_list || [];
      const covers = video.originCoverUrlList || video.coverUrlList || video.cover_original_scale?.url_list || video.cover?.url_list || [];
      return {id: String(found.awemeId || found.aweme_id), title: found.desc,
        duration_ms: video.duration, width: video.width, height: video.height,
        video_urls: Array.isArray(play) ? play.map(item => typeof item === 'string' ? item : item.src).filter(Boolean) : [],
        cover_urls: Array.isArray(covers) ? covers : [], user_agent: navigator.userAgent};
    })()""".replace('IDENTIFIER', json.dumps(str(identifier)))


def _urls(values, domains):
    if not isinstance(values, list): return []
    result = []
    for value in values:
        if not isinstance(value, str): continue
        try:
            parsed = urlparse(value)
            host = (parsed.hostname or '').lower()
            if (parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443)
                    or not any(host == domain or host.endswith('.' + domain) for domain in domains)):
                continue
        except ValueError:
            continue
        if value not in result: result.append(value)
    return result


def normalize(payload, identifier):
    if (not isinstance(payload, dict) or payload.get('id') != str(identifier)
            or not isinstance(payload.get('title'), str) or not payload['title'].strip()):
        raise BrowserParseError('浏览器未取得指定抖音视频的信息；不会下载推荐流中的其他视频。')
    duration = payload.get('duration_ms')
    if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
        raise BrowserParseError('抖音视频时长无效，未取得可用媒体。')
    urls = _urls(payload.get('video_urls'), ('douyinvod.com', 'douyin.com', 'amemv.com'))
    covers = _urls(payload.get('cover_urls'), ('douyinpic.com', 'byteimg.com', 'douyin.com', 'bytetos.com', 'pstatp.com'))
    if not urls:
        raise BrowserParseError('抖音页面未提供可信的视频地址，当前未下载视频。')
    return {'aweme_detail': {'aweme_id': str(identifier), 'desc': payload['title'].strip(),
             'video': {'duration': duration, 'width': payload.get('width'), 'height': payload.get('height'),
                       'play_addr': {'url_list': urls}, 'cover_original_scale': {'url_list': covers}}},
            '_browser_user_agent': payload.get('user_agent') if isinstance(payload.get('user_agent'), str) else ''}


def _resolve(identifier, kind):
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout
    except ImportError:
        raise BrowserParseError('抖音浏览器解析需要 Playwright，请安装项目 requirements.txt 并执行 python -m playwright install chromium。') from None
    browser = None
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True, timeout=15000)
            context = browser.new_context(viewport={'width': 1280, 'height': 800}, locale='zh-CN')
            page = context.new_page()
            page.goto(f'https://www.douyin.com/{kind}/{identifier}', wait_until='domcontentloaded', timeout=30000)
            handle = page.wait_for_function(extraction_script(identifier), timeout=25000)
            payload = handle.json_value()
            handle.dispose()
            page.evaluate("document.querySelectorAll('video,audio').forEach(v=>{v.pause();v.muted=true})")
            return normalize(payload, identifier)
        except BrowserParseError:
            raise
        except BrowserTimeout:
            raise BrowserParseError('抖音页面未能加载指定视频，可能需要登录、验证或内容不可访问；未尝试绕过限制。') from None
        except Exception:
            raise BrowserParseError('抖音浏览器解析未能启动或运行，请检查 Playwright Chromium 和网络。') from None
        finally:
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass  # A crashed browser must not hide the original parsing error.


def resolve_in_browser(identifier, kind='video'):
    if kind not in ('video', 'note') or not re.fullmatch(r'\d{1,25}', str(identifier)):
        raise BrowserParseError('抖音视频编号或类型无效。')
    if not _browser_lock.acquire(timeout=60):
        raise BrowserParseError('已有抖音浏览器解析任务正在处理，请稍后重试。')
    try:
        # Legacy async API callers and sync CLI callers share the same safe worker path.
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix='douyin-browser') as executor:
            return executor.submit(_resolve, str(identifier), kind).result(timeout=80)
    finally:
        _browser_lock.release()
