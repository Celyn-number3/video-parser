# 集成工具来源与许可边界

本次在用户授权下将两个本机工具的必要实现并入 video-parser，保留原项目代码及已有版权声明。没有合并 Git 历史、初始化子仓库、提交或推送。

| 来源 | 基准提交 | 纳入内容 |
|---|---|---|
| Celyn-number2/whisper-desk | `05b4c7a2bd44474e215a49d28c8d9db6917c5c2e` | CLI、CUDA 运行时、固定模型清单、6 项 CLI 测试 |
| Celyn-number2/bili_substitle_download | `9296830b216bdd477946c8f512d0368ed43fd6ba` | 字幕工作进程、三件套校验器、2 项校验器测试；含本机会话中已实现的无头适配 |

目的路径分别为 `backend/video_parser/integrations/whisper/` 和 `backend/video_parser/integrations/bilibili/`。新增适配包括项目内资源路径、工作台扫码登录缓存、固定无头执行及主项目服务调用。

没有引入两个工具原来的 Gradio / Flask Web 界面、启动器、远程 .git、个人 agent 配置或旧服务端。原 B站工具中针对退休 Flask 服务的测试不属于新的执行路径，因此不移入；新的工作台服务测试和集成测试覆盖实际采用的路径。

**许可状态：**检查两个工具仓库根目录及浅层源码目录，未发现明确 LICENSE / COPYING 文件。因此不能仅因它们位于本仓库就认定自动适用本仓库的 MIT 许可。本次是用户授权的本机整合；公开发布、再分发或替其授予许可证前，应由用户确认其著作权归属与授权。没有删除或伪造上游许可声明。

第三方 Python 包及其依赖仍受各自许可证约束；安装后的许可资料随包保存在本机运行环境中。模型沿用原固定清单，对应 Hugging Face 仓库 `dropbox-dash/faster-whisper-large-v3-turbo`，revision `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`；再分发模型需另行核对模型及上游权重许可。

模型、虚拟环境、NVIDIA DLL、Chromium、Cookie、字幕及其他个人数据不属于本次提交内容，均留在 Git 忽略的资源/数据目录。
