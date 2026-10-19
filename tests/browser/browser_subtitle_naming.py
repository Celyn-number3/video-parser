"""Synthetic naming UI regressions; every workspace API is intercepted, no real model/files."""
import copy
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
        self.adjusted_from = None
        self.saved_plans = {}
        self.applied_rows = None
        self.before_adjustment_rows = None
        self.fail_adjust = False
        self.operation = 'plan'
        self.rows = [{'project_id': self.base.identifier(part), 'number': f'1.{part}', 'title': title}
                     for part, title in [(1, '变量基础'), (2, '条件与类型')]]
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
                 'number': self.applied_row(part)['number'] if self.applied and self.applied_row(part) else '', 'transcript': 'subtitles/fixture.srt',
                 'transcript_filename': f'P0{part}_分集主题.srt',
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
                'state': self.plan_state, 'rows': self.rows if self.plan_state not in ('analyzing', 'failed') else [],
                'entries': self.original_entries, 'preview': self.preview, 'preview_token': (self.preview or {}).get('preview_token'),
                'job_id': None if self.adjusted_from and self.plan_state in ('proposed', 'validated') else self.task_ids[self.operation],
                'last_error': '合成中断，可恢复' if self.plan_state == 'recovery_required' else ''}

    def route(self, route):
        request = route.request; url = urlsplit(request.url)
        if url.hostname != '127.0.0.1' or url.port != self.base.fixture.server.server_port:
            return self.base.route(route)
        path = url.path.removeprefix('/api/workspace')
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
                history = [{'id': self.plan_id, 'state': self.plan_state, 'created_at': '2026-10-17T01:00:00Z'}] if self.plan_created else []
                history += [{'id': item['id'], 'state': item['state'], 'created_at': '2026-10-17T00:59:00Z'} for item in self.saved_plans.values()]
                return route.fulfill(json={'title': getattr(self, 'inventory_title', '合成课程甲'), 'entries': self.entries(), 'subtitle_count': 2, 'ready_count': 2,
                                           'max_selected': 150, 'fingerprint': 'fixture', 'history': history})
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
                self.preview = {'plan_id': self.plan_id, 'preview_token': f'{self.preview_count:032x}', 'rows': edited, 'moves': moves, 'fingerprint': 'fixture'}
                self.plan_state = 'validated'
                return route.fulfill(json=self.preview)
            if path.endswith('/apply'):
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
        self.page.locator('.video-context-more > summary').click()
        self.page.get_by_role('button', name='字幕层级命名', exact=True).click()
        self.dialog = self.page.get_by_role('dialog', name='字幕层级命名', exact=True)
        expect(self.dialog).to_contain_text('可改名 2 讲')

    def suggest(self):
        button = self.dialog.get_by_role('button', name='生成命名建议', exact=True)
        expect(button).to_be_disabled()
        self.dialog.get_by_label(re.compile('同意本次由所选模型处理课程字幕')).check()
        expect(button).to_be_enabled(); button.click()
        if not self.background: expect(self.dialog.get_by_role('textbox', name='P1 语义标题')).to_have_value('变量基础')

    def validate(self):
        self.dialog.get_by_role('button', name='验证并预览最终文件名', exact=True).click()
        expect(self.dialog.get_by_role('region', name='真实文件改名预览')).to_be_visible()

    def count_post(self, suffix):
        return sum(method == 'POST' and path.endswith(suffix) for method, path, _ in self.calls)

    def open_completed(self):
        self.plan_created = True; self.plan_state = 'applied'; self.applied = True; self.operation = 'apply'
        self.open()
        self.dialog.locator('.naming-history summary').click()
        self.dialog.get_by_role('button', name=re.compile('^真实文件名已同步')).click()

    def open_restore(self):
        detail = self.dialog.locator('.naming-restore')
        if detail.get_attribute('open') is None:
            detail.locator('summary').click()

    def test_completed_six_rows_are_compact_readonly_and_details_are_opt_in(self):
        self.plan_created = True; self.plan_state = 'applied'; self.applied = True; self.operation = 'apply'
        self.rows = [{'project_id': self.base.identifier(i), 'number': f'1.{i}', 'title': f'第{i}讲的合成标题'} for i in range(1, 7)]
        self.original_entries = [{**copy.deepcopy(self.original_entries[0]), 'project_id': self.base.identifier(i), 'part': i} for i in range(1, 7)]
        self.open()
        self.dialog.locator('.naming-history summary').click()
        self.dialog.get_by_role('button', name=re.compile('^真实文件名已同步')).click()
        expect(self.dialog.get_by_role('heading', name='真实文件名已同步')).to_be_visible()
        expect(self.dialog.locator('.naming-results li')).to_have_count(6)
        expect(self.dialog.get_by_role('textbox')).to_have_count(0)
        expect(self.dialog.get_by_role('region', name='命名任务状态')).to_have_count(0)
        self.assertIsNone(self.dialog.locator('.naming-help').get_attribute('open'))
        self.assertIsNone(self.dialog.locator('.naming-restore').get_attribute('open'))
        for width in (1440, 760, 390, 280):
            self.page.set_viewport_size({'width': width, 'height': 900})
            self.assertTrue(self.dialog.evaluate('e=>e.scrollWidth<=e.clientWidth+1'), width)
        self.page.set_viewport_size({'width': 1440, 'height': 900})
        self.page.screenshot(path=str(self.base.fixture.output / 'naming-completed-compact.png'))
        self.page.evaluate("document.documentElement.setAttribute('data-theme','dark')")
        self.page.screenshot(path=str(self.base.fixture.output / 'naming-completed-dark.png'))
        self.assertFalse(any(method == 'POST' for method, _, _ in self.calls))
        self.dialog.get_by_role('button', name='调整命名', exact=True).click()
        expect(self.dialog.get_by_role('textbox')).to_have_count(12)
        expect(self.dialog.get_by_role('textbox', name='P1 语义标题')).to_have_value('第1讲的合成标题')
        expect(self.dialog.get_by_role('textbox', name='P1 语义标题')).to_be_focused()
        expect(self.dialog.get_by_role('button', name='生成命名建议', exact=True)).to_have_count(0)
        expect(self.dialog.get_by_role('region', name='真实文件改名预览')).to_have_count(0)
        for width in (390, 280):
            self.page.set_viewport_size({'width': width, 'height': 900})
            self.assertTrue(self.dialog.evaluate('e=>e.scrollWidth<=e.clientWidth+1'), width)
        self.assertEqual(self.count_post('/adjust'), 1)
        self.assertEqual(self.count_post('/plan'), 0); self.assertEqual(self.count_post('/apply'), 0)

    def test_completed_preview_uses_only_applied_subset_and_can_expand_paths(self):
        self.plan_created = True; self.plan_state = 'applied'; self.applied = True; self.operation = 'apply'
        self.preview = {'rows': self.rows[:1], 'moves': [{'project_id': self.rows[0]['project_id'], 'resource': 'video/fixture.wav',
            'source': 'video/fixture.wav', 'target': 'video/1.1 变量基础.wav'}], 'preview_token': 'f' * 32, 'fingerprint': 'fixture'}
        self.assertEqual(self.base.project(2), learning.LearningWorkflowBrowserTests.project(self.base, 2))
        self.open()
        self.dialog.locator('.naming-history summary').click()
        self.dialog.get_by_role('button', name=re.compile('^真实文件名已同步')).click()
        expect(self.dialog.locator('.naming-results li')).to_have_count(1)
        expect(self.dialog.get_by_role('region', name='真实文件改名预览')).to_be_hidden()
        self.dialog.locator('.naming-preview-details summary').click()
        expect(self.dialog.get_by_role('region', name='真实文件改名预览')).to_contain_text('video/1.1 变量基础.wav')
        self.open_restore()
        expect(self.dialog.get_by_role('button', name='恢复原命名', exact=True)).to_be_disabled()
        self.assertEqual(self.count_post('/apply'), 0); self.assertEqual(self.count_post('/restore'), 0)

        self.dialog.get_by_role('button', name='调整命名', exact=True).click()
        expect(self.dialog.get_by_role('textbox', name='P1 语义标题')).to_have_value('变量基础')
        expect(self.dialog.get_by_role('textbox', name='P2 语义标题')).to_have_count(0)
        self.dialog.get_by_role('button', name='取消调整', exact=True).click()
        expect(self.dialog.locator('.naming-results li')).to_have_count(1)
        expect(self.dialog.get_by_role('textbox')).to_have_count(0)

    def test_long_course_heading_keeps_the_close_button_on_one_line(self):
        self.inventory_title = '麻省理工学院—线性代数课（完整版72讲）通俗易懂，绝对是线性代数课程天花板！'
        self.open_completed()
        close = self.dialog.get_by_role('button', name='关闭字幕层级命名', exact=True)
        for width in (390, 280):
            self.page.set_viewport_size({'width': width, 'height': 900})
            value = close.evaluate("e=>{const r=document.createRange();r.selectNodeContents(e);const s=getComputedStyle(e);return {textHeight:r.getBoundingClientRect().height,lineHeight:parseFloat(s.lineHeight)||parseFloat(s.fontSize)*1.5}}")
            self.assertLessEqual(value['textHeight'], value['lineHeight'] + 1, (width, value))
            self.assertTrue(self.dialog.evaluate('e=>e.scrollWidth<=e.clientWidth+1'))

    def test_adjust_can_cancel_without_replaying_model_or_file_operations(self):
        self.rows[0].update(number='2.1', title='已经编辑过的标题')
        self.open_completed()
        previous_id = self.plan_id
        self.dialog.get_by_role('button', name='调整命名', exact=True).click()
        expect(self.dialog.get_by_role('textbox', name='P1 层级序号')).to_have_value('2.1')
        expect(self.dialog.get_by_role('textbox', name='P1 语义标题')).to_have_value('已经编辑过的标题')
        self.dialog.get_by_role('textbox', name='P1 语义标题').fill('未确认的草稿')
        self.dialog.get_by_role('button', name='取消调整', exact=True).click()
        expect(self.dialog.locator('.naming-results li').first).to_contain_text('已经编辑过的标题')
        expect(self.dialog.get_by_role('textbox')).to_have_count(0)
        expect(self.dialog.get_by_role('button', name='调整命名', exact=True)).to_be_enabled()
        self.assertEqual(self.saved_plans[previous_id]['state'], 'applied')
        self.assertEqual(self.count_post('/adjust'), 1)
        for suffix in ('/plan', '/reuse', '/preview', '/apply', '/restore'):
            self.assertEqual(self.count_post(suffix), 0, suffix)

    def test_adjust_requires_new_preview_and_confirmation_and_restores_prior_result(self):
        self.open(); self.suggest(); self.validate()
        self.dialog.get_by_label(re.compile('我已检查以上最终清单')).check()
        self.dialog.get_by_role('button', name='确认执行真实文件改名', exact=True).click()
        expect(self.dialog.get_by_role('heading', name='真实文件名已同步')).to_be_visible()
        self.dialog.get_by_role('button', name='调整命名', exact=True).click()
        expect(self.dialog.get_by_role('textbox', name='P1 语义标题')).to_have_value('变量基础')
        expect(self.dialog.get_by_role('region', name='真实文件改名预览')).to_have_count(0)
        self.dialog.get_by_role('textbox', name='P1 语义标题').fill('二次修订')
        self.validate()
        expect(self.dialog.get_by_label(re.compile('我已检查以上最终清单'))).not_to_be_checked()
        expect(self.dialog.get_by_role('button', name='确认执行真实文件改名', exact=True)).to_be_disabled()
        self.dialog.get_by_label(re.compile('我已检查以上最终清单')).check()
        self.dialog.get_by_role('textbox', name='P1 语义标题').fill('二次修订的最终版')
        expect(self.dialog.get_by_role('region', name='真实文件改名预览')).to_have_count(0)
        self.validate()
        expect(self.dialog.get_by_label(re.compile('我已检查以上最终清单'))).not_to_be_checked()
        self.dialog.get_by_label(re.compile('我已检查以上最终清单')).check()
        self.dialog.get_by_role('button', name='确认执行真实文件改名', exact=True).click()
        expect(self.page.locator('.video-context-heading')).to_contain_text('1.1 二次修订的最终版')
        self.open_restore()
        expect(self.dialog.get_by_role('button', name='恢复原命名', exact=True)).to_be_disabled()
        self.dialog.get_by_label(re.compile('确认恢复这次操作前')).check()
        self.dialog.get_by_role('button', name='恢复原命名', exact=True).click()
        expect(self.page.locator('.video-context-heading')).to_contain_text('1.1 变量基础')
        expect(self.dialog.locator('.naming-results li').first).not_to_contain_text('1.1 1.1')
        self.assertEqual(self.count_post('/plan'), 1); self.assertEqual(self.count_post('/adjust'), 1)
        applied = [body for method, path, body in self.calls if method == 'POST' and path.endswith('/apply')]
        self.assertEqual(len(applied), 2)
        self.assertNotEqual(applied[0]['preview_token'], applied[1]['preview_token'])
        self.assertTrue(all(body['confirm'] is True for body in applied))

    def test_adjusted_validated_draft_resumes_from_history_without_model_request(self):
        self.open_completed()
        self.dialog.get_by_role('button', name='调整命名', exact=True).click()
        self.dialog.get_by_role('textbox', name='P1 语义标题').fill('可恢复的调整草稿')
        self.validate()
        self.dialog.get_by_label(re.compile('我已检查以上最终清单')).check()
        self.dialog.get_by_role('button', name='关闭字幕层级命名').click()
        self.page.locator('.video-context-more > summary').click()
        self.page.get_by_role('button', name='字幕层级命名', exact=True).click()
        self.dialog.locator('.naming-history summary').click()
        self.dialog.get_by_role('button', name=re.compile('^已验证，尚未改名')).click()
        expect(self.dialog.get_by_role('textbox', name='P1 语义标题')).to_have_value('可恢复的调整草稿')
        expect(self.dialog.get_by_label(re.compile('我已检查以上最终清单'))).not_to_be_checked()
        expect(self.dialog.get_by_role('button', name='确认执行真实文件改名', exact=True)).to_be_disabled()
        self.assertEqual(self.count_post('/plan'), 0); self.assertEqual(self.count_post('/apply'), 0)

    def test_adjust_subtitle_result_becomes_editable_without_model_consent(self):
        self.open()
        self.dialog.get_by_role('button', name='复用字幕名生成视频改名预览', exact=True).click()
        self.dialog.get_by_label(re.compile('我已检查以上最终清单')).check()
        self.dialog.get_by_role('button', name='确认执行真实文件改名', exact=True).click()
        expect(self.dialog.get_by_role('heading', name='真实文件名已同步')).to_be_visible()
        self.dialog.get_by_role('button', name='调整命名', exact=True).click()
        title = self.dialog.get_by_role('textbox', name='P1 语义标题')
        expect(title).to_be_enabled(); expect(title).to_have_value('P01_分集主题')
        expect(self.dialog.get_by_role('textbox', name='P1 层级序号')).to_have_value('')
        title.fill('手动字幕标题'); self.validate()
        expect(self.dialog.get_by_role('region', name='真实文件改名预览')).to_contain_text('video/手动字幕标题.wav')
        expect(self.dialog.get_by_role('button', name='确认执行真实文件改名', exact=True)).to_be_disabled()
        self.assertEqual(self.count_post('/reuse'), 1); self.assertEqual(self.count_post('/adjust'), 1)
        self.assertEqual(self.count_post('/plan'), 0)

    def test_adjust_failure_preserves_the_completed_view(self):
        self.open_completed(); self.fail_adjust = True
        self.dialog.get_by_role('button', name='调整命名', exact=True).click()
        expect(self.dialog.get_by_role('alert')).to_contain_text('来源已变化')
        expect(self.dialog.locator('.naming-results li')).to_have_count(2)
        expect(self.dialog.get_by_role('textbox')).to_have_count(0)
        self.assertEqual(self.count_post('/plan'), 0); self.assertEqual(self.count_post('/apply'), 0)

    def test_english_adjust_prefills_content_and_can_cancel(self):
        self.plan_created = True; self.plan_state = 'applied'; self.applied = True; self.operation = 'apply'
        self.page.add_init_script("localStorage.setItem('vp-language', 'en')")
        self.page.goto(self.base.fixture.url + f'?project={self.base.identifier(1)}&page=learning')
        expect(self.page.get_by_role('combobox', name='Learning project', exact=True)).to_be_visible()
        self.page.locator('.video-context-more > summary').click()
        self.page.get_by_role('button', name='Subtitle hierarchy naming', exact=True).click()
        dialog = self.page.get_by_role('dialog', name='Subtitle hierarchy naming', exact=True)
        dialog.locator('.naming-history summary').click(); dialog.locator('.naming-history button').first.click()
        dialog.get_by_role('button', name='Adjust naming', exact=True).click()
        expect(dialog.get_by_role('textbox', name='P1 descriptive title')).to_have_value('变量基础')
        expect(dialog.get_by_role('textbox', name='P1 hierarchy number')).to_have_attribute('placeholder', 'Optional')
        expect(dialog).to_contain_text('without another model call')
        dialog.get_by_role('button', name='Cancel adjustment', exact=True).click()
        expect(dialog.get_by_role('list', name='Naming results')).to_be_visible()
        expect(dialog.get_by_role('textbox')).to_have_count(0)
        self.assertEqual(self.count_post('/plan'), 0); self.assertEqual(self.count_post('/apply'), 0)

    def test_reuse_subtitle_names_without_model_consent_syncs_heading_and_picker(self):
        self.open()
        self.dialog.get_by_role('button', name='复用字幕名生成视频改名预览', exact=True).click()
        expect(self.dialog.get_by_role('textbox', name='P1 语义标题')).to_have_value('P01_分集主题')
        expect(self.dialog.get_by_role('textbox', name='P1 语义标题')).to_be_disabled()
        expect(self.dialog.get_by_role('textbox', name='P1 层级序号')).to_have_count(0)
        expect(self.dialog.get_by_role('region', name='真实文件改名预览')).to_be_visible()
        expect(self.dialog.get_by_role('region', name='真实文件改名预览')).to_contain_text('video/P01_分集主题.wav')
        expect(self.dialog.get_by_role('button', name='确认执行真实文件改名', exact=True)).to_be_disabled()
        self.dialog.get_by_label(re.compile('我已检查以上最终清单')).check()
        self.dialog.get_by_role('button', name='确认执行真实文件改名', exact=True).click()
        expect(self.dialog.get_by_role('heading', name='真实文件名已同步')).to_be_visible()
        expect(self.page.locator('.video-context-heading strong')).to_have_text('P01_分集主题')
        expect(self.page.get_by_role('combobox', name='学习项目', exact=True).locator('option:checked')).to_have_text(re.compile('^P01_分集主题'))
        self.assertEqual(self.count_post('/reuse'), 1)
        self.assertEqual(self.count_post('/plan'), 0)
        self.open_restore()
        self.dialog.get_by_label(re.compile('确认恢复这次操作前')).check()
        self.dialog.get_by_role('button', name='恢复原命名', exact=True).click()
        expect(self.dialog.get_by_role('heading', name='已恢复原命名')).to_be_visible()
        expect(self.page.locator('.video-context-heading strong')).to_have_text('合成课程甲')

    def test_open_requires_consent_and_has_no_mutation_or_overflow(self):
        self.open()
        expect(self.dialog.get_by_role('button', name='生成命名建议', exact=True)).to_be_disabled()
        for width in (1440, 760, 390, 280):
            self.page.set_viewport_size({'width': width, 'height': 900})
            self.assertTrue(self.dialog.evaluate('(e) => e.scrollWidth <= e.clientWidth + 1'), width)
            self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), width)
        self.dialog.get_by_role('button', name='关闭字幕层级命名').click()
        self.assertFalse(any(method == 'POST' for method, _, _ in self.calls))

    def test_edited_preview_explicit_apply_refreshes_titles_and_can_restore(self):
        self.open(); self.suggest()
        self.dialog.get_by_role('textbox', name='P1 层级序号').fill('2.2.1')
        self.dialog.get_by_role('textbox', name='P1 语义标题').fill('基础类型')
        self.validate()
        expect(self.dialog.get_by_role('region', name='真实文件改名预览')).to_contain_text('2.2.1 基础类型.wav')
        apply = self.dialog.get_by_role('button', name='确认执行真实文件改名', exact=True)
        expect(apply).to_be_disabled(); self.assertEqual(self.count_post('/apply'), 0)
        self.dialog.get_by_label(re.compile('我已检查以上最终清单')).check(); apply.click()
        expect(self.dialog.get_by_role('heading', name='真实文件名已同步')).to_be_visible()
        expect(self.page.locator('.video-context-heading')).to_contain_text('2.2.1 基础类型')
        self.open_restore()
        expect(self.dialog.get_by_role('button', name='恢复原命名', exact=True)).to_be_disabled()
        self.open_restore()
        self.dialog.get_by_label(re.compile('确认恢复这次操作前')).check()
        self.dialog.get_by_role('button', name='恢复原命名', exact=True).click()
        expect(self.dialog.get_by_role('heading', name='已恢复原命名')).to_be_visible()
        expect(self.page.locator('.video-context-heading')).not_to_contain_text('2.2.1 基础类型')
        self.assertEqual(self.count_post('/plan'), 1); self.assertEqual(self.count_post('/apply'), 1); self.assertEqual(self.count_post('/restore'), 1)
        start = next(body for method, path, body in self.calls if method == 'POST' and path.endswith('/plan'))
        self.assertIs(start['consent'], True)
        self.assertEqual(start['selected_ids'], [self.base.identifier(1), self.base.identifier(2)])
        applied = next(body for _, path, body in self.calls if path.endswith('/apply'))
        self.assertEqual(applied, {'confirm': True, 'preview_token': f'{1:032x}'})

    def test_edit_invalidates_confirmation_and_validation_failure_does_not_replay_model(self):
        self.open(); self.suggest(); self.validate()
        self.dialog.get_by_label(re.compile('我已检查以上最终清单')).check()
        self.dialog.get_by_role('textbox', name='P1 语义标题').fill('修订后的合成标题')
        expect(self.dialog.get_by_role('region', name='真实文件改名预览')).to_have_count(0)
        self.fail_preview = True
        self.dialog.get_by_role('button', name='验证并预览最终文件名', exact=True).click()
        expect(self.dialog.get_by_role('alert')).to_contain_text('合成目标重名')
        expect(self.dialog.get_by_role('textbox', name='P1 语义标题')).to_have_value('修订后的合成标题')
        self.fail_preview = False; self.validate()
        expect(self.dialog.get_by_label(re.compile('我已检查以上最终清单'))).not_to_be_checked()
        expect(self.dialog.get_by_role('button', name='确认执行真实文件改名', exact=True)).to_be_disabled()
        self.assertEqual(self.count_post('/plan'), 1); self.assertEqual(self.count_post('/apply'), 0)

    def test_background_task_survives_close_and_resumes_from_task_center(self):
        self.background = True; self.open(); self.suggest()
        expect(self.dialog.get_by_role('region', name='命名任务状态')).to_contain_text('进行中')
        self.dialog.get_by_role('button', name='关闭字幕层级命名').click()
        expect(self.dialog).to_have_count(0)
        self.assertEqual(self.count_post('/cancel'), 0)
        self.page.get_by_role('button', name=re.compile('^任务中心')).click()
        expect(self.page.get_by_role('button', name='查看命名进度', exact=True)).to_be_visible()
        self.finished = True
        self.page.get_by_role('button', name='查看命名进度', exact=True).click()
        expect(self.dialog).to_be_visible()
        expect(self.dialog.get_by_role('textbox', name='P1 语义标题')).to_have_value('变量基础')
        self.assertEqual(self.count_post('/plan'), 1); self.assertEqual(self.count_post('/apply'), 0)

    def test_cancel_model_job_never_submits_file_operation(self):
        self.background = True; self.open(); self.suggest()
        self.dialog.get_by_role('button', name='取消任务', exact=True).click()
        expect(self.dialog.get_by_role('heading', name='未生成建议，没有改名')).to_be_visible()
        expect(self.dialog.get_by_role('alert')).to_contain_text('已取消')
        self.assertEqual(self.count_post('/cancel'), 1); self.assertEqual(self.count_post('/apply'), 0)
        self.assertEqual(self.count_post('/plan'), 1)

    def test_interrupted_history_can_restore_without_calling_model(self):
        self.plan_created = True; self.failed_apply = True; self.operation = 'apply'
        self.plan_state = 'recovery_required'; self.applied = True
        self.open()
        self.dialog.get_by_text('最近预览与恢复记录', exact=True).click()
        self.dialog.get_by_role('button', name=re.compile('^需要恢复原命名')).click()
        expect(self.dialog.get_by_role('heading', name='需要恢复原命名')).to_be_visible()
        self.open_restore()
        self.dialog.get_by_label(re.compile('确认恢复这次操作前')).check()
        self.dialog.get_by_role('button', name='恢复原命名', exact=True).click()
        expect(self.dialog.get_by_role('heading', name='已恢复原命名')).to_be_visible()
        self.assertEqual(self.count_post('/plan'), 0); self.assertEqual(self.count_post('/apply'), 0); self.assertEqual(self.count_post('/restore'), 1)

    def test_missing_task_archive_shows_error_on_task_page_without_file_or_model_request(self):
        self.plan_created = True; self.base.fixture.jobs = [self.job('plan')]
        self.open()
        self.dialog.get_by_role('button', name='关闭字幕层级命名').click()
        self.page.get_by_role('button', name=re.compile('^任务中心')).click()
        self.fail_resume = True
        self.page.get_by_role('button', name='查看命名记录', exact=True).click()
        expect(self.page.get_by_role('alert')).to_contain_text('无法从本地归档恢复命名任务对应的视频')
        expect(self.page.get_by_role('heading', name='任务中心', exact=True)).to_be_visible()
        expect(self.dialog).to_have_count(0)
        self.assertEqual(self.count_post('/plan'), 0); self.assertEqual(self.count_post('/apply'), 0)

    def test_foreign_course_plan_is_rejected_before_editor_or_apply(self):
        self.plan_created = True; self.foreign_plan = True
        self.open()
        self.dialog.get_by_text('最近预览与恢复记录', exact=True).click()
        self.dialog.get_by_role('button', name=re.compile('^待编辑与验证')).click()
        expect(self.dialog.get_by_role('alert')).to_contain_text('不属于当前课程')
        expect(self.dialog.get_by_role('textbox', name='P1 语义标题')).to_have_count(0)
        self.assertEqual(self.count_post('/plan'), 0); self.assertEqual(self.count_post('/apply'), 0)


    def test_english_naming_ui_keeps_course_titles_and_requires_consent(self):
        self.page.add_init_script("localStorage.setItem('vp-language', 'en')")
        self.page.goto(self.base.fixture.url + f'?project={self.base.identifier(1)}&page=learning')
        expect(self.page.get_by_role('combobox', name='Learning project', exact=True)).to_be_visible()
        self.page.locator('.video-context-more > summary').click()
        self.page.get_by_role('button', name='Subtitle hierarchy naming', exact=True).click()
        dialog = self.page.get_by_role('dialog', name='Subtitle hierarchy naming', exact=True)
        expect(dialog).to_be_visible()
        expect(dialog).to_contain_text('合成课程甲')
        button = dialog.get_by_role('button', name='Generate naming suggestions', exact=True)
        expect(button).to_be_disabled()
        dialog.get_by_label(re.compile('Allow the selected model to process course subtitles')).check()
        button.click()
        expect(dialog.get_by_role('textbox', name='P1 descriptive title', exact=True)).to_have_value('变量基础')
        expect(dialog.get_by_role('textbox', name='P1 hierarchy number', exact=True)).to_have_value('1.1')
        dialog.get_by_role('button', name='Validate and preview final filenames', exact=True).click()
        expect(dialog.get_by_role('region', name='Real-file rename preview', exact=True)).to_be_visible()
        expect(dialog.get_by_role('button', name='Confirm real-file renaming', exact=True)).to_be_disabled()
        self.assertEqual(self.count_post('/apply'), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
