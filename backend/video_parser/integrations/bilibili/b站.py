import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright
if __package__:
    from . import checker
    from .events import emit
else:
    # Run as a script. The portable build's embedded Python (._pth) does not put the script folder on sys.path.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import checker
    from events import emit

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
from video_parser.core.browser import launch_chromium
from video_parser.core.paths import CACHE_DIR
os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(PROJECT_ROOT / 'runtimes/browsers')
COOKIE_FILE = PROJECT_ROOT / ".local/credentials/bilibili-cookies.json"
DOWNLOAD_DIR = CACHE_DIR / "bilibili/subtitle_download"
VIDEO_URL = sys.argv[1] if len(sys.argv) > 1 else "https://www.bilibili.com/video/BV1Ju4y1o7q8/"
REQUEST_TIMEOUT = (10, 30)


def parse_episode_selection(total: int) -> list[int] | None:
    args = [a for a in sys.argv[1:] if not a.startswith("http")]

    if "--all" in args:
        return list(range(1, total + 1))

    ep_arg = None
    for i, a in enumerate(args):
        if a in ("--ep", "-e"):
            ep_arg = args[i + 1] if i + 1 < len(args) else None
            break

    if not ep_arg:
        return None

    selected: set[int] = set()
    for part in ep_arg.split(","):
        part = part.strip()
        if not part:
            raise ValueError("选集参数包含空项")
        if "-" in part:
            a, b = part.split("-", 1)
            lo, hi = int(a.strip()), int(b.strip())
            if lo < 1 or hi < 1 or lo > hi:
                raise ValueError(f"无效范围: {part}")
            selected.update(range(lo, hi + 1))
        else:
            number = int(part)
            if number < 1:
                raise ValueError(f"无效集数: {part}")
            selected.add(number)

    return sorted(s for s in selected if 1 <= s <= total)


def save_cookies(context):
    cookies = context.cookies()
    # 去重，保留每个 name 最后一个（即最新的）
    seen = {}
    for c in cookies:
        seen[(c["name"], c.get("domain", ""))] = c
    COOKIE_FILE.write_text(json.dumps(list(seen.values()), ensure_ascii=False, indent=2))
    print(f"cookies saved -> {COOKIE_FILE}")


def load_cookies(context):
    if COOKIE_FILE.exists():
        cookies = json.loads(COOKIE_FILE.read_text())
        context.add_cookies(cookies)
        return True
    return False


def _sanitize(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = name.strip().replace(" ", "_")
    return name[:100] or "subtitle"


def request_subtitle(subtitle_url: str) -> dict | None:
    if not subtitle_url.startswith("http"):
        subtitle_url = f"https:{subtitle_url}"
    resp = requests.get(subtitle_url, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.bilibili.com/",
    }, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    raw = resp.content
    for enc in ["utf-8", "gbk", "gb18030"]:
        try:
            text = raw.decode(enc)
            return json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return None


def save_subtitle_files(data: dict, base_name: str, out_dir: Path = Path(".")):
    json_dir = out_dir / "_json"
    srt_dir = out_dir / "_srt"
    md_dir = out_dir / "_md"
    json_dir.mkdir(parents=True, exist_ok=True)
    srt_dir.mkdir(parents=True, exist_ok=True)
    md_dir.mkdir(parents=True, exist_ok=True)

    json_path = json_dir / f"{base_name}.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  json -> {json_path}")

    body = data.get("body", [])
    srt_lines = []
    for i, item in enumerate(body, 1):
        start = _to_srt_time(item["from"])
        end = _to_srt_time(item["to"])
        content = item["content"]
        srt_lines.append(f"{i}\n{start} --> {end}\n{content}\n")
    srt_path = srt_dir / f"{base_name}.srt"
    srt_path.write_text("\n".join(srt_lines), encoding="utf-8")
    print(f"  srt  -> {srt_path}  ({len(body)} lines)")

    md_path = md_dir / f"{base_name}.md"
    md_path.write_text("，".join(item["content"] for item in body), encoding="utf-8")
    print(f"  md   -> {md_path}")


