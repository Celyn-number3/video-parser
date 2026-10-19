# 视频工作台设置 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 当前仅规划；用户确认后再实现。不自行启动子代理、不提交已有用户改动。

**Goal:** 为本机 React 视频工作台加入可访问的设置入口，让默认画质与归档完成提醒持续生效，并说明实际保存位置和归档复用规则。

**Architecture:** 在现有 App 页头增加按钮，使用原生 dialog 呈现设置。浏览器偏好保存到独立 localStorage 键；后端只扩展现有只读 config 响应，不新增配置写入 API、不改动归档目录或 CLI 默认行为。

**Tech Stack:** 项目现有 React、TypeScript、CSS、FastAPI、Python unittest、Playwright；无新增依赖。

**Spec:** 本文“范围与行为”是待用户确认的执行规格，来源于本会话的设置功能讨论；此次收敛与上一轮五项建议不同，必须确认后才执行。

## 全局约束

- Ponytail Full：复用现有 request、Configuration、VideoQuality、Icon、测试与状态保护逻辑。
- 保留所有已有未提交文件；此次只新增本规划文件。实施时只修改任务列出的文件，不顺手重构。
- local_request 的本机同源限制、后端资源校验、AI 显式同意、平台登录边界保持不变。
- 不读取或回传密钥、Cookie、完整环境变量；设置重置不删除项目、历史或实际视频。
- CodeGraph 已以当前项目绝对路径调用；根 codegraph.json 排除了 frontend、workspace.py、cli.py、library_store.py 和 tests，故对这些文件采用定向原生读取。未扩展索引，不把索引未覆盖区的调用链当作完整结果。

## 当前实现依据

- frontend/src/App.tsx：parse() 采用后端 default_quality_id；chooseQuality() 会中断当前请求；prepare() 通过质量 ID 下载归档，且用 epoch/current 防止过期响应更新页面。
- frontend/src/download.ts：saveFiles() 触发链接下载，没有浏览器文件落盘成功回执。
- workspace.py：GET /api/workspace/config 提供能力状态；POST /videos/{identifier}/prepare 负责归档。前端同一时刻只有一个 parse/prepare/analyze 操作。
- library_store.py：LIBRARY_ROOT 由 VIDEO_LIBRARY_ROOT 或默认 library 目录决定；tests/test_quality.py 已有多画质归档与重复资源复用测试。
- tests/browser_react.py 使用本地 fixtures 验证真实工作台流程；frontend/package.json 提供 typecheck/build，没有独立前端单元测试框架。

## 范围与行为（待确认）

### 第一版

1. 页头右侧“设置”按钮，打开弹窗；包含“下载偏好”“保存说明”“服务状态”三个区块。
2. 默认画质：最高可用（默认）、优先 1080P、优先 720P。作用于下次解析，不立即改变当前视频、正在处理的任务或恢复的历史项目。
3. 选择规则：最高可用保持后端 default_quality_id；优先指定分辨率时，选最高的不超过目标的已知高度；若全部高于目标，选最低的已知高度；若全部未知，回退后端默认。相同高度保持原返回顺序，不改变后端已选的编码兼容性。
4. 新解析的 quality 与 media 必须来自同一选项，禁止沿用 result.media 导致低画质选择显示高画质归档。
5. 归档完成提醒：默认关闭；开启后仅在新的 prepare 请求成功且 current() 有效时显示非模态提示，提示“视频已归档”。原有状态文字一直保留，不因关闭提醒而消失。失败、取消、解析时复用历史资源不显示成功提醒。
6. 提醒是页面内提示，不申请系统通知权限、不加声音、不声称浏览器导出已保存成功。字幕、转录通知暂不统一改造。
7. 保存位置：只读显示后端归档根目录，并明确与浏览器“导出视频”的下载目录不同。浏览器导出位置由浏览器控制。本版不提供修改目录、打开系统文件夹或迁移文件。
8. 同名处理：展示“归档按项目和画质管理，已有资源优先复用”；浏览器导出遵循浏览器规则。不新增覆盖/自动编号开关。
9. 服务状态：复用现有 config 中的媒体、字幕、转录、AI 就绪状态；不新增轮询、安装按钮、密钥编辑或虚假的整体健康判定。
10. “恢复默认”：只重置本版两个偏好；保留 last-project、last-quality 与归档文件。普通偏好即时生效、即时尝试保存；失败需提示“当前页已生效，关闭或刷新后可能丢失”，不能声称已保存。

### 明确延期

