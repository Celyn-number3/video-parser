<p align="center">
  <img src="./assets/readme/hero.svg" width="100%" alt="Video Parser：视频、字幕与转写，本地有序归档。流程示意：输入素材 → 按需处理 → 保存项目资料或转写结果。">
</p>

<p align="center">
  <strong>为个人视频资料管理打造的本地工作台与命令行工具。</strong><br>
  获取视频、整理分集字幕、转写音视频，让素材和处理结果都有处可寻。
</p>

<p align="center">
  <a href="./pyproject.toml"><img src="https://shields.io/badge/Python-3.11%2B-b4f1d7?labelColor=191f1c" alt="Python 3.11 及以上"></a>
  <a href="./frontend/package.json"><img src="https://shields.io/badge/React-19-b4f1d7?labelColor=191f1c" alt="React 19"></a>
  <a href="./frontend/package.json"><img src="https://shields.io/badge/TypeScript-7-b4f1d7?labelColor=191f1c" alt="TypeScript 7"></a>
  <a href="./pyproject.toml"><img src="https://shields.io/badge/API-FastAPI-b4f1d7?labelColor=191f1c" alt="FastAPI 后端"></a>
  <a href="./scripts/setup-local-tools.ps1"><img src="https://shields.io/badge/Setup-Windows-b4f1d7?labelColor=191f1c" alt="提供 Windows 安装脚本"></a>
</p>

## 应用截图

### 视频工作台

<p align="center">
  <img src="./assets/readme/workspace.png" width="100%" alt="Video Parser 真实工作台：链接输入、封面预览、视频信息、已归档画质和项目文件夹入口。">
</p>

真实运行界面，使用隔离的本地演示项目。彩条画面是 FFmpeg 生成的测试视频，用于展示封面预览与资源归档，不涉及私人素材或平台下载。

### 本地音视频转写

<p align="center">
  <img src="./assets/readme/transcription.png" width="100%" alt="真实音频转文字面板：文件上传、语言选择、开始转录按钮和 CUDA 模型复用选项。">
</p>

展示选择文件、识别语言和模型复用设置。截图时已选择演示文件，尚未提交转写任务；不是转写完成结果。

## 从一个链接，到一份可继续使用的资料

**链接或本地文件 → 下载 / 字幕 / 转写 → 校验与保存。**

例如，课程字幕归入对应视频项目，录音转写另存为文本和时间轴。以下是输出结构示意，不是固定文件名：

```text
library/
└─ …/视频项目/
   ├─ …
   └─ subtitles/
      └─ JSON · SRT · MD

outputs/transcriptions/
└─ …/转写任务/
   └─ TXT · SRT · JSON
```

React 工作台用于交互操作，Python CLI 便于脚本调用，两者共用后端服务逻辑。无需数据库，CLI 无需启动 Web 服务。

> **已有验收记录** · 2026-10-13 的本机验收通过 194 项离线测试，并完成真实 CUDA 批处理、任务取消、进程重启和浏览器专项验证。可复验用例见 [离线测试](tests/offline) 和 [运行时测试](tests/runtime)；这是一次已记录的验收，不是实时 CI 状态，本机详细验收输出不随源码发布。

## 三条常用工作流

### 01 · 获取并整理视频

粘贴链接或分享文本，解析标题和可用资源，再选择下载。B站支持本次实际可用的画质及音视频合并；不同画质分别保存。下载后可继续预览、抽帧或分析。

已实现解析器：**哔哩哔哩、抖音、小红书、快手、好看视频、微视、梨视频、皮皮搞笑**。

解析不会自动下载完整视频。平台支持受页面变化、登录状态、权限和风控影响，不保证每个链接可用，也不绕过访问权限。浏览器不能播放某种编码时，可打开项目文件夹交给本地播放器。

### 02 · 整理 B站分集字幕

工作台扫码登录 → 选择当前、全部或指定分集 → 下载或复用已校验字幕 → 归档至 `library/.../subtitles/`。

- 输出 **JSON / SRT / MD**，支持重试未完成分集。
- 字幕只保存到项目资料库，**不会自动复制到浏览器下载目录**。
- 不提供另存字幕副本按钮；通过“打开项目文件夹”查看。

### 03 · 本地转写音视频

选择本地文件和语言 → 分文件排队 → 本地 CUDA 转写 → 查看文本或下载 TXT / SRT。

- 一次最多选择 **32 个文件**，单文件失败不阻断其他任务。
- 可选模型复用，默认空闲 **60 秒** 后释放。
- 固定使用本地 **large-v3-turbo / CUDA / int8_float16**，不自动回退 CPU、云端或其他模型。
- 每个文件独立保存结果，JSON 也保留在本机输出目录。

## 快速开始

以下命令在仓库根目录的 **Windows PowerShell** 中执行。

### 准备环境

- Python **3.11+**：统一安装脚本可准备项目内 Python 环境。
- Node.js **22.12+** 与 npm：用于前端安装和构建。
- FFmpeg / FFprobe：需要能从 `PATH` 调用。
- `uv`：用于统一安装流程。
- 本地转写需要兼容的 **NVIDIA GPU 与 CUDA 运行环境**；基础解析、下载、抽帧不依赖 GPU。

### 安装 → 检查 → 启动

```powershell
# 准备运行环境、浏览器、固定模型和前端
.\scripts\setup-local-tools.ps1 -DownloadModel

# 检查模型摘要、CUDA、浏览器、写权限与磁盘
.\.venv\Scripts\python.exe cli.py doctor --deep --json

# 打开本地工作台
.\start-web.ps1 -OpenBrowser
```

访问 **http://127.0.0.1:15001**，粘贴链接开始；也可双击 `start-web.cmd`。保持终端开启，按 `Ctrl+C` 停止。需要换端口时，使用 `-Port 15002`。