def get_subtitle_url_api(bvid: str, cid: int) -> str | None:
    """通过 API 获取字幕 URL（无需浏览器），需要已保存的 cookies"""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com/",
    })
    # 去重加载 cookies，.biligame.com 域名的仅在无 .bilibili.com 时使用
    if COOKIE_FILE.exists():
        raw = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
        used_names = set()
        # 优先加 .bilibili.com 域的
        for c in raw:
            key = (c["name"], c.get("domain", ""))
            if key in used_names:
                continue
            if "biligame" in c.get("domain", ""):
                continue  # 跳过 game 域 cookies
            session.cookies.set(c["name"], c["value"], domain=c.get("domain", ".bilibili.com"))
            used_names.add(key)

    resp = session.get(f"https://api.bilibili.com/x/player/v2?bvid={bvid}&cid={cid}", timeout=REQUEST_TIMEOUT)
    if resp.status_code != 200:
        return None
    data = resp.json()
    if data.get("code") != 0:
        return None
    subtitles = data.get("data", {}).get("subtitle", {}).get("subtitles", [])
    if not subtitles:
        return None
    sub_url = subtitles[0].get("subtitle_url", "")
    if not sub_url:
        return None
    if not sub_url.startswith("http"):
        sub_url = f"https:{sub_url}"
    return sub_url


def _to_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _has_session_cookies(context) -> bool:
    for c in context.cookies():
        if c["name"] == "SESSDATA" and c["value"]:
            return True
    return False


def get_episode_subtitle(page, ep_num: int, video_url: str) -> str | None:
    """单集：设监听 → goto → 等 INIT_STATE → UI 点击 → 等网络请求 → 返回字幕 URL"""
    subtitle_url = None

    def on_request(request):
        nonlocal subtitle_url
        if "aisubtitle.hdslb.com" in request.url or "subtitle.bilibili.com" in request.url:
            subtitle_url = request.url

    page.on("request", on_request)
    page.goto(f"{video_url.split('?')[0]}?p={ep_num}", wait_until="domcontentloaded")
    page.wait_for_function("() => !!window.__INITIAL_STATE__", timeout=15000)

    if not subtitle_url:
        try:
            player = page.locator(".bpx-player-video-wrap").first
            player.wait_for(state="attached", timeout=10000)
            player.hover(timeout=3000)
            sub_btn = page.locator(".bpx-player-ctrl-subtitle").first
            sub_btn.wait_for(state="visible", timeout=10000)
            sub_btn.click()
            zh_item = page.locator(".bpx-player-ctrl-subtitle-language-item").first
            zh_item.wait_for(state="visible", timeout=3000)
            zh_item.click()
            # 等网络请求出现（最多 5 秒）
            for _ in range(50):
                if subtitle_url:
                    break
                page.wait_for_timeout(100)
        except Exception as e:
            print(f"  subtitle click error: {e}")

    page.remove_listener("request", on_request)
    return subtitle_url


def _click_subtitle_in_player(page) -> str | None:
    """UI 点击拿字幕（当前页，不 goto）"""
    subtitle_url = None
    def on_request(request):
        nonlocal subtitle_url
        if "aisubtitle.hdslb.com" in request.url or "subtitle.bilibili.com" in request.url:
            subtitle_url = request.url
    page.on("request", on_request)
    try:
        player = page.locator(".bpx-player-video-wrap").first
        player.wait_for(state="attached", timeout=10000)
        player.hover(timeout=3000)
        sub_btn = page.locator(".bpx-player-ctrl-subtitle").first
        sub_btn.wait_for(state="visible", timeout=10000)
        sub_btn.click()
        zh_item = page.locator(".bpx-player-ctrl-subtitle-language-item").first
        zh_item.wait_for(state="visible", timeout=3000)
        zh_item.click()
        for _ in range(50):
            if subtitle_url:
                break
            page.wait_for_timeout(100)
    except Exception as e:
        print(f"  subtitle click error: {e}")
    page.remove_listener("request", on_request)
    return subtitle_url


