# 开发与验证

## 安装

在仓库根目录执行（Windows PowerShell）：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
npm.cmd --prefix frontend ci --ignore-scripts
```

已有环境升级到包结构时，仍需运行 editable 安装。正式依赖仅在 `pyproject.toml` 维护；`pip install -r requirements.txt` 仍可从仓库根目录转接安装，但测试额外依赖需使用 `.[test]`。不要向系统 Python 安装项目依赖。

## 运行

```powershell
# CLI（安装后不依赖当前工作目录）
.\.venv\Scripts\python.exe -m video_parser capabilities --json
.\.venv\Scripts\python.exe -m video_parser doctor --json

# 旧入口仍可用
.\.venv\Scripts\python.exe cli.py capabilities --json
.\video-parser.ps1 capabilities --json

# Web，或双击 start-web.cmd
.\start-web.ps1 -OpenBrowser

# 手动构建并启动
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe -m uvicorn video_parser.web.app:app --host 127.0.0.1 --port 15001 --no-proxy-headers

# 历史素材导入先看帮助；默认预览，--apply 才复制
.\.venv\Scripts\python.exe -m video_parser.services.history_import --help
```

也可使用虚拟环境的 `video-parser` console script。字幕和 Whisper 已整合到项目模块中，Whisper 使用项目内独立环境；安装方式见 README，不自动切换云端。历史 `python api.py` 与 `uvicorn api:app` 在仓库内仍可用。

## 测试

```powershell
# 默认离线回归；含临时文件、模拟 HTTP、FFmpeg 和本机回环集成
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests/offline -p "test_*.py"

# 前端类型检查和构建
npm.cmd --prefix frontend run build

# 本地浏览器检查：需已安装 Playwright Chromium，按脚本要求准备运行环境
.\.venv\Scripts\python.exe -m tests.browser.browser_optimization
.\.venv\Scripts\python.exe -m tests.browser.browser_settings
.\.venv\Scripts\python.exe -m tests.browser.browser_transcription
```

`tests/live/browser_douyin_live.py` 需要真实平台网络和工作台，仅在明确需要时手动运行；不作为默认离线验收。`tests/fixtures/` 只放测试夹具。浏览器缺失导致的跳过不能算通过。真实下载、外部字幕和模型推理需另行验证。

## 改动纪律

先备份未提交工作区，不执行破坏性 Git 重置。修改 Python 模块后同步导入、mock 目标、包资源、启动器和文档。迁移测试位置后核对发现数量，防止只因未发现测试而得到假通过。

保持外部请求和个人数据边界，不将 Cookie、私人配置或素材加入 Git。`configs/business_config.json` 仅包含运行所需的平台映射和通用 User-Agent；个人凭据应放在被忽略的 `.env` 或 `.local/`。本机 `codegraph.json` 不随源码发布。

项目生成目录如 `.venv/`、`__pycache__/`、`frontend/node_modules/`、`frontend/dist/` 可在编辑器中隐藏，不属于源码分层。
