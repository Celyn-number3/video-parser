# 脚本职责索引

根部 CMD 保留双击入口，PowerShell 实现在 scripts/。脚本自行定位仓库；安装、锁定及验证脚本仍从仓库根调用，不为外观增加空分层。

| 职责 | 脚本 | 边界 |
|---|---|---|
| 启动 | `scripts/start-web.ps1`、`scripts/start-ai.ps1`、`scripts/video-parser.ps1` | 根部 CMD 双击入口保留；脚本按自身位置定位仓库 |
| 安装 | `scripts/setup-local-tools.ps1` | 设置项目内运行工具；仅显式 `-DownloadModel` 下载缺失模型 |
| 启动 | `scripts/start-local-ai.py` | 本机模型启动实现；优先使用根部 `start-ai.cmd` / `scripts/start-ai.ps1` |
| 锁定与检查 | `scripts/lock-main-environment.py`、`scripts/check-main-lock.py` | 依赖锁维护与一致性检查；不自动改全局环境 |
| 验证 | `scripts/verify-whisper-model.py` | 模型存在、大小与哈希检查；不自动重下载 |
| 模型专项验证 | `scripts/check-local-ai.py` | 会实际调用限定的本机模型；不是无副作用的普通健康检查，不在常规回归中自动执行 |
| 性能验证 | `scripts/benchmark-library-index.py` | 资料库索引专项基准；按脚本参数选择范围 |

运行时缓存和日志默认分别为 `.local/work/cache/`、`.local/work/logs/`。旧安装在显式迁移前继续使用唯一的旧目录；新旧目录同时存在时拒绝启动，避免把历史任务与新任务分成两套。不要手工创建第二个缓存目录。
