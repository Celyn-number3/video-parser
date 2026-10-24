"""Isolated single-project completion and precise study-rail alignment; no live writes."""
import re
import unittest
from tests.browser.project_picker import select_project
from urllib.parse import urlsplit
from playwright.sync_api import expect
from tests.browser import browser_learning_workflow as workflow


def fixture_type():
    class Fixture(workflow.LearningWorkflowBrowserTests):
        def setUp(self):
            self.completed = {}; self.completion_calls = []; self.fail_completion = False
            self.no_part = False; self.resume_position = 0
            super().setUp()
        def project(self, part):
            value = super().project(part)
            value['learned'] = self.completed.get(part, False)
            if self.no_part and part == 3: value.update(part=None, platform='youtube')
            return value
        def parsed(self, part, online=False):
            value = super().parsed(part, online)
            value['episodes'] = [{**row, 'learned': self.completed.get(row['part'], False)} for row in value['episodes']]
            return value
        def route(self, route):
            req = route.request; url = urlsplit(req.url)
            if url.hostname == '127.0.0.1' and url.port == self.fixture.server.server_port:
                path = url.path.removeprefix('/api/workspace')
                match = re.fullmatch('/projects/([a-f0-9]{32})/learning', path)
                if match and req.method == 'POST':
                    owner = int(match[1], 16); body = req.post_data_json
                    self.completion_calls.append((owner, body))
                    if self.fail_completion: return route.fulfill(status=503, json={'detail': '模拟学习状态保存失败'})
                    expected = self.project(owner)['part'] or 1
                    assert body['part'] == expected and type(body['learned']) is bool, body
                    self.completed[owner] = body['learned']
                    return route.fulfill(json={'episodes': self.parsed(owner)['episodes'], 'learned': self.completed[owner]})
                if path.endswith('/study/progress'):
                    return route.fulfill(json={'position': self.resume_position if req.method == 'GET' else req.post_data_json['position'],
                        'duration': 20, 'revision': 0 if req.method == 'GET' else req.post_data_json['expected_revision'] + 1})
            return super().route(route)
    return Fixture


class LearningCompletionAlignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): workflow.LearningWorkflowBrowserTests.setUpClass()
    @classmethod
    def tearDownClass(cls): workflow.LearningWorkflowBrowserTests.tearDownClass()
    def setUp(self):
        self.f = fixture_type()('test_summary_does_not_hide_current_video_chapters'); self.f.setUp(); self.page = self.f.page
    def tearDown(self): self.f.tearDown()
    def toggle(self): return self.page.locator('.learning-header-completion').get_by_role('checkbox')
    def aligned(self):
        expect(self.page.locator('.chapter-timeline-player')).to_be_visible()
        self.page.wait_for_function("""() => {
            const a = document.querySelector('.chapter-timeline-player').getBoundingClientRect();
            const b = document.querySelector('#project-context').getBoundingClientRect();
            return a.height > 0 && b.height > 0 && Math.abs(a.top-b.top) < 1;
        }""")
        if self.page.locator('.playback-resume.is-empty').count():
            self.page.wait_for_function("""() => {
                const side=document.querySelector('.study-sidebar').getBoundingClientRect();
                const video=document.querySelector('#video-stage').getBoundingClientRect();
                return Math.abs(side.bottom-video.bottom) < 1;
            }""")
    def shot(self, name): self.page.screenshot(path=str(self.f.fixture.output / (name+'.png')), full_page=True)
    def test_single_completion_persists_reload_switch_and_cancel(self):
        self.f.open(3); expect(self.toggle()).to_be_visible(); expect(self.toggle()).not_to_be_checked()
        expect(self.page.locator('#project-context')).to_be_hidden()
        self.toggle().click(); expect(self.toggle()).to_be_checked(); expect(self.toggle()).to_be_enabled()
        self.page.reload(); expect(self.toggle()).to_be_checked()
        picker = self.page.get_by_role('combobox', name='学习项目', exact=True)
        select_project(picker, self.f.identifier(1)); expect(self.toggle()).not_to_be_checked()
        select_project(picker, self.f.identifier(3)); expect(self.toggle()).to_be_checked()
        self.toggle().click(); expect(self.toggle()).not_to_be_checked(); expect(self.toggle()).to_be_enabled()
        self.page.reload(); expect(self.toggle()).not_to_be_checked()
        self.assertEqual(self.f.completion_calls, [(3, {'part':3,'learned':True}), (3, {'part':3,'learned':False})])
        for width in (1440,390,280):
            self.page.set_viewport_size({'width':width,'height':1000}); expect(self.toggle()).to_be_visible()
            self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            self.shot('single-completion-'+str(width))
    def test_project_without_part_and_save_failure_does_not_fake_success(self):
        self.f.no_part = True; self.f.fail_completion = True; self.f.open(3)
        expect(self.toggle()).to_have_attribute('aria-label','当前这一讲 P1 已学完')
        self.toggle().click(); expect(self.page.get_by_role('alert').filter(has_text='模拟学习状态保存失败')).to_be_visible()
        expect(self.toggle()).not_to_be_checked(); expect(self.toggle()).to_be_enabled()
        self.f.fail_completion = False; self.toggle().click(); expect(self.toggle()).to_be_checked()
        self.page.reload(); expect(self.toggle()).to_be_checked()
        self.assertEqual(self.f.completion_calls[-1], (3, {'part':1,'learned':True}))
    def test_timeline_and_episode_card_align_with_and_without_resume_offer(self):
        for position in (0,7):
            self.f.resume_position = position
            for width in (1171,1280,1440,1720):
                with self.subTest(position=position,width=width):
                    self.page.set_viewport_size({'width':width,'height':1000}); self.f.open(1)
                    if position: expect(self.page.get_by_role('button',name='继续上次学习 · 00:07',exact=True)).to_be_visible()
                    self.aligned(); self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                    if width == 1440: self.shot('aligned-resume-'+str(position))
            if position:
                self.page.get_by_role('button',name='从头播放',exact=True).click()
                expect(self.page.get_by_role('button',name='从头播放',exact=True)).to_have_count(0); self.aligned()
    def test_alignment_survives_same_resource_episode_switch_collapse_and_mobile(self):
        self.page.set_viewport_size({'width':1440,'height':1000}); self.f.open(1); self.aligned()
        select_project(self.page.get_by_role('combobox',name='学习项目',exact=True), self.f.identifier(2))
        expect(self.toggle()).to_have_attribute('aria-label','当前这一讲 P2 已学完'); self.aligned()
        self.page.get_by_role('button',name='收起学习侧栏',exact=True).click(); expect(self.page.locator('#project-context')).to_be_hidden()
        self.page.get_by_role('button',name='展开学习侧栏',exact=True).click(); self.aligned()
        self.page.set_viewport_size({'width':390,'height':1000})
        expect(self.toggle()).to_be_visible(); self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
        self.shot('aligned-mobile')