def run():
    with sync_playwright() as p:
        browser = launch_chromium(p, headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 720})
        page = context.new_page()

        # --- login ---
        loaded = load_cookies(context)
        if loaded and _has_session_cookies(context):
            print("cookies loaded with SESSDATA, skip login")
        else:
            print('缺少登录 Cookie，请在工作台扫码登录')
            browser.close()
            return

        # --- load page & get episode list ---
        page.goto(VIDEO_URL, wait_until="domcontentloaded")
        page.wait_for_function("() => !!window.__INITIAL_STATE__", timeout=15000)

        init = page.evaluate("() => window.__INITIAL_STATE__")
        if not init:
            print("no __INITIAL_STATE__, cannot continue")
            return

        series_title = init.get("videoData", {}).get("title", "")
        bvid = init.get("videoData", {}).get("bvid", "")
        print(f"\nseries: {series_title}  ({bvid})")

        out_dir = DOWNLOAD_DIR / _sanitize(series_title)
        out_dir.mkdir(parents=True, exist_ok=True)

        pages = init.get("videoData", {}).get("pages", [])
        emit("target", title=series_title, bvid=bvid, total=len(pages) or 1, single=not bool(pages))
        if not pages:
            cid = init.get("cid", 0)
            print(f"single video, cid={cid}")
            base = _sanitize(series_title)
            json_path = out_dir / "_json" / f"{base}.json"
            if checker.check(json_path)["ok"]:
                emit("episode", episode=1, status="existing")
                print("exists, skip")
                return
            t0 = time.time()
            url = _click_subtitle_in_player(page)
            if url:
                data = request_subtitle(url)
                if data:
                    save_subtitle_files(data, base, out_dir)
            else:
                print("no subtitle for this video")
            emit("episode", episode=1, status="downloaded" if checker.check(json_path)["ok"] else "failed")
            print(f"  done in {time.time()-t0:.1f}s")
            return

        # 多集 ---
        try:
            episode_selection = parse_episode_selection(len(pages))
        except (ValueError, IndexError) as exc:
            print(f"invalid episode selection: {exc}")
            return
        pages_by_num = {p["page"]: p for p in pages}

        if episode_selection is None:
            print("use --all or --ep 1-5,8 to select episodes")
            print("only downloading current episode...")
            target_list = [pages[init.get("p", 1) - 1]]
        else:
            target_list = [pages_by_num[i] for i in episode_selection if i in pages_by_num]
            print(f"selected {len(target_list)}/{len(pages)} episodes: {episode_selection}")

        ep_times = []

        for completed, ep in enumerate(target_list):
            emit("progress", done=completed, total=len(target_list))
            ep_num = ep["page"]
            ep_name = ep.get("part", f"P{ep_num}")
            clean_name = ep_name
            _m = re.match(r'^(\d+)\s+(.*)', clean_name or '')
            if _m:
                clean_name = _m.group(2)
            base = _sanitize(f"P{str(ep_num).zfill(2)} {clean_name}")
            json_path = out_dir / "_json" / f"{base}.json"
            if checker.check(json_path)["ok"]:
                emit("episode", episode=ep_num, status="existing")
                print(f"\n[P{ep_num}] exists, skip")
                continue

            print(f"\n[P{ep_num}] {ep_name}  cid={ep['cid']}")
            t0 = time.time()

            subtitle_url = get_episode_subtitle(page, ep_num, VIDEO_URL)

            if subtitle_url:
                data = request_subtitle(subtitle_url)
                if data and data.get("body"):
                    save_subtitle_files(data, base, out_dir)
                else:
                    print(f"  no subtitle content for P{ep_num}")
            else:
                print(f"  no subtitle URL for P{ep_num}")

            emit("episode", episode=ep_num, status="downloaded" if checker.check(json_path)["ok"] else "failed")
            elapsed = time.time() - t0
            ep_times.append(elapsed)
            print(f"  [{elapsed:.1f}s]")

        emit("progress", done=len(target_list), total=len(target_list))
        context.close()
        browser.close()

        total = sum(ep_times)
        print(f"\n--- summary ---")
        if ep_times:
            print(f"total: {total:.1f}s for {len(ep_times)} episodes")
            print(f"avg:   {total/len(ep_times):.1f}s per episode")
        else:
            print("all episodes skipped (already downloaded)")


if __name__ == "__main__":
    run()
