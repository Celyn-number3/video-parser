# React 视频工作台 Implementation Plan

> **For agentic workers:** 使用 superpowers:executing-plans，在当前会话内逐项执行，不委派、不提交。

**Goal:** 交付可实际解析、下载、预览并分析画面的现代 React 工作台。
**Architecture:** 同源 React + FastAPI router，复用现有 CLI 媒体实现。同步线程池接口与每资源锁，不引入任务队列；浏览器以请求版本和 AbortController 隔离过期响应。
**Tech Stack:** React、Vite、TypeScript；现有 FastAPI、Pillow、requests、ffmpeg、Playwright。
**Spec:** ../specs/2026-10-11-react-workspace.md

## Global Constraints
保留后端/CLI/skill/Gradio和已有未提交改动。深色薄荷绿、独立标签、按钮和边框阴影；不恢复装饰文案。不创建云资源、不改全局配置、不暴露本机文件/密钥。

## Review Focus
- 输入切换与清空期间旧请求完成，不恢复旧内容。
- 两个客户端互不覆盖，重复下载不重复生成，不完整文件不可访问。
- 无效链接/封面失败/下载失败/模型失败可理解且可重试。
- 本机 Host/Origin、受控文件目录、符号链接逃逸、缺少 AI 同意/密钥。
- 无横向溢出、键盘标签焦点、所有可见带边框区域与按钮保留阴影。

## Task 1: 后端媒体桥接
- [x] 新增 tests/test_react_api.py，观察失败；覆盖解析、资源隔离、预览/下载复用、失败、Range、文件安全、AI 前置条件。
- [x] 新增 workspace.py：受控资源会话与本机边界、复用 CLI、AI 显式同意；api.py 最小注册和静态托管。
- [x] 运行相关测试，确认红转绿，再运行既有测试。

## Task 2: React 工作台
- [x] 新增 frontend/package.json、锁文件、TS/Vite配置、index.html、src/api.ts、src/App.tsx、src/main.tsx、src/style.css。
- [x] 实现解析/预览/封面/下载/AI真实请求，失效响应保护与错误重试；沿旧图继承精简文案和阴影。
- [x] 新增浏览器测试先检查真实DOM并经本地真实 API/ffmpeg 媒体验证全流程，不只截图。
- [x] 执行类型检查、生产构建、浏览器验证并修复。

## Task 3: 启动与交付
- [x] 新增 start-web.ps1（构建 + 回环 Uvicorn），仅追加 .gitignore 所需项，更新 README 的主要入口及回退说明。
- [x] 运行 Python 全套、构建、浏览器回归、git diff --check；核对备份哈希确保不相关旧文件未变。
- [x] 独立端口启动新版、保留旧服务，打开实际页面并给出最终结果和验证边界。

## Execution ledger
- 基线：main / aa931d0006c0fce090541829cb819ab08e0d60df；44项 Python 测试通过。
- 外部备份：C:/Users/wjx/AppData/Local/Temp/video-parser-react-baseline-3n8l8w7v。
- Ruling: 使用每资源同步线程池接口而非队列 — 本地单工作台无需后台任务基础设施；长任务保持真实忙碌状态，可取消等待但不保证取消服务器已开始工作。
- Ruling: 新版端口15001，原5001/17860不动 — 避免干扰其他聊天服务。

- 验证：54 项 Python 测试全部通过（无跳过），TypeScript 与生产构建通过，npm audit 为 0。
- 浏览器：真实 API/CLI/ffmpeg 音视频合并、播放/保存、封面、真实抽帧+本地模型 HTTP、失败重试、重复点击、清空/切换期间迟到响应/自动下载隔离通过。
- 视觉：1440/768/390/320px、16:9、无横向溢出、全部可见按钮/边框阴影、键盘标签切换与减少动态效果通过；截图/报告见 outputs/react-preview。
- Ruling: Vite 代理显式 changeOrigin:false — 已安装 Vite 的字符串简写会改写 Host，导致正确的后端同源校验拒绝开发模式 POST；保持 Host 而非放宽后端安全边界。生产15001与开发5173实测 GET/POST 通过。
- 保留核对：16 份既有非目标文件哈希不变；app.py、qwen3vl.py、cli.py、旧测试、skill、static 与 launcher 未改。原服务5001/17860未重启。调试用5173已停止，新版15001保持运行。
- 验证边界：未访问真实平台、未调用收费模型；Windows 不允许创建符号链接时，资源越界测试改用实际外部目录验证同一规范路径保护（不跳过测试）。现有 requests/pkg_resources/Gradio 告警仍存在。
