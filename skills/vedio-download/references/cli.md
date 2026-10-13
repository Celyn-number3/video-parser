# CLI 命令参考

## 运行方式

项目 Python：`.venv/Scripts/python.exe`。仓库内启动器自动定位项目；个人安装的 Skill 使用用户设置的 `VIDEO_PARSER_ROOT`。以下 PowerShell 示例在项目根目录执行。

从任意工作目录运行 skill 的启动脚本，例如 PowerShell：

```powershell
& '.\.venv\Scripts\python.exe' '.\skills\vedio-download\scripts\video_download.py' capabilities --json
```

下面用 `video_download.py` 简写同一个脚本。所有子命令支持 `--json`（可置于子命令前或后）。退出码：0 成功，1 执行失败，2 参数错误，130 用户中断。stdout 为最终结果，stderr 为日志、进度及错误。

## 命令

```text
video_download.py capabilities --json
video_download.py doctor --json
video_download.py parse "链接或完整分享文本" --json
video_download.py download "链接" --output-dir "E:\视频" --json
video_download.py download "链接" --output "E:\视频\成品.mp4" --json
video_download.py cover "链接" --output-dir "E:\视频" --json
video_download.py frames "E:\视频\成品.mp4" --count 12 --output "E:\视频\成品画面" --json
video_download.py analyze "E:\视频\成品.mp4" --frames 8 --prompt "概括画面叙事" --output "E:\视频\分析.md" --json
video_download.py analyze "链接" --output-dir "E:\视频" --output "E:\视频\分析.md" --json
video_download.py transcribe "E:\录音\会议.wav" --language auto --timestamps --output-dir "E:\转录结果\本次任务" --json
video_download.py list --directory "E:\视频" --json
video_download.py play "E:\视频\成品.mp4" --json
```

默认按视频归档到项目根目录下的 `library`，不跟随当前终端目录；默认的抽帧和分析报告也归入同一视频项目。显式 `--output` / `--output-dir` 保持原平铺输出语义。显式相对输出路径则相对于启动脚本使用的项目目录；推荐传绝对路径避免歧义。`analyze --output` 是报告文件，`--output-dir` 是链接分析所需视频的下载目录；`frames --output` 是新的输出目录。帧数必须为正整数。

默认不覆盖文件或已有帧目录。成功文件经检查后发布，失败的下载临时文件不会冒充成品。下载命名保留中文标题及视频 ID；B站分P链接的 `p` 参数保留。

`doctor` 返回依赖状态、ffmpeg/ffprobe 路径、`ai_configured`，不会访问网络或输出 API 密钥。`ok: true` 代表检查运行成功，不代表所有可选功能就绪；需要读取 `parser_ready`、`media_ready` 、`ai_configured` 和 `transcription_ready`。

## 本机音视频转录

`transcribe` 只接受已有本地音视频，不接受链接。语言默认自动检测（auto），可指定 zh/en。默认结果保存在项目 `outputs/transcriptions/<任务ID>/`；`--output-dir` 显式指定目录，不会覆盖已有同名 TXT/SRT/JSON/日志。SRT 总含片段级时间戳，`--timestamps` 给 TXT 增加片段时间。结果不是逐字精确字幕，空文本需说明未识别有效语音。

复用 `WHISPER_ROOT`（默认 `D:\CodexProjects\whisper-local`）的独立 Python 和 large-v3-turbo CUDA 模型，不上传音频、不启动网页、不自动安装或切换云端。`transcription_ready` 只核对安装文件；真实推理还受 CUDA/显存状态影响。

## 功能依赖

- 平台解析使用已有 `DownloaderFactory` 和 URL 工具；CLI 可独立运行，不需要启动 Web 服务，也不需要数据库。
- 下载校验依赖 ffprobe；B站独立音视频合并和画面提取还需要 ffmpeg。
- 画面提取复用项目 `video_parser.services.analysis`，需要该模块的 Python 依赖，但不需要 API 密钥。
- AI 分析需要项目 `.env` 或环境变量中的 `QWEN_API_KEY`。可选变量为 `QWEN_API_BASE_URL`、`QWEN_MODEL_ID`、`MAX_FRAMES`。CLI 加载项目根目录 `.env`，不输出密钥。请用户在本机配置，不要在聊天中收集它。
- 代码中包含抖音、B站、小红书、快手、好看视频、微视、梨视频和皮皮搞笑解析器。原解析器可能随平台页面变化失效；不自动安装其他下载器或导出浏览器登录凭据。

## 结果示例

```json
{"ok":true,"command":"download","path":"E:\\视频\\成品.mp4","size_bytes":21363339,"media":{"streams":[{"codec_type":"video","width":852,"height":480},{"codec_type":"audio"}],"format":{"duration":"686.4"}},"title":"视频标题"}
```

错误：

```json
{"ok":false,"command":"download","error":"文件已存在，拒绝覆盖：…"}
```

不要把 Signed CDN URL 当永久链接保存用于以后下载，稍后应重新解析源分享链接。


## B站画质选择

`parse`、`download`、链接 `analyze` 支持 `--quality best`（默认最高可取得画质）、`--quality 720p` 等。先读取解析结果 `qualities` 确认实际选项；用户指定清晰度时传对应参数，未提供的画质报错而不是静默降级。其他平台只有单一直链时仅best/default，不伪造画质。
默认资源库中不同画质作为同一项目的独立 `videos` 文件保存，已校验的匹配版本复用，原 `video.mp4` 不删除。显式 `--output` / `--output-dir` 路径语义与拒绝覆盖规则保持。
解析 CLI 只取信息，不下载视频；Web同样改为解析后手动下载归档。下载画质不代表可绕过登录/会员权限。