- 并发下载数量：现有主流程不是下载队列；设置数字前必须先有队列与实际执行限制，不能加入无效控件。
- 修改归档目录：需要旧项目可发现性、任务期间切换限制、目录权限、路径边界、持久化及恢复策略，另立需求。
- 文件命名、主题、自动重试、清理缓存、删除历史、账号管理、系统通知：不在第一版范围。

## Review Focus

- 存储损坏、不可写：降级到默认/当前会话，提醒保存失败，不阻断视频操作。
- 默认画质与归档 media 不匹配：始终按最终 quality ID 同步选择 media，未归档时必须为空。
- 当前任务被设置变更干扰：不调用 chooseQuality，不中断请求；只影响后续解析。
- 新提醒误报成功：只认有效 prepare 成功响应，失败与过期响应不提示。
- 重置误删项目：仅写独立偏好键，不使用 localStorage.clear，不调用删除接口。

## 文件与接口

以下路径均相对项目根 E:\项目管理\视频下载\video-parser；执行者编辑前检查 frontend/tests 下适用的 AGENTS.md。

新增：frontend/src/settings.ts（偏好规范化、画质选择）；frontend/src/Settings.tsx（弹窗）；tests/browser_settings.py（独立设置 E2E，复用现有 fixture 模式）。
修改：frontend/src/App.tsx（入口与偏好接线）；frontend/src/api.ts（Configuration 字段）；frontend/src/Icon.tsx（本地设置图标）；frontend/src/style.css（弹窗与提示）；workspace.py（只读配置）；tests/test_react_api.py（配置回归）；README.md（使用说明）。

不改：下载器、cli.py、library_store.py、.env、现有启动脚本、依赖清单。

新增契约：

```ts
export type Settings = {
  qualityPreference: 'best' | '1080p' | '720p';
  completionReminder: boolean;
};
export const SETTINGS_KEY = 'video-parser:settings';
export const DEFAULT_SETTINGS: Settings = {
  qualityPreference: 'best', completionReminder: false,
};
// 未知键忽略；非法字段独立回退，布尔值不接受字符串转换。
export function normalizeSettings(value: unknown): Settings;
// 只返回候选中存在的 ID；空候选返回空字符串。
export function preferredQualityId(
  qualities: readonly VideoQuality[], defaultId: string | null,
  preference: Settings['qualityPreference'],
): string;
```

Settings.tsx 使用 props：settings、onChange、config、configError、onClose。父层负责持久化及保存结果文字，弹窗不调用视频接口。Configuration 新增 archive_root: string；API 不接受目录写入。

## Task 1：只读保存说明与能力状态

- [ ] 在 tests/test_react_api.py 的 ReactAPITests 添加配置测试。借用 setUp 的临时 LIBRARY_ROOT，断言 config 返回的 archive_root 等于该目录的绝对路径；保留并断言现有六个配置字段；确认响应不包含 QWEN_API_KEY、cookie 或环境变量集合。
- [ ] 执行 `python -m unittest tests.test_react_api -v`，新增字段测试应失败。
- [ ] workspace.configuration() 在现有字典增加 `'archive_root': str(library.LIBRARY_ROOT.resolve())`；frontend/src/api.ts 同步增加 `archive_root: string`。不在此操作 mkdir、扫描库或改变根目录。
- [ ] 重跑同一测试，验证现有本机/同源拒绝测试未退化。

接口自检示例（置于现有测试类）：

```python
def test_config_archive_root(self):
    response = self.client.get('/api/workspace/config')
    self.assertEqual(response.status_code, 200)
    data = response.json()
    self.assertEqual(data['archive_root'], str((self.root / 'library').resolve()))
    for key in ('platforms', 'ai_configured', 'media_ready', 'subtitles_ready',
                'transcription_ready', 'transcription_upload_limit'):
        self.assertIn(key, data)
    self.assertNotIn('QWEN_API_KEY', data)
    self.assertNotIn('cookie', data)
```

交付：真实目录与状态可安全读取；无可写配置接口。

## Task 2：偏好保存与默认画质真正接线

- [ ] 新增 browser_settings.py，按 browser_react.py 的本地服务/fixture 方式提供 1080P、720P 候选，先验证设置 720P 后刷新仍保留且下一次解析默认 720P；初始 UI 无设置入口，此时测试应失败。
- [ ] settings.ts 实现上述纯函数；未知/损坏 JSON 在 App 初始化处 catch，normalizeSettings 拒绝非对象/数组及非法字段，采用字段级默认。localStorage 只读写 SETTINGS_KEY。
- [ ] App 保存函数先更新内存，然后尝试 JSON.stringify + setItem；成功与失败分别展示真实保存状态。恢复默认调用同一保存函数，禁止清空所有键。
- [ ] 在 parse 成功回调使用 preferredQualityId 计算 ID，并同步 media；恢复历史项目逻辑维持原选择，不套用新偏好。代码形状：

