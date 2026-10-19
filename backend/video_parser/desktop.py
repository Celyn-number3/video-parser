"""Desktop launcher for the portable Windows build.

Starts the local server (127.0.0.1 only) and shows it in its own window via pywebview / Edge WebView2,
falling back to the default browser. Closing the window stops the server.

    pythonw.exe -m video_parser.desktop            normal start
    python.exe  -m video_parser.desktop --check    start, verify /health, /config and the built frontend, then exit
"""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = ROOT / '.local' / 'work' / 'logs'
LOG_FILE = LOG_DIR / 'launcher.log'
TITLE = 'Video Parser'
PORTS = range(15001, 15021)
CREATE_NO_WINDOW, DETACHED_PROCESS, CREATE_NEW_CONSOLE = 0x08000000, 0x00000008, 0x00000010
# Local health checks must never go through a system or environment proxy.
LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def ensure_utf8_mode():
    """The backend expects -X utf8 (as start-web.ps1 does); the embedded build ignores PYTHONUTF8."""
    if sys.flags.utf8_mode:
        return
    flags = CREATE_NO_WINDOW if os.name == 'nt' and Path(sys.executable).name.lower() == 'python.exe' and '--check' not in sys.argv else 0
    raise SystemExit(subprocess.call([sys.executable, '-X', 'utf8', '-m', 'video_parser.desktop', *sys.argv[1:]],
                                     cwd=ROOT, creationflags=flags))


def redirect_output():
    """pythonw has no console: uvicorn and print() need real streams, so everything goes to a log file."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if LOG_FILE.is_file() and LOG_FILE.stat().st_size > 5 * 1024 * 1024:
        LOG_FILE.replace(LOG_FILE.with_suffix('.log.1'))
    stream = open(LOG_FILE, 'a', encoding='utf-8', buffering=1)
    sys.stdout = sys.stderr = stream
    print(f'\n==== {time.strftime("%Y-%m-%d %H:%M:%S")} start {sys.executable}')


def hide_child_consoles():
    """A windowless parent would give every ffmpeg / worker / yt-dlp child its own black console window."""
    if os.name != 'nt':
        return
    original = subprocess.Popen.__init__

    def init(self, *args, **kwargs):
        flags = kwargs.get('creationflags', 0) or 0
        if not flags & (DETACHED_PROCESS | CREATE_NEW_CONSOLE):
            kwargs['creationflags'] = flags | CREATE_NO_WINDOW
        original(self, *args, **kwargs)

    subprocess.Popen.__init__ = init
    # Workers are started with sys.executable; the console interpreter keeps their pipes reliable.
    console = Path(sys.executable).with_name('python.exe')
    if Path(sys.executable).name.lower() == 'pythonw.exe' and console.is_file():
        sys.executable = str(console)


def get_json(url, timeout=2.0):
    with LOCAL.open(url, timeout=timeout) as response:
        return json.load(response)


def is_our_server(port):
    """True only for a Video Parser server started from this same install folder (not a dev copy or another version)."""
    from video_parser.core.paths import instance_id
    try:
        health = get_json(f'http://127.0.0.1:{port}/health', 1.0)
        if health.get('status') != 'healthy' or health.get('instance') != instance_id():
            return False
        config = get_json(f'http://127.0.0.1:{port}/api/workspace/config', 3.0)
        return 'transcription_ready' in config
    except Exception:
        return False


def port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


def choose_port():
    """Return (port, already_running). Reuse this install's running server; never stop other programs."""
    for port in PORTS:
        if not port_free(port) and is_our_server(port):
            return port, True
    for port in PORTS:
        if port_free(port):
            return port, False
    raise RuntimeError(f'端口 {PORTS[0]}–{PORTS[-1]} 都被占用，无法启动。')


class Server:
    def __init__(self, port):
        import uvicorn
        self.port = port
        config = uvicorn.Config('video_parser.web.app:app', host='127.0.0.1', port=port,
                                proxy_headers=False, use_colors=False, log_level='info')
        self.server = uvicorn.Server(config)
        self.error = None
        self.thread = threading.Thread(target=self._run, name='uvicorn', daemon=True)

    def _run(self):
        try:
            self.server.run()
        except BaseException as error:  # reported in the window instead of vanishing silently
            self.error = error
            raise

    def start(self):
        self.thread.start()

    def wait_ready(self, timeout=90):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.error or not self.thread.is_alive():
                return False
            if is_our_server(self.port):
                return True
            time.sleep(0.3)
        return False

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=15)


def page(message, detail=''):
    return ('<!doctype html><meta charset="utf-8"><body style="font:15px system-ui,\'Microsoft YaHei\';'
            'display:grid;place-items:center;height:96vh;margin:0;color:#222">'
            f'<div style="text-align:center"><p style="font-size:18px">{message}</p>'
            f'<p style="color:#777;font-size:13px">{detail}</p></div></body>')


def show(url, server):
    try:
        import webview
    except ImportError:
        webview = None
    if webview is None:
        import webbrowser
        print('pywebview unavailable; opening the default browser')
        webbrowser.open(url)
        if server:
            server.thread.join()
        return

    # The workspace has "下载 SRT / 导出 Markdown" buttons; pywebview blocks downloads unless allowed.
    webview.settings['ALLOW_DOWNLOADS'] = True
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = True
    window = webview.create_window(TITLE, html=page('正在启动 Video Parser…'), width=1440, height=960,
                                   min_size=(1024, 680), text_select=True, zoomable=True)

    def navigate():
        if server and not server.wait_ready():
            window.load_html(page('启动失败', f'详细信息见 {LOG_FILE}'))
            return
        window.load_url(url)

    storage = ROOT / '.local' / 'webview'
    storage.mkdir(parents=True, exist_ok=True)
    webview.start(navigate, private_mode=False, storage_path=str(storage))


def check():
    """Build smoke test: start on a free port, verify the API and the built frontend, then stop."""
    port = next(port for port in PORTS if port_free(port))
    server = Server(port)
    server.start()
    ok = server.wait_ready()
    result = {'port': port, 'ready': ok}
    if ok:
        config = get_json(f'http://127.0.0.1:{port}/api/workspace/config', 10)
        with LOCAL.open(f'http://127.0.0.1:{port}/', timeout=10) as response:
            index = response.read().decode('utf-8', 'replace')
        result.update({key: config.get(key) for key in ('version', 'media_ready', 'subtitles_ready', 'transcription_ready')},
                      frontend='<div id="root"' in index, python=sys.version.split()[0],
                      ffmpeg=shutil.which('ffmpeg'), executable=sys.executable)
    server.stop()
    print(json.dumps(result, ensure_ascii=False))
    # A missing bundled file (e.g. the Bilibili subtitle worker) shows up as a tool that is not ready.
    return 0 if ok and all(result.get(key) for key in ('frontend', 'media_ready', 'subtitles_ready')) else 1


def main():
    ensure_utf8_mode()
    if '--check' in sys.argv:
        return check()
    redirect_output()
    hide_child_consoles()
    os.chdir(ROOT)
    port, running = choose_port()
    url = f'http://127.0.0.1:{port}/'
    print(f'port {port} already_running={running}')
    server = None if running else Server(port)
    if server:
        server.start()
    try:
        show(url, server)
    finally:
        if server:
            server.stop()
        print('stopped')
    return 0


if __name__ == '__main__':
    try:
        code = main()
    except SystemExit:
        raise
    except BaseException:
        import traceback
        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    os._exit(code)
