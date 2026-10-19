# Video Library Implementation Plan

> 使用 superpowers:executing-plans 本会话内执行；用户要求三步全完成，不委派，不提交。

**Goal:** 一个视频一个正式项目，统一 Web/CLI 新资源，并完成安全的历史复制整理。
**Architecture:** library_store.py 标准库持久JSON清单、项目身份与原子发布；API/CLI/字幕调用同一仓储。history_import.py只扫描明确旧资源目录，生成可重跑清单并核验复制。不改外部字幕CLI。
**Tech Stack:** 现有Python/FastAPI/React/ffmpeg/Playwright，标准库，无新增依赖。
**Spec:** ../specs/2026-10-11-video-library.md

## Global Constraints
保留现有未提交文件、旧API/Gradio/skill、显式CLI输出语义、原外部字幕工具和Cookie。不删除旧资源。只对可靠身份归并；未知资源隔离待确认。

## Review Focus
- 同BV不同分P与同标题不同视频不能覆盖。
- 迟到任务与跨客户端锁、重启后持久文件仍有效。
- 项目文件缺失/摘要变化/链接过期必须重新校验而非成功假象。
- 显式输出路径与旧skill调用保持兼容。
- 历史导入逐资源状态、未知身份、摘要校验与幂等，原件不变。

### 任务1 新资源仓储与Web
- [x] tests/test_library.py红转绿：身份/文件/批次/并发/持久恢复/ZIP/越界。
- [x] library_store.py、workspace.py、subtitles.py：视频/封面/字幕/分析聚合，持久路由。
- [x] frontend 项目位置/打开目录/ZIP与字幕每分集项目入口；只追加必要样式。

### 任务2 CLI与回归
- [x] cli.py默认项目路径、显式路径保留、抽帧/分析归档、list兼容。
- [x] 测试更新隔离根目录；CLI/Web同身份复用和持久恢复测试。

### 任务3 历史复制和交付
- [x] history_import.py和测试：预览+复制模式、清单、校验、内容去重和待确认分组。
- [x] 本机生成预览，执行复制，再次执行核对幂等与全部源文件摘要。
- [x] README、gitignore、生产构建、Python全套、浏览器真实媒体流程，最终目录和迁移报告。

## Ledger
基线备份：C:/Users/wjx/AppData/Local/Temp/video-parser-library-baseline-0j418k19。
CodeGraph未索引新Web/CLI文件，采用明确文件定向读取，不扩大索引。
当前subtitle UI已有自动下载三份字幕的后续改动，保留这一行为，不擅自恢复旧ZIP自动行为；新增项目整体ZIP为独立导出。

- 三步执行完成：持久仓储与受控接口、React项目操作与恢复、CLI默认归档及显式路径兼容、历史预览/复制/重复验证。
- 历史扫描365个源文件全部处理，复制360份资源、复用5份重复；123个项目（2已确认/121待确认身份），失败0。两次复制对比新增0，预览/复制/复验全部源SHA一致；全部360资源已按登记摘要实读核验。
- Ruling: 缺少来源的旧字幕按来源路径隔离，而不是按字幕摘要去重 — 相同字幕文本不能证明同视频；牺牲部分去重换取不误合并。
- Ruling: 保留起始工作树中已有“解析后自动准备、封面默认标签、字幕自动下载三份”的后续行为 — 不回滚其他窗口成果；仅补项目打开/整体ZIP。
- Ruling: 新验证服务15003，不停止起始时已存在的15001/PID63700 — 所有者并非本次新启动会话；README支持start-web.ps1 -Port15003，最终打开新版入口。
- 原AGENTS、Gradio、API旧路由、launcher、字幕外部项目/Cookie不变；vedio-download仅同步默认目录说明（项目源与个人安装各两份文档），个人旧文档另存外部基线备份。
- 浏览器证明实际ffmpeg合并播放/封面/抽样帧/本地模型分析/自动字幕三份、四个分P项目、统一ZIP、重载恢复和迟到响应隔离。独立CLI子进程实际抽帧与本地模型分析归同一项目。
- 冷启动15003直接读取历史项目、播放已有真实视频、ZIP导出200；本次无真实平台请求/付费模型调用。
