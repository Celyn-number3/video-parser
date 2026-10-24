"""Workbench episode card regressions. Only synthetic projects/API writes are used."""
from pathlib import Path
import unittest
from urllib.parse import urlsplit

from playwright.sync_api import expect
from tests.browser import browser_learning_workflow as workflow


class EpisodeCardBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workflow.LearningWorkflowBrowserTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        workflow.LearningWorkflowBrowserTests.tearDownClass()

    def setUp(self):
        self.fixture = workflow.LearningWorkflowBrowserTests()
        self.fixture.setUp()
        self.page = self.fixture.page
        self.completed = set()
        self.count = 12
        self.writes = []
        self.fail_learning = False
        original = self.fixture.parsed
        self.fixture.parsed = lambda part, online=False: {**original(part, online), 'episodes': self.episodes()}
        self.fixture.fixture.context.unroute('**/*')
        self.fixture.fixture.context.route('**/*', self.route)
        self.output = Path(__file__).resolve().parents[2] / '.local/work/artifacts/episode-card'
        self.output.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.fixture.tearDown()

    def episodes(self):
        return [{'part': part, 'title': f'合成第{part}讲：分集学习与进度', 'duration': 20,
                 'project_id': self.fixture.identifier(part), 'archived': True,
                 'learned': part in self.completed} for part in range(1, self.count + 1)]

    def route(self, route):
        request = route.request
        url = urlsplit(request.url)
        if url.hostname == '127.0.0.1' and url.port == self.fixture.fixture.server.server_port and request.method == 'POST':
            if url.path.endswith('/learning') or url.path.endswith('/episodes/refresh'):
                body = request.post_data_json
                self.writes.append((url.path, body))
                if url.path.endswith('/learning'):
                    if self.fail_learning:
                        return route.fulfill(status=422, json={'detail': '合成保存失败，请重试'})
                    if body['learned']:
                        self.completed.add(body['part'])
                    else:
                        self.completed.discard(body['part'])
                return route.fulfill(json={'episodes': self.episodes()})
        return self.fixture.route(route)

    def open(self, width=1440):
        self.page.set_viewport_size({'width': width, 'height': 1100})
        self.page.goto(self.fixture.fixture.url + '?project=' + self.fixture.identifier(1))
        expect(self.page.locator('#project-context')).to_be_visible()

    def test_separate_cards_desktop_mobile_and_single_episode(self):
        for width in (1440, 390):
            with self.subTest(width=width):
                self.open(width)
                project = self.page.locator('#project-context')
                card = self.page.locator('.episode-learning-card')
                expect(project.get_by_role('button', name='生成字幕', exact=True)).to_have_count(0)
                expect(project.get_by_role('button', name='解析视频集数', exact=True)).to_be_visible()
                expect(project.locator('.learning-progress')).to_have_count(0)
                expect(card).to_be_visible()
                self.assertTrue(card.evaluate('(card) => card.previousElementSibling.id === "project-context"'))
                expect(card.get_by_role('heading', name='分集学习', exact=True)).to_have_count(1)
                if width == 390:
                    expect(card.get_by_role('list', name='分集列表')).to_be_hidden()
                    card.get_by_role('button', name='展开分集列表').click()
                expect(card.get_by_role('list', name='分集列表')).to_be_visible()
                a, b = project.bounding_box(), card.bounding_box()
                self.assertGreaterEqual(b['y'] - a['y'] - a['height'], 15)
                self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                self.page.screenshot(path=str(self.output / f'workbench-{width}.png'), full_page=True)
                self.page.locator('.study-context-rail').screenshot(path=str(self.output / f'cards-{width}.png'))
        self.count = 1
        self.open()
        expect(self.page.locator('.episode-learning-card')).to_have_count(0)
        expect(self.page.get_by_role('button', name='解析视频集数', exact=True)).to_be_visible()

    def test_search_completion_error_refresh_and_episode_switch(self):
        self.open()
        card = self.page.locator('.episode-learning-card')
        search = card.get_by_role('searchbox', name='定位分集')
        search.fill('P2')
        expect(card.locator('.learning-episode-row')).to_have_count(1)
        toggle = card.get_by_role('checkbox')
        toggle.click()  # State is committed after the save response, not optimistically.
        expect(toggle).to_be_checked()
        expect(card.get_by_role('progressbar')).to_have_attribute('aria-valuenow', '1')
        self.assertEqual(self.writes[-1][1], {'part': 2, 'learned': True})
        self.fail_learning = True
        toggle.click()  # Rejected save intentionally restores the checked state.
        expect(card.get_by_role('alert')).to_contain_text('合成保存失败')
        expect(toggle).to_be_checked()
        expect(toggle).to_be_enabled()
        self.fail_learning = False
        search.fill('没有这个标题')
        expect(card.get_by_role('status')).to_have_text('没有匹配分集。')
        search.press('Escape')
        expect(card.locator('.learning-episode-row')).to_have_count(12)
        self.page.get_by_role('button', name='解析视频集数', exact=True).click()
        expect(self.page.locator('.episode-refresh [role=status]')).to_have_text('已解析 12 集。')
        self.assertEqual(self.writes[-1][1], {'confirm': True})
        search.fill('P2')
        search.press('Enter')
        expect(card).to_contain_text('当前播放：P2')
        expect(card.get_by_role('progressbar')).to_have_attribute('aria-valuenow', '1')
        self.assertIn(('GET', '/projects/' + self.fixture.identifier(2) + '/resume'), self.fixture.calls)
        self.assertNotIn(('POST', '/parse'), self.fixture.calls)

    def test_learning_collapse_and_subtitle_entry_remain_available(self):
        self.fixture.open()
        expect(self.page.locator('.episode-learning-card')).to_have_count(0)
        expect(self.page.locator('#project-context .learning-progress')).to_be_visible()
        self.page.get_by_role('button', name='收起学习侧栏', exact=True).click()
        expect(self.page.locator('#project-context')).to_be_hidden()
        self.page.get_by_role('button', name='展开学习侧栏', exact=True).click()
        expect(self.page.locator('#project-context .learning-progress')).to_be_visible()
        self.page.get_by_role('button', name='视频工作台', exact=True).click()
        expect(self.page.locator('.episode-learning-card')).to_be_visible()
        self.page.get_by_role('tab', name='字幕与转写', exact=True).click()
        expect(self.page.locator('#subtitle-workpanel')).to_be_visible()
        expect(self.page.locator('.episode-learning-card')).to_be_hidden()
