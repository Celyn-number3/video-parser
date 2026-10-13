# 任务、缓存与批量转录

## 工作台任务

字幕、语音转录、视频下载、AI 分析使用同一个本地任务调度器。每类只有一个执行线程，最多等待 32 项；不为每个排队任务创建等待线程，不引入数据库、Redis 或 Celery。

任务状态与执行阶段分开保存，保留既有 API 的兼容性：

- 状态：`queued`、`running`、`completed`、`partial`、`empty`、`failed`、`login_required`、`cancelled`、`interrupted`。
- 阶段：读取信息、下载/转录/提取画面/模型分析、校验、归档。
- 队列位置、分集计数或当前音视频轨道字节数、任务 ID、阶段耗时保存在本机记录中。不虚构推理百分比。

页面底部的**任务中心**可以查看最近任务、取消执行或排队任务、重新查看字幕/转录结果，以及打开已归档项目。字幕面板提供**重试未完成分集**。刷新会重新连接，不需要再次提交。

“清空”或切换视频不是取消后台任务。取消请使用明确的取消按钮；它会停止本任务的进程树，或在安全检查点停止本地归档工作。已归档成果不删除。AI 取消只终止本机操作/连接，无法保证模型服务撤销已产生的费用。

正常停止工作台会通知自己的任务退出；异常退出后，重新启动会把未完成的记录标记为 `interrupted`。没有跨重启的推理续跑、断点续传或自动付费重试。原始下载地址可能过期，中断后应重新解析再提交。

工作台的新异步端点为 `/videos/{id}/prepare-task`、`/videos/{id}/analyze-task`，进度为 `/tasks/{id}`；原同步接口保留兼容。CLI 保留同步命令语义，不要求运行 Web 服务。一个项目只运行一个工作台服务实例；CLI/Web 转录另有跨进程文件锁。

## 本地记录与隐私

- 字幕记录：`cache/react-workspace/subtitles/.tasks/`。
- 转录记录：`outputs/transcriptions/.tasks/`。
- 视频/分析记录：`.local/tasks/workflows/`。
- 记录采用原子 JSON 写入。列表显示最近 100 项；旧终态 Python 对象会移出内存，历史文件不因此删除。
- 视频解析的临时签名地址和请求头通过子进程 stdin 传递，不写入任务日志。HTTP 不返回原始工具异常或 Cookie。
- 客户端浏览器仅记住任务 ID，不保存 Cookie、模型密钥或上传音视频。

这些位置继承项目的 Git 忽略规则；不是加密存储。不要将本机任务目录、日志、素材或凭据作为代码上传。

## 字幕工作进程

默认集成模块通过带版本号的 JSONL 文件报告课程身份、分集结果与进度，不依赖人类日志里的 `series:`、`selected` 等文字判断默认流程。字幕仍在独立进程中执行。

仅检查目标课程的目标分集；不再在每次任务前遍历所有字幕缓存。缓存命中也必须通过 JSON/SRT/MD 三件套检查，归档后仍受资源库完整性校验保护。旧外部工具覆盖配置仍保留兼容解析，不等同于新的默认协议。

字幕正式结果只在 `library/.../subtitles/`，不会自动复制到浏览器下载文件夹，也没有“另存字幕副本”按钮；保留“打开项目文件夹”。

## 缓存边界

成功字幕任务的已归档中间副本、成功视频/分析任务的自有临时目录会清理。失败或中断任务保留临时证据，便于排查。

**缓存管理**先给出体积与清理预览，只有点击**确认清理上述临时缓存**才执行：

- 仅选择本程序带所有权标记、已经停止、创建超过 24 小时的字幕/视频/分析临时任务目录。
- 预览令牌 10 分钟内有效且只能使用一次；检测到目录变化则跳过。
- 有运行或排队任务时不能执行清理。路径逃逸、符号链接、junction、未知目录不清理。
- 不清理 `library`、模型、Cookie、原始音视频、转录成果、任务记录或可复用字幕缓存。
- 这不是“删除整个 cache”的按钮。上传中断等无法确认所有权的历史缓存，宁可保留，不自动删除。

资源库的 `.project-index.json` 仅用于快速定位项目，可重建，不是事实来源。删除它并重启后，首次查询会重建。项目清单与完整文件 SHA-256 校验仍是判断依据；**不把大小和 mtime 相同当成内容未变化的证明**。

## Whisper 批量与空闲释放

工作台可一次选择最多 32 个文件，分别排队。多选时默认启用模型复用，单文件则默认不常驻。可以通过复用复选框决定是否保留一个短暂的 CUDA 模型进程；默认空闲 60 秒释放。取消当前复用任务也会停止这个自有进程。

CLI 示例：

```powershell
.\.venv\Scripts\python.exe -m video_parser transcribe-batch "素材一.wav" "素材二.mp4" --language zh --json
```

每个文件有独立输出目录；单个缺失、损坏或转录失败不会阻止后续文件。一个批次加载一次模型，批次结束释放。部分失败时 CLI 退出码为 1，JSON 仍列出所有成功/失败项；不会覆盖旧文件。

仍然只使用项目内 `large-v3-turbo`、CUDA、`int8_float16`，强制本地模型文件，不回退 CPU、云端或其他模型。集成进程在启动 stdin 读取线程之前初始化原生模型，避免本机 Windows/NumPy 的并发 DLL 初始化阻塞。

## 环境与排错

```powershell
# 基础离线检查
.\.venv\Scripts\python.exe -m video_parser doctor --json

# 完整模型 SHA-256、真实无头浏览器启动、本机 CUDA、目录写入与剩余空间
.\.venv\Scripts\python.exe -m video_parser doctor --deep --json
```

普通检查的文件存在/大小结果不代表哈希通过，完整校验需 `--deep`。doctor 不访问外网，不输出密钥或 Cookie。空间低于 2 GiB 会标记警告。

错误结果带稳定分类与任务 ID；HTTP 还有 `X-Request-ID`。网络断开时只对读取状态做有限退避重试，不自动重新提交下载或付费分析。模型 SDK 自动重试也已关闭。

Windows 主环境锁定为 `requirements/windows-main.lock.txt` 中实际测试的 41 个运行/测试依赖；Whisper 保持独立的 28 项锁文件，前端使用 `package-lock.json`。本轮没有升级/降级这些已安装包。安装脚本在主环境会发生降级时拒绝自动继续，要求先审查或创建新的独立环境。

## 可复验命令

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests/offline
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe tests/browser/browser_optimization.py
.\.venv\Scripts\python.exe tests/browser/browser_transcription.py
.\.venv\Scripts\python.exe tests/runtime/check_task_restart.py
.\.venv\Scripts\python.exe scripts/benchmark-library-index.py
```

`tests/runtime/check_optimization_gpu.py` 是显式 CUDA 验收，只使用已存在的公共 JFK 测试音频及其合成副本，不扫描私人录音。`check_live_subtitle_optimization.py` 是显式真实平台检查，仅复用已授权课程 P1；不在离线回归中自动运行。