```ts
const id = preferredQualityId(result.qualities, result.default_quality_id,
  settings.qualityPreference);
setParsed(result);
setQuality(id);
setMedia(result.qualities.find(item => item.id === id)?.media || null);
```

- [ ] 补充 fixture 用例：1080 偏好仅有 720 时选 720；720 偏好仅有 1080 时选 1080；未知高度使用默认；选中未归档画质时不显示其他画质 media；空候选不可下载。
- [ ] 存储损坏通过 page.add_init_script 写入非法 JSON；不可写通过覆盖 Storage.prototype.setItem 抛 DOMException。两种情况均可继续解析，不出现未捕获错误；不可写时出现降级提示。
- [ ] 新增断言：恢复默认后其他 localStorage 键和项目文件仍存在；改变设置不取消正在运行的 prepare 请求。
- [ ] 运行 `npm --prefix frontend run typecheck` 和 `python -m unittest tests.test_quality tests.test_react_api -v`。

交付：偏好与画质已端到端接线，旧归档和 CLI 行为不变。

## Task 3：弹窗、完成提醒与可访问性

- [ ] Settings.tsx 使用原生 `<dialog>`、showModal()、关闭按钮与 cancel 事件；卸载关闭，避免 StrictMode 重复 showModal 异常。打开时聚焦设置控件，关闭后回到触发按钮；Tab 焦点不逃出弹窗。
- [ ] 设置控件用 label 关联 select/checkbox；保存状态用 role=status，失败提示不得只靠颜色。原有 config 加载失败时显示 configError，不伪造目录或“未就绪”。
- [ ] App 页头接入“设置”按钮；Icon.tsx 使用本地 SVG，不引入在线图标请求。CSS 延续现有视觉风格，在 390px 宽度可滚动但不横向溢出。
- [ ] App prepare 成功的 current() 分支中，当 completionReminder 为 true 时展示可关闭的页面内提示；不添加系统权限、计时器或通知服务。新解析、关闭提示时清除提醒；正常状态文字保持不变。
- [ ] Playwright 断言打开、Escape 关闭、焦点返回、键盘修改设置及移动布局；执行提醒开启/关闭、失败和过期响应用例。

关键断言（在 E2E 服务 fixture 建好后使用）：

```python
button = page.get_by_role('button', name='设置', exact=True)
button.click()
expect(page.get_by_role('dialog', name='设置', exact=True)).to_be_visible()
page.get_by_label('默认画质', exact=True).select_option('720p')
page.get_by_label('归档完成提醒', exact=True).check()
page.keyboard.press('Escape')
expect(button).to_be_focused()
page.reload()
button.click()
expect(page.get_by_label('默认画质', exact=True)).to_have_value('720p')
expect(page.get_by_label('归档完成提醒', exact=True)).to_be_checked()
```

- [ ] 保存说明明确显示两个位置的区别，以及“已有归档优先复用”；不提供并发数字或覆盖开关。

交付：完整可用设置入口，而不是只展示不能生效的控件。

## Task 4：回归、说明与交付

- [ ] README.md 增加第一版设置范围、仅当前浏览器保存偏好、换端口/浏览器不共享、恢复默认不删文件、归档目录只读、浏览器导出目录由浏览器控制的说明。
- [ ] 执行以下检查并保存结果；若运行环境缺依赖，明确报告，不自动安装全局工具或升级依赖。

```powershell
python -m unittest tests.test_react_api tests.test_quality tests.test_library -v
npm --prefix frontend run typecheck
npm --prefix frontend run build
python tests/browser_settings.py
python tests/browser_react.py
git diff --check
```

- [ ] E2E 使用临时归档根目录和本地视频 fixture，不发起真实平台下载、收费 AI 请求、系统通知或删除用户文件。
- [ ] 检查默认画质更改、当前任务不受影响、恢复历史、归档复用、浏览器导出、字幕与转录主流程无回归；截图复核桌面及 390px 设置面板。
- [ ] 浏览器控制台无新增未捕获错误；输出任何未通过或未运行的检查。
- [ ] 审查 git diff 只涉及列出的文件，不把原有未提交改动纳入提交。仅在用户明确要求提交时操作 Git 提交。

## 停止条件与当前状态

用户确认第一版范围后执行；满足以上验收即结束，不扩展为下载队列、目录迁移或通用设置框架。

此次只完成代码上下文读取与规划，未实施功能、未运行功能测试或构建。首要待确认项是：是否接受目录只读、同名规则说明、并发延期，以及提醒限定为页面内“归档完成”。