首次安装需要网络，模型和 NVIDIA 依赖较大。只使用 CLI 可给安装脚本加 `-SkipFrontend`。主环境、Whisper 和前端分别使用锁文件；安装器遇到未经审查的主环境依赖降级会停止。换机器或移动目录后应重新创建虚拟环境，不要直接复制旧环境。

## 命令行也能独立使用

```powershell
# 解析链接 / 下载本次可用的最高画质
.\.venv\Scripts\python.exe cli.py parse "视频链接或分享文本" --json
.\.venv\Scripts\python.exe cli.py download "B站视频链接" --quality best

# 单文件转写 / 批次内复用模型
.\.venv\Scripts\python.exe cli.py transcribe "素材.mp4" --language zh --timestamps
.\.venv\Scripts\python.exe cli.py transcribe-batch "素材一.wav" "素材二.mp4" --language zh --json
```

<details>
<summary><strong>更多命令：封面、抽帧、分析与本地列表</strong></summary>

```powershell
.\.venv\Scripts\python.exe cli.py cover "视频链接"
.\.venv\Scripts\python.exe cli.py frames "素材.mp4" --count 8
.\.venv\Scripts\python.exe cli.py analyze "素材.mp4" --frames 6
.\.venv\Scripts\python.exe cli.py list --json
.\.venv\Scripts\python.exe cli.py capabilities --json
```

分析命令需要先配置模型服务。运行 `cli.py <命令> --help` 查看完整参数。

</details>

批量转写部分失败时退出码为 `1`，成功结果仍保留。B站平台字幕下载通过工作台提供；`transcribe` 是语音识别，不是下载平台字幕。

## 长任务，有状态也有边界

| 操作 | 实际行为 |
| --- | --- |
| 刷新页面 | 重新连接已有任务，不重复提交 |
| 取消任务 | 停止所属工作进程或在安全检查点结束；清空输入不等于取消 |
| 重启服务 | 未完成任务标记为中断，需手动重试，不自动续跑推理或付费分析 |
| 清理缓存 | 先预览再确认，只清理符合条件的程序自有临时目录 |
| 复用资源 | 保留完整 SHA-256 校验与路径保护，不用大小或 mtime 替代内容校验 |

资料库、模型、Cookies、原始素材和转写成果不属于缓存清理范围。详细规则见 [任务、缓存与批量转写](docs/task-runtime.md)。

## 配置与隐私

按需将 `.env.example` 复制为 `.env`，修改后重启服务。基础解析、下载和抽帧不需要 AI 密钥。

| 配置 | 用途 |
| --- | --- |
| `KUAISHOU_COOKIE` | 可选快手登录凭据，仅保存在本机 `.env` |
| `QWEN_API_KEY` | 后端模型服务密钥 |
| `QWEN_API_BASE_URL` | OpenAI 兼容接口地址 |
| `QWEN_MODEL_ID` | 视觉模型标识 |
| `MAX_FRAMES` | AI 分析默认抽样帧数 |
| `VIDEO_LIBRARY_ROOT` | 资料库路径，默认 `library/` |

**本地转写不上传音视频；AI 画面分析会把抽样画面发送给配置的模型服务。** 分析前请确认素材允许上传。画面分析不读取音轨，也不等于理解整个长视频；取消本地等待无法保证撤销服务端已经产生的计算或费用。

工作台默认仅监听本机回环地址，**不要直接暴露到公网**。不要分享或提交 `.env`、Cookies、私人配置、模型、运行环境及处理结果；密钥不能写进前端代码或 `VITE_*` 变量。Git 忽略规则不等于加密，也不会移除已经提交的敏感内容。

## 项目结构与开发

<details>
<summary><strong>查看目录职责</strong></summary>

```text
src/video_parser/
├─ web/              FastAPI 与工作台接口
├─ services/         任务、资源库、下载、字幕、转写与分析
├─ integrations/     B站字幕与 Whisper 模块
├─ platforms/        平台解析器
├─ core/             路径、配置与日志
└─ cli.py            CLI 实现
frontend/            React + TypeScript 工作台
assets/readme/       README 静态 SVG 视觉资源
scripts/             安装、校验与性能检查
requirements/        Python 环境锁文件
tests/               离线、浏览器、运行时与真实平台测试
docs/                使用、架构与开发文档
library/             正式资料库
outputs/             转写结果与其他本地产物
cache/               临时文件与可复用缓存
models/              本地模型
runtimes/            独立运行环境与浏览器
.local/              本地凭据与任务记录
```

数据与运行目录按安装、使用情况生成。根目录 `cli.py` 是命令行入口，`start-web.ps1` 是工作台启动器。当前支持源码仓库运行，不承诺单独安装 wheel 即可获得完整前端和本机配置。

</details>

```powershell
# 离线回归 / 类型检查与生产构建
.\.venv\Scripts\python.exe -m unittest discover -s tests/offline -p "test_*.py"
npm.cmd --prefix frontend run build

# 开发前端（另行启动 15001 后端）
npm.cmd --prefix frontend run dev
```

开发前端默认在 `http://127.0.0.1:5173`，代理 API 到 `15001`。后端提供 `/health` 与 `/docs`。GPU 和真实平台测试需显式运行，不属于默认离线回归。

[项目架构](docs/architecture.md) · [开发指引](docs/development.md) · [任务使用说明](docs/task-runtime.md)

## 许可与使用范围

适用的许可与第三方代码说明见 [LICENSE](LICENSE) 和 [许可说明](docs/integrated-tools-provenance.md)。不同来源的代码可能适用不同许可，发布或分发前请确认授权范围。请仅处理拥有或获得授权的素材，并遵守平台条款。
