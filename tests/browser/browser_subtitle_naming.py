"""Synthetic naming UI regressions; every workspace API is intercepted, no real model/files."""
import copy
from pathlib import Path
import re
import unittest
from urllib.parse import urlsplit

from playwright.sync_api import expect
from tests.browser import browser_learning_workflow as learning


class SubtitleNamingBrowserTests(unittest.TestCase):
    plan_id = 'd' * 32
    task_ids = {'plan': 'a' * 32, 'apply': 'b' * 32, 'restore': 'c' * 32}

    @classmethod
    def setUpClass(cls):
        learning.LearningWorkflowBrowserTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        learning.LearningWorkflowBrowserTests.tearDownClass()

    def setUp(self):
        self.base = learning.LearningWorkflowBrowserTests('test_summary_does_not_hide_current_video_chapters')
        self.base.setUp()
        self.page = self.base.page
        self.calls = []
        self.reused = False
        self.plan_created = False
        self.plan_state = 'proposed'
        self.applied = False
        self.background = False
        self.finished = False
        self.cancelled = False
        self.failed_apply = False
        self.fail_preview = False
        self.foreign_plan = False
        self.fail_resume = False
        self.preview = None
        self.preview_count = 0
        self.hold_next_preview = False
        self.held_preview = None
        self.rename_scope = 'video_subtitles'
        self.unready_parts = set()
        self.fail_generate = False
        self.fail_apply_request = False
        self.adjusted_from = None
        self.saved_plans = {}
        self.applied_rows = None
        self.before_adjustment_rows = None
        self.fail_adjust = False
        self.operation = 'plan'
        self.rows = [{'project_id': self.base.identifier(part), 'number': f'1.{part}', 'title': title}
                     for part, title in [(1, '变量基础'), (2, '条件与类型')]]
        self.all_rows = copy.deepcopy(self.rows)
        original_project = self.base.project
        def project(part):
            value = original_project(part)
            if self.applied and part in (1, 2):
                row = self.applied_row(part)
                if row is not None:
                    value['episode_title'] = f'{row["number"]} {row["title"]}' if row['number'] else row['title']
            return value
        self.base.project = project
        self.original_entries = self.entries()
        self.base.fixture.context.unroute('**/*')
        self.base.fixture.context.route('**/*', self.route)

    def tearDown(self):
        self.base.tearDown()

    def applied_row(self, part):
        rows = self.applied_rows if self.applied_rows is not None else (self.preview or {'rows': self.rows})['rows']
        return next((row for row in rows if row['project_id'] == self.base.identifier(part)), None)

    def entries(self):
        return [{'project_id': self.base.identifier(part), 'part': part, 'title': self.base.project(part).get('episode_title') or f'合成第{part}讲',
                 'number': self.applied_row(part)['number'] if self.applied and self.applied_row(part) else '', 'transcript': None if part in self.unready_parts else 'subtitles/fixture.srt',
                 'transcript_filename': f'P0{part}_分集主题.srt',
                 'subtitle_files': [{'resource': 'subtitles/fixture.srt', 'source': 'subtitles/fixture.srt', 'filename': f'P0{part}_分集主题.srt'}],
                 'files': [{'resource': 'video/fixture.wav', 'source': 'video/fixture.wav', 'filename': 'fixture.wav'}]}
                for part in (1, 2)]

    def job(self, operation):
        state = 'completed'
        if operation == 'plan' and self.background and not self.finished: state = 'running'
        if operation == 'plan' and self.cancelled: state = 'cancelled'
        if operation == 'apply' and self.failed_apply: state = 'failed'
        return {'id': self.task_ids[operation], 'kind': 'naming', 'operation': operation, 'state': state,
                'phase': 'analyzing' if state == 'running' else state, 'project_id': self.base.identifier(1),
                'title': '合成课程甲', 'message': '合成命名任务进行中' if state == 'running' else '合成任务已取消，没有改名' if state == 'cancelled' else '合成任务结果',
                'result': {'plan_id': self.plan_id, 'state': self.plan_state}, 'progress': {}, 'created': 1}

    def public_plan(self):
        return {'id': self.plan_id, 'project_id': self.base.identifier(3 if self.foreign_plan else 1), 'title': '合成课程甲',
                'source': 'manual' if self.adjusted_from else 'subtitle' if self.reused else None, 'adjusted_from': self.adjusted_from,
                'rename_scope': self.rename_scope, 'state': self.plan_state, 'rows': self.rows if self.plan_state not in ('analyzing', 'failed') else [],
                'entries': self.original_entries, 'preview': self.preview, 'preview_token': (self.preview or {}).get('preview_token'),
                'job_id': None if self.adjusted_from and self.plan_state in ('proposed', 'validated') else self.task_ids[self.operation],
                'last_error': '合成中断，可恢复' if self.plan_state == 'recovery_required' else ''}

    def route(self, route):
        request = route.request; url = urlsplit(request.url)
        if url.hostname != '127.0.0.1' or url.port != self.base.fixture.server.server_port:
            return self.base.route(route)
        path = url.path.removeprefix('/api/workspace')
        if request.method == 'GET' and path == '/embedding/settings':
            return route.fulfill(json={'configured': False, 'base_url': '', 'model': '', 'key_saved': False})
        if request.method == 'GET' and path.endswith('/subtitle-cues'):
            return route.fulfill(json={'sources': [], 'resource': '', 'cues': []})
        if self.fail_resume and re.fullmatch(r'/projects/[a-f0-9]{32}/resume', path):
            return route.fulfill(status=404, json={'detail': '合成归档已不可用'})
        match = re.fullmatch(r'/naming/tasks/([a-f0-9]{32})', path)
        is_inventory = path == f'/projects/{self.base.identifier(1)}/naming'
        is_start = path == f'/projects/{self.base.identifier(1)}/naming/plan'
        is_reuse = path == f'/projects/{self.base.identifier(1)}/naming/reuse'
        is_adjust = path == f'/projects/{self.base.identifier(1)}/naming/adjust'
        is_plan = path.startswith(f'/naming/plans/{self.plan_id}')
        is_saved_plan = any(path == f'/naming/plans/{identifier}' for identifier in self.saved_plans)
        is_cancel = path == f'/tasks/naming/{self.task_ids["plan"]}/cancel'
        if not (match or is_inventory or is_start or is_reuse or is_adjust or is_plan or is_saved_plan or is_cancel): return self.base.route(route)
        body = request.post_data_json if request.post_data else None
        self.calls.append((request.method, path, body))
        if request.method == 'GET':
            if is_inventory:
                if getattr(self, 'fail_inventory', False): return route.fulfill(status=503, json={'detail': '合成分集读取失败。'})
                history = [{'id': self.plan_id, 'state': self.plan_state, 'created_at': '2026-10-17T01:00:00Z'}] if self.plan_created else []
                history += [{'id': item['id'], 'state': item['state'], 'created_at': '2026-10-17T00:59:00Z'} for item in self.saved_plans.values()]
                return route.fulfill(json={'title': getattr(self, 'inventory_title', '合成课程甲'), 'entries': self.entries(), 'subtitle_count': 2, 'ready_count': 2,
                                           'max_selected': getattr(self, 'max_selected', 150), 'fingerprint': 'fixture', 'history': history})
            if match:
                operation = next(key for key, value in self.task_ids.items() if value == match[1])
                if operation == 'plan' and self.finished and not self.cancelled and self.plan_state == 'analyzing': self.plan_state = 'proposed'
                return route.fulfill(json=self.job(operation))
            if path == f'/naming/plans/{self.plan_id}': return route.fulfill(json=self.public_plan())
            if is_saved_plan: return route.fulfill(json=self.saved_plans[path.rsplit('/', 1)[1]])
        if request.method == 'POST':
            if is_adjust:
                if self.fail_adjust: return route.fulfill(status=409, json={'detail': '合成来源已变化，未创建草稿。'})
                previous = copy.deepcopy(self.public_plan() if body['plan_id'] == self.plan_id else self.saved_plans[body['plan_id']])
                if previous['state'] != 'applied': return route.fulfill(status=409, json={'detail': '合成方案不是完成态。'})
                self.saved_plans[previous['id']] = previous
                self.before_adjustment_rows = copy.deepcopy((previous['preview'] or {}).get('rows') or previous['rows'])
                self.applied_rows = copy.deepcopy(self.before_adjustment_rows)
                self.rows = copy.deepcopy(self.before_adjustment_rows)
                selected = {row['project_id']: row for row in self.rows}
                self.original_entries = [copy.deepcopy(entry) for entry in previous['entries'] if entry['project_id'] in selected]
                moves = {(move['project_id'], move['resource']): move for move in (previous['preview'] or {}).get('moves', [])}
                for entry in self.original_entries:
                    row = selected[entry['project_id']]
                    entry.update(number=row['number'], title=(row['number'] + ' ' if row['number'] else '') + row['title'])
                    for file in entry['files']:
                        move = moves.get((entry['project_id'], file['resource']))
                        if move: file.update(source=move['target'], filename=move['target'].rsplit('/', 1)[-1])
                self.adjusted_from = previous['id']; self.plan_id = f'{100 + len(self.saved_plans):032x}'
                self.plan_state = 'proposed'; self.preview = None; self.reused = False
                return route.fulfill(status=201, json={'plan_id': self.plan_id, 'state': 'proposed'})
            if is_reuse:
                self.plan_created = True; self.reused = True
                self.rows = [{'project_id': self.base.identifier(part), 'number': '', 'title': f'P0{part}_分集主题'} for part in (1, 2)]
                return route.fulfill(status=201, json={'plan_id': self.plan_id, 'state': 'proposed'})
            if is_start:
                if self.fail_generate: return route.fulfill(status=503, json={'detail': '合成模型请求失败，不会自动重试。'})
                self.rows = copy.deepcopy([row for row in self.all_rows if row['project_id'] in body['selected_ids']])
                self.original_entries = [entry for entry in self.entries() if entry['project_id'] in body['selected_ids']]
                self.preview = None
                self.plan_created = True; self.operation = 'plan'; self.plan_state = 'analyzing' if self.background else 'proposed'
                self.base.fixture.jobs = [self.job('plan')]
                return route.fulfill(status=202, json=self.job('plan'))
            if is_cancel:
                self.cancelled = True; self.finished = True; self.plan_state = 'failed'
                return route.fulfill(json=self.job('plan'))
            if path.endswith('/preview'):
                if self.fail_preview: return route.fulfill(status=409, json={'detail': '合成目标重名，请编辑后重试；没有改名。'})
                self.preview_count += 1
                edited = copy.deepcopy(body['rows'])
                entries = {entry['project_id']: entry for entry in self.original_entries}
                moves = [{'project_id': row['project_id'], 'resource': 'video/fixture.wav', 'source': entries[row['project_id']]['files'][0]['source'],
                          'target': 'video/' + (row['number'] + ' ' if row['number'] else '') + row['title'] + '.wav'} for row in edited]
                moves += [{'project_id': row['project_id'], 'resource': 'subtitles/fixture.srt', 'source': 'subtitles/fixture.srt', 'target': 'subtitles/' + (row['number'] + ' ' if row['number'] else '') + row['title'] + '-B站平台字幕.srt'} for row in edited]
                self.preview = {'plan_id': self.plan_id, 'preview_token': f'{self.preview_count:032x}', 'rows': edited, 'moves': moves, 'fingerprint': 'fixture'}
                self.plan_state = 'validated'
                if self.hold_next_preview:
                    self.hold_next_preview = False
                    self.held_preview = (route, copy.deepcopy(self.preview))
                    return
                return route.fulfill(json=self.preview)
            if path.endswith('/apply'):
                if self.fail_apply_request: return route.fulfill(status=409, json={'detail': '合成来源文件已变化，未执行改名。'})
                if not body.get('confirm') or body.get('preview_token') != (self.preview or {}).get('preview_token'):
                    return route.fulfill(status=409, json={'detail': '合成预览令牌已失效。'})
                self.applied = True; self.operation = 'apply'; self.plan_state = 'applied'
                self.applied_rows = copy.deepcopy((self.preview or {'rows': self.rows})['rows'])
                return route.fulfill(status=202, json=self.job('apply'))
            if path.endswith('/restore'):
                self.applied = bool(self.adjusted_from); self.operation = 'restore'; self.plan_state = 'rolled_back'
                self.applied_rows = copy.deepcopy(self.before_adjustment_rows) if self.adjusted_from else None
                return route.fulfill(status=202, json=self.job('restore'))
        self.base.fixture.unexpected.append((request.method, path)); route.abort()

    def open(self):
        self.base.open()
        self.page.get_by_role('button', name='视频工作台', exact=True).click()
        self.page.get_by_role('tab', name='文件重命名', exact=True).click()
        self.dialog = self.page.get_by_role('region', name='文件重命名', exact=True)
        expect(self.dialog.get_by_role('heading', name='选择分集', exact=True)).to_be_visible()

    def suggest(self):
        self.dialog.get_by_role('button', name=re.compile('^(重新)?生成新名字$')).click()
        if not self.background and not self.fail_generate:
            expect(self.dialog.locator('.naming-rows input').first).to_be_visible()

    def validate(self):
        expect(self.dialog.get_by_role('region', name='真实文件改名预览')).to_be_visible()
        expect(self.dialog.get_by_role('button', name='确认并重命名', exact=True)).to_be_enabled()

    def count_post(self, suffix):
        return sum(method == 'POST' and path.endswith(suffix) for method, path, _ in self.calls)

    def from_task_center(self, operation='plan'):
        self.base.fixture.jobs = [self.job(operation)]
        self.page.get_by_role('button', name=re.compile('^任务中心')).click()
        self.page.get_by_role('button', name=re.compile('^查看命名(进度|记录)$')).click()
        expect(self.dialog).to_be_visible()
        expect(self.page.get_by_role('tab', name='文件重命名', exact=True)).to_have_attribute('aria-selected', 'true')

    def open_completed(self):
        self.plan_created = True; self.plan_state = 'applied'; self.applied = True; self.operation = 'apply'
        self.open(); self.from_task_center('apply')
        expect(self.dialog.get_by_role('heading', name='文件重命名完成', exact=True)).to_be_visible()

    def assert_removed(self):
        for text in ('撤销这次命名', '最近预览与恢复记录', '使用说明', '1 选择分集', '2 编辑建议', '3 确认改名'):
            expect(self.dialog.get_by_text(text, exact=True)).to_have_count(0)
        expect(self.dialog.locator('details, .naming-steps')).to_have_count(0)

    def assert_controls(self):
        expect(self.dialog.get_by_role('combobox', name='引擎与模型')).to_be_visible()
        expect(self.dialog.locator('.naming-scope')).to_be_visible()
        self.assertLess(self.dialog.locator('.naming-analysis').bounding_box()['y'], self.dialog.locator('.naming-scope').bounding_box()['y'])
        self.assert_removed()

    def test_inventory_failure_does_not_show_permanent_loading_or_mutate(self):
        self.fail_inventory = True; self.base.open()
        self.page.get_by_role('button', name='视频工作台', exact=True).click()
        self.page.get_by_role('tab', name='文件重命名', exact=True).click()
        panel = self.page.get_by_role('region', name='文件重命名', exact=True)
        expect(panel.get_by_role('alert')).to_contain_text('分集读取失败')
        expect(panel.get_by_role('status')).to_have_text('无法读取分集，请刷新页面重试。')
        self.assertEqual(self.count_post('/plan'), 0); self.assertEqual(self.count_post('/apply'), 0)

    def test_single_page_controls_remain_before_and_after_generation(self):
        self.open(); self.assert_controls()
        expect(self.dialog).to_contain_text('可能联网并产生费用')
        self.assertEqual(self.count_post('/plan'), 0)
        self.suggest(); self.validate(); self.assert_controls()
        expect(self.dialog.get_by_role('textbox', name='P1 新名称')).to_have_value('变量基础')
        expect(self.dialog.get_by_role('button', name='验证并预览最终文件名')).to_have_count(0)
        self.assertEqual(self.count_post('/plan'), 1); self.assertEqual(self.count_post('/apply'), 0)
        body = next(body for method, path, body in self.calls if method == 'POST' and path.endswith('/plan'))
        self.assertTrue(body['consent']); self.assertEqual(len(body['selected_ids']), 2)
        expect(self.dialog.get_by_role('region', name='真实文件改名预览')).to_contain_text('subtitles/1.1 变量基础-B站平台字幕.srt')

    def test_fourth_tab_preserves_draft_keyboard_navigation_and_no_learning_menu(self):
        self.open(); self.suggest(); self.validate()
        tabs = self.page.get_by_role('tablist', name='内容类型')
        expect(tabs.get_by_role('tab')).to_have_text(['视频', '字幕与转写', 'AI 分析', '文件重命名'])
        expect(tabs.get_by_role('tab', name='文件重命名')).to_have_attribute('aria-controls', 'naming-workpanel')
        expect(self.page.get_by_role('dialog', name='文件重命名')).to_have_count(0)
        self.dialog.get_by_role('textbox', name='P1 新名称').fill('保留的命名草稿')
        tabs.get_by_role('tab', name='视频', exact=True).click(); self.page.keyboard.press('End')
        expect(tabs.get_by_role('tab', name='文件重命名')).to_be_focused()
        expect(self.dialog.get_by_role('textbox', name='P1 新名称')).to_have_value('保留的命名草稿')
        self.page.get_by_role('button', name='学习视图', exact=True).click()
        expect(self.page.locator('.video-context-more')).to_have_count(0)
        expect(self.page.locator('#naming-workpanel')).to_be_hidden()
        self.page.get_by_role('button', name='视频工作台', exact=True).click()
        self.validate(); self.assert_controls()
        self.assertEqual(self.count_post('/plan'), 1); self.assertEqual(self.count_post('/apply'), 0)

    def test_fourth_tab_without_project_has_no_mutation(self):
        self.page.goto(self.base.fixture.url)
        self.page.get_by_role('tab', name='文件重命名', exact=True).click()
        panel = self.page.get_by_role('tabpanel', name='文件重命名', exact=True)
        expect(panel).to_contain_text('请先选择视频项目')
        expect(self.page.get_by_role('dialog')).to_have_count(0)
        expect(panel.get_by_role('button', name='返回视频', exact=True)).to_have_count(0)
        self.assertFalse(any(method == 'POST' for method, _, _ in self.calls))

    def test_only_explicit_confirmation_applies_and_refreshes_titles(self):
        self.open(); self.suggest(); self.validate()
        self.dialog.get_by_role('textbox', name='P1 新名称').fill('用户确认的标题')
        expect(self.dialog.get_by_role('button', name='确认并重命名')).to_be_disabled()
        self.validate()
        expect(self.dialog.get_by_role('region', name='真实文件改名预览')).to_contain_text('video/1.1 用户确认的标题.wav')
        self.assertEqual(self.count_post('/apply'), 0)
        self.dialog.get_by_role('button', name='确认并重命名').click()
        expect(self.dialog.get_by_role('heading', name='文件重命名完成')).to_be_visible()
        expect(self.page.locator('.video-context-heading')).to_contain_text('1.1 用户确认的标题')
        self.assert_controls()
        expect(self.dialog.locator('.naming-results li')).to_have_count(2)
        expect(self.dialog.get_by_role('textbox')).to_have_count(0)
        expect(self.dialog.get_by_role('button', name='恢复未完成操作')).to_have_count(0)
        applied = [body for method, path, body in self.calls if method == 'POST' and path.endswith('/apply')]
        self.assertEqual(len(applied), 1); self.assertTrue(applied[0]['confirm'])
        self.assertEqual(applied[0]['preview_token'], self.preview['preview_token'])
        self.assertEqual(self.count_post('/restore'), 0)

    def test_selection_before_generation_is_exact_and_missing_suggestions_block_apply(self):
        self.open()
        self.dialog.locator('.naming-scope input').nth(1).uncheck()
        self.suggest(); self.validate()
        expect(self.dialog.get_by_role('textbox', name='P2 新名称')).to_have_count(0)
        self.dialog.locator('.naming-scope input').nth(1).check()
        expect(self.dialog).to_contain_text('分集选择已变化，请重新生成新名字。')
        expect(self.dialog.get_by_role('button', name='确认并重命名')).to_be_disabled()
        expect(self.dialog.get_by_role('region', name='真实文件改名预览')).to_have_count(0)
        self.assertEqual(self.count_post('/plan'), 1)
        self.suggest(); self.validate()
        expect(self.dialog.get_by_role('textbox', name='P2 新名称')).to_have_value('条件与类型')
        selected = [body['selected_ids'] for method, path, body in self.calls if method == 'POST' and path.endswith('/plan')]
        self.assertEqual([len(ids) for ids in selected], [1, 2]); self.assertEqual(self.count_post('/apply'), 0)

    def test_deselecting_after_generation_validates_only_selected_subset(self):
        self.open(); self.suggest(); self.validate()
        self.dialog.locator('.naming-scope input').nth(1).uncheck(); self.validate()
        expect(self.dialog.get_by_role('textbox', name='P2 新名称')).to_have_count(0)
        self.dialog.get_by_role('button', name='确认并重命名').click()
        expect(self.dialog.get_by_role('heading', name='文件重命名完成')).to_be_visible()
        expect(self.dialog.locator('.naming-results li')).to_have_count(1)
        self.assertEqual([row['project_id'] for row in self.applied_rows], [self.base.identifier(1)])
        self.assertEqual(self.base.project(2), learning.LearningWorkflowBrowserTests.project(self.base, 2))
        # Selecting another episode for the next run must not claim it was already renamed.
        self.dialog.locator('.naming-scope input').nth(1).check()
        expect(self.dialog.locator('.naming-results li')).to_have_count(1)
        self.dialog.get_by_role('button', name='调整命名').click()
        expect(self.dialog.get_by_role('textbox', name='P1 新名称')).to_be_visible()
        expect(self.dialog.get_by_role('textbox', name='P2 新名称')).to_have_count(0)
        self.assertEqual(self.count_post('/apply'), 1)

    def test_empty_selection_and_missing_subtitles_never_start_model(self):
        self.unready_parts = {2}; self.open()
        expect(self.dialog.locator('.naming-scope input').nth(1)).to_be_disabled()
        expect(self.dialog).to_contain_text('缺少字幕，请先生成字幕')
        self.dialog.locator('.naming-scope input').first.uncheck()
        expect(self.dialog.get_by_role('button', name='生成新名字', exact=True)).to_be_disabled()
        self.assertEqual(self.count_post('/plan'), 0); self.assertEqual(self.count_post('/apply'), 0)

    def test_selection_limit_blocks_generation(self):
        self.max_selected = 1; self.open()
        expect(self.dialog).to_contain_text('一次最多选择 1 集。')
        expect(self.dialog.get_by_role('button', name='生成新名字', exact=True)).to_be_disabled()
        self.dialog.locator('.naming-scope input').nth(1).uncheck()
        expect(self.dialog.get_by_role('button', name='生成新名字', exact=True)).to_be_enabled()
        self.assertEqual(self.count_post('/plan'), 0)

    def test_model_change_preserves_episode_selection_and_never_auto_generates(self):
        self.open(); self.dialog.locator('.naming-scope input').nth(1).uncheck()
        picker = self.dialog.get_by_role('combobox', name='引擎与模型')
        picker.select_option('codex|codex-fixture')
        expect(self.dialog.locator('.naming-scope input').nth(1)).not_to_be_checked()
        self.assertEqual(self.count_post('/plan'), 0)
        self.suggest(); self.validate()
        body = next(body for method, path, body in self.calls if method == 'POST' and path.endswith('/plan'))
        self.assertEqual(body['agent']['engine'], 'codex'); self.assertEqual(body['selected_ids'], [self.base.identifier(1)])
        picker.select_option('api|')
        self.assertEqual(self.count_post('/plan'), 1); self.assertEqual(self.count_post('/apply'), 0)

    def test_preview_conflict_never_replays_model_and_can_retry_local_check(self):
        self.fail_preview = True; self.open(); self.suggest()
        expect(self.dialog.get_by_role('alert')).to_contain_text('目标重名')
        expect(self.dialog.get_by_role('button', name='确认并重命名')).to_be_disabled()
        self.fail_preview = False
        self.dialog.get_by_role('button', name='重新校验文件名').click(); self.validate()
        self.assertEqual(self.count_post('/plan'), 1); self.assertEqual(self.count_post('/apply'), 0)

    def test_stale_preview_response_cannot_authorize_newer_edit(self):
        self.open(); self.suggest(); self.validate()
        self.hold_next_preview = True
        title = self.dialog.get_by_role('textbox', name='P1 新名称')
        with self.page.expect_request(lambda request: request.method == 'POST' and request.url.endswith('/preview')):
            title.fill('旧的在途草稿')
        expect(self.dialog.get_by_text('正在校验文件名…', exact=True)).to_be_visible()
        self.assertIsNotNone(self.held_preview)
        title.fill('最新确认草稿'); self.validate()
        held, response = self.held_preview
        held.fulfill(json=response)
        expect(self.dialog.get_by_role('region', name='真实文件改名预览')).to_contain_text('最新确认草稿')
        expect(self.dialog.get_by_role('region', name='真实文件改名预览')).not_to_contain_text('旧的在途草稿')
        self.dialog.get_by_role('button', name='确认并重命名').click()
        expect(self.dialog.get_by_role('heading', name='文件重命名完成')).to_be_visible()
        self.assertNotEqual(next(body['preview_token'] for method, path, body in self.calls if method == 'POST' and path.endswith('/apply')), response['preview_token'])

    def test_generation_failure_does_not_auto_retry_or_modify_files(self):
        self.fail_generate = True; self.open(); self.suggest()
        expect(self.dialog.get_by_role('alert')).to_contain_text('模型请求失败')
        self.assert_controls()
        self.assertEqual(self.count_post('/plan'), 1); self.assertEqual(self.count_post('/apply'), 0)
        expect(self.dialog.get_by_role('button', name='确认并重命名')).to_have_count(0)

    def test_apply_conflict_does_not_retry_or_claim_completion(self):
        self.open(); self.suggest(); self.validate(); self.fail_apply_request = True
        self.dialog.get_by_role('button', name='确认并重命名').click()
        expect(self.dialog.get_by_role('alert')).to_contain_text('来源文件已变化')
        expect(self.dialog.get_by_role('heading', name='文件重命名完成')).to_have_count(0)
        self.assertEqual(self.count_post('/apply'), 1); self.assertEqual(self.count_post('/plan'), 1)
        self.assertFalse(self.applied)

    def test_adjust_preserves_previous_result_and_can_cancel_without_model_or_apply(self):
        self.open_completed()
        self.dialog.get_by_role('button', name='调整命名', exact=True).click()
        expect(self.dialog.get_by_role('textbox', name='P1 新名称')).to_have_value('变量基础')
        self.dialog.get_by_role('textbox', name='P1 新名称').fill('未确认的调整')
        self.validate(); self.assert_controls()
        self.dialog.get_by_role('button', name='取消调整', exact=True).click()
        expect(self.dialog.get_by_role('heading', name='文件重命名完成')).to_be_visible()
        expect(self.dialog.locator('.naming-results li').first).to_contain_text('变量基础')
        self.assertEqual(self.count_post('/adjust'), 1)
        for suffix in ('/plan', '/apply', '/restore'): self.assertEqual(self.count_post(suffix), 0)

    def test_adjust_requires_fresh_preview_then_explicit_confirmation(self):
        self.open(); self.suggest(); self.validate()
        self.dialog.get_by_role('button', name='确认并重命名').click()
        expect(self.dialog.get_by_role('heading', name='文件重命名完成')).to_be_visible()
        self.dialog.get_by_role('button', name='调整命名').click()
        self.dialog.get_by_role('textbox', name='P1 新名称').fill('二次修订')
        self.validate()
        self.assertEqual(self.count_post('/apply'), 1)
        self.dialog.get_by_role('button', name='确认并重命名').click()
        expect(self.page.locator('.video-context-heading')).to_contain_text('1.1 二次修订')
        applied = [body for method, path, body in self.calls if method == 'POST' and path.endswith('/apply')]
        self.assertEqual(len(applied), 2); self.assertNotEqual(applied[0]['preview_token'], applied[1]['preview_token'])
        self.assertEqual(self.count_post('/plan'), 1); self.assertEqual(self.count_post('/adjust'), 1)

    def test_adjust_failure_keeps_completed_result(self):
        self.open_completed(); self.fail_adjust = True
        self.dialog.get_by_role('button', name='调整命名').click()
        expect(self.dialog.get_by_role('alert')).to_contain_text('来源已变化')
        expect(self.dialog.locator('.naming-results li')).to_have_count(2)
        self.assertEqual(self.count_post('/plan'), 0); self.assertEqual(self.count_post('/apply'), 0)

    def test_existing_subtitle_plan_still_resumes_without_model_call(self):
        self.plan_created = True; self.reused = True
        self.rows = [{'project_id': self.base.identifier(part), 'number': '', 'title': f'P0{part}_分集主题'} for part in (1, 2)]
        self.open(); self.from_task_center(); self.validate()
        expect(self.dialog.get_by_role('textbox', name='P1 新名称')).to_be_disabled()
        expect(self.dialog.get_by_role('textbox', name='P1 新名称')).to_have_value('P01_分集主题')
        self.assertEqual(self.count_post('/plan'), 0); self.assertEqual(self.count_post('/apply'), 0)

    def test_task_center_restores_edited_preview_without_auto_applying(self):
        self.plan_created = True; self.plan_state = 'validated'
        self.preview = {'rows': [{**self.rows[0], 'title': '持久草稿'}], 'moves': [], 'preview_token': 'f' * 32, 'fingerprint': 'fixture'}
        self.open(); self.from_task_center(); self.validate()
        expect(self.dialog.get_by_role('textbox', name='P1 新名称')).to_have_value('持久草稿')
        expect(self.dialog.get_by_role('textbox', name='P2 新名称')).to_have_count(0)
        self.assert_controls()
        self.assertEqual(self.count_post('/plan'), 0); self.assertEqual(self.count_post('/apply'), 0)
        self.assertNotEqual(self.preview['preview_token'], 'f' * 32)

    def test_legacy_video_only_plan_cannot_apply_without_regeneration(self):
        self.plan_created = True; self.rename_scope = 'video'; self.open(); self.from_task_center()
        expect(self.dialog).to_contain_text('旧版仅视频预览')
        expect(self.dialog.get_by_role('button', name='确认并重命名')).to_be_disabled()
        self.assertEqual(self.count_post('/preview'), 0); self.assertEqual(self.count_post('/apply'), 0)

    def test_background_task_survives_navigation_and_resumes_from_task_center(self):
        self.background = True; self.open(); self.suggest()
        expect(self.dialog.get_by_role('region', name='命名任务状态')).to_contain_text('进行中')
        self.assert_controls()
        self.page.get_by_role('tab', name='视频', exact=True).click()
        self.assertEqual(self.count_post('/cancel'), 0)
        self.finished = True; self.from_task_center(); self.validate()
        expect(self.dialog.get_by_role('textbox', name='P1 新名称')).to_have_value('变量基础')
        self.assertEqual(self.count_post('/plan'), 1); self.assertEqual(self.count_post('/apply'), 0)

    def test_cancel_model_task_never_submits_file_operation(self):
        self.background = True; self.open(); self.suggest()
        self.dialog.get_by_role('button', name='取消任务').click()
        expect(self.dialog.get_by_role('heading', name='未生成建议，没有改名')).to_be_visible()
        expect(self.dialog.get_by_role('alert')).to_contain_text('已取消')
        self.assertEqual(self.count_post('/cancel'), 1); self.assertEqual(self.count_post('/apply'), 0)

    def test_only_incomplete_transaction_has_explicit_recovery(self):
        self.plan_created = True; self.failed_apply = True; self.operation = 'apply'
        self.plan_state = 'recovery_required'; self.applied = True
        self.open(); self.from_task_center('apply'); self.assert_removed()
        expect(self.dialog.get_by_role('button', name='重新生成新名字')).to_be_disabled()
        expect(self.dialog.get_by_role('button', name='恢复未完成操作')).to_be_disabled()
        self.dialog.get_by_label('确认恢复未完成操作的原文件名').check()
        self.dialog.get_by_role('button', name='恢复未完成操作').click()
        expect(self.dialog.get_by_role('heading', name='已恢复原命名')).to_be_visible()
        self.assertEqual(self.count_post('/plan'), 0); self.assertEqual(self.count_post('/apply'), 0)
        self.assertEqual(self.count_post('/restore'), 1)

    def test_missing_task_archive_stays_in_task_center_without_mutation(self):
        self.plan_created = True; self.base.fixture.jobs = [self.job('plan')]; self.open()
        self.page.get_by_role('button', name=re.compile('^任务中心')).click(); self.fail_resume = True
        self.page.get_by_role('button', name='查看命名记录', exact=True).click()
        expect(self.page.get_by_role('alert')).to_contain_text('无法从本地归档恢复命名任务对应的视频')
        expect(self.page.get_by_role('heading', name='任务中心', exact=True)).to_be_visible()
        self.assertEqual(self.count_post('/plan'), 0); self.assertEqual(self.count_post('/apply'), 0)

    def test_foreign_course_plan_is_rejected_before_edit_or_apply(self):
        self.plan_created = True; self.foreign_plan = True; self.open(); self.from_task_center()
        expect(self.dialog.get_by_role('alert')).to_contain_text('不属于当前课程')
        expect(self.dialog.get_by_role('textbox', name='P1 新名称')).to_have_count(0)
        self.assertEqual(self.count_post('/plan'), 0); self.assertEqual(self.count_post('/apply'), 0)

    def test_desktop_mobile_and_dark_screenshots_have_no_overflow(self):
        self.inventory_title = '麻省理工学院—线性代数课（完整版72讲）通俗易懂的课程'
        self.open(); self.suggest(); self.validate()
        artifacts = Path(__file__).resolve().parents[2] / '.local/work/artifacts/file-rename/synthetic'
        artifacts.mkdir(parents=True, exist_ok=True)
        for width, theme in ((1440, 'light'), (1440, 'dark'), (390, 'light'), (280, 'dark')):
            self.page.set_viewport_size({'width': width, 'height': 1000})
            self.page.evaluate('(theme) => document.documentElement.setAttribute("data-theme", theme)', theme)
            self.assert_controls()
            self.assertTrue(self.dialog.evaluate('e=>e.scrollWidth<=e.clientWidth+1'))
            self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'))
            self.page.screenshot(path=str(artifacts / f'{theme}-{width}.png'), full_page=True, animations='disabled')
        self.assertEqual(self.count_post('/apply'), 0)

    def test_english_ui_keeps_content_and_requires_explicit_apply(self):
        self.page.add_init_script("localStorage.setItem('vp-language', 'en')")
        self.page.goto(self.base.fixture.url + f'?project={self.base.identifier(1)}&page=learning')
        expect(self.page.get_by_role('combobox', name='Learning project', exact=True)).to_be_visible()
        self.page.locator('.nav-button').first.click()
        self.page.get_by_role('tab', name='File renaming', exact=True).click()
        dialog = self.page.get_by_role('region', name='File renaming', exact=True)
        expect(dialog).to_contain_text('incur charges')
        dialog.get_by_role('button', name='Generate new names', exact=True).click()
        expect(dialog.get_by_role('textbox', name='P1 new name')).to_have_value('变量基础')
        expect(dialog.get_by_role('region', name='Real-file rename preview')).to_be_visible()
        expect(dialog.get_by_role('button', name='Confirm and rename')).to_be_enabled()
        expect(dialog.locator('details')).to_have_count(0)
        self.assertEqual(self.count_post('/apply'), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
