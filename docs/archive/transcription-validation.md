# 本机音视频转录验证

日期：2026-10-11。

## 本次改动

- 新增本机 Whisper 桥接模块、串行后台任务、流式上传与安全下载接口。
- React 面板支持本地音视频上传、指定已归档画质转写、语言选择、文字展示和 TXT/SRT 下载。
- CLI 新增 transcribe；doctor 返回 transcription_ready；项目内 Skill 命令参考同步更新。
- 新输出目录加入忽略规则，原有配置和无关未提交改动保留；未安装依赖或模型，未修改个人全局 Skill，未提交或推送 Git。

## 实际验证

- 全量 Python 回归：116 项通过，其中转录回归 16 项；覆盖输出冲突、错误/静音、路径保护、大小限制、同源限制、过期/容量、精确视频版本、CLI/Web 操作系统文件锁串行与 Windows 超时进程树终止。
- 前端 TypeScript 检查与 Vite 生产构建通过。
- 新浏览器流程通过：真实页面/HTTP/文件校验，GPU 边界模拟；上传、轮询、TXT/SRT 下载、非法文件错误、归档来源转录、桌面/手机版布局、无页面运行时错误。证据位于 outputs/verification-transcription/verification.json 和两张截图。
- 原有浏览器流程通过：视频解析、下载重试、画质切换、过期响应隔离、封面/播放器、分析、字幕分集、项目资源统一及 CLI 操作；包含真实 ffmpeg 和本地模型服务夹具，未访问外部平台。
- 真实 GPU CLI 转录通过：使用 Windows 本机语音合成生成非私人英文样本，7.86 秒音频、2.83 秒转录、9.85 秒模型加载，得到完整测试句。
- 真实 GPU HTTP 上传转录通过：自动检测英文、正文匹配、TXT/SRT HTTP 200、临时上传文件已清理。证据位于 outputs/verification-transcription/live-gpu-http.json。
- Git 差异空白检查通过（使用 core.whitespace=cr-at-eol 适配工作区已有 Windows 换行）。默认 git diff --check 会将其他既有 CRLF 改动报告为尾部空白；未为此改写无关文件。

## 未覆盖与已知限制

- 中文识别准确率、噪声/弱语音、长录音和真实不同硬件显存压力未实测。
- 浏览器完整流程的 GPU 边界模拟；真实 GPU 分别通过 CLI 与 HTTP 端到端检查，不把这两种验证混称为真实浏览器 GPU 测试。
- 结果不自动清理；页面切换不取消服务器任务；内存状态不跨重启恢复。
- 环境现有 requests 依赖版本警告、py_mini_racer 的 pkg_resources 弃用警告与偶发测试事件循环 ResourceWarning 未在本次修改范围内修复。
