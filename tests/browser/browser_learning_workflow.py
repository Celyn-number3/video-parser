"""Synthetic-only learning context regressions; all workspace APIs are intercepted."""
import io
import re
import unittest
import wave
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect
from tests.browser import browser_product_improvements as harness


class LearningWorkflowBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.ProductImprovementsBrowserTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        harness.ProductImprovementsBrowserTests.tearDownClass()

    def setUp(self):
        self.fixture = harness.ProductImprovementsBrowserTests('test_settings_cross_tab_updates')
        self.fixture.setUp()
        self.fixture.jobs = []
        self.fixture.with_media = True
        self.calls = []
        self.empty_parts = set()
        audio = io.BytesIO()
        with wave.open(audio, 'wb') as clip:
            clip.setnchannels(1)
            clip.setsampwidth(2)
            clip.setframerate(8000)
            clip.writeframes(b'\0\0' * 8000 * 20)
        self.fixture.audio = audio.getvalue()
        self.page = self.fixture.page
        self.fixture.context.unroute('**/*')
        self.fixture.context.route('**/*', self.route)

    def tearDown(self):
        self.fixture.tearDown()

    @staticmethod
    def identifier(part):
        return f'{part:032x}'

    @staticmethod
    def record_id(part, template):
        return f'20261017-10000{1 if template == "timeline" else 0}-{part:08x}'

    def project(self, part):
        return {**self.fixture.project(), 'id': self.identifier(part), 'part': part,
                'video_id': 'BV1TaqYBcEJc' if part < 3 else 'BV1TaqYBcEJa',
                'title': '合成课程甲' if part < 3 else '合成课程乙',
                'resources': [{'path': 'video/fixture.wav', 'kind': 'video',
                               'size_bytes': len(self.fixture.audio), 'url': f'/learning-fixture-{part}.wav'}]}

    def parsed(self, part, online=False):
        media = {**self.fixture.media(), 'duration': 20, 'preview_url': f'/learning-fixture-{part}.wav',
                 'quality_id': '720p', 'resource': 'video/fixture.wav'}
        qualities = [{'id': '720p', 'label': '720p', 'width': 1280, 'height': 720, 'media': media}]
        if online:
            qualities.insert(0, {'id': '1080p', 'label': '1080p', 'width': 1920, 'height': 1080, 'media': None})
        return {**self.fixture.parsed(), 'id': self.identifier(part), 'project': self.project(part),
                'title': self.project(part)['title'], 'source_url': f'https://www.bilibili.com/video/BV1TaqYBcEJc?p={part}',
                'media': None if online else media, 'qualities': qualities,
                'default_quality_id': qualities[0]['id'], 'duration': 20,
                'episodes': [{'part': index, 'title': f'合成第{index}讲', 'duration': 20,
                              'project_id': self.identifier(index), 'archived': True, 'learned': False}
                             for index in (1, 2)] if part < 3 else []}

    def records(self, part):
        if part in self.empty_parts:
            return []
        return [{'id': self.record_id(part, template), 'template': template,
                 'template_name': '章节时间轴' if template == 'timeline' else '内容摘要',
                 'text': f'## 00:00 第{part}集开场\n说明。\n## 00:05 第{part}集概念\n解释。'
                         if template == 'timeline' else f'这是第{part}集自己的摘要。',
                 'video_resource': 'video/fixture.wav', 'source': 'transcript', 'source_label': '只用字幕',
                 'transcript_label': '合成字幕', 'frame_count': 0, 'frames': [], 'followups': [],
                 'usage': {}, 'model': 'fixture', 'prompt': '', 'created_at': '2026-10-17T01:00:00Z'}
                for template in ('summary', 'timeline')]

    def route(self, route):
        request = route.request
        url = urlsplit(request.url)
        if url.hostname != '127.0.0.1' or url.port != self.fixture.server.server_port:
            return self.fixture.route(route)
        if re.fullmatch('/learning-fixture-[123].wav', url.path):
            return route.fulfill(content_type='audio/wav', body=self.fixture.audio)
        path = url.path.removeprefix('/api/workspace')
        self.calls.append((request.method, path))
        match = re.match(r'/projects/([a-f0-9]{32})(/.*)?$', path)
        part = int(match[1], 16) if match else None
        suffix = match[2] or '' if match else ''
        if request.method == 'GET':
            if path == '/projects':
                return route.fulfill(json={'projects': [{key: value for key, value in {
                    **self.project(index), 'archived': True, 'created_at': '',
                }.items() if key in ('id', 'title', 'platform', 'part', 'location', 'created_at', 'video_id', 'episode_title', 'archived')}
                    for index in (1, 2, 3)]})
            if suffix == '/resume':
                return route.fulfill(json=self.parsed(part))
            if suffix == '/analyses':
                return route.fulfill(json={'records': self.records(part)})
        if request.method == 'POST' and path == '/parse':
            source = request.post_data_json['text']
            part = int(parse_qs(urlsplit(source).query).get('p', ['1'])[0])
            return route.fulfill(json=self.parsed(part, online=True))
        return self.fixture.route(route)

    def open(self, part=1):
        self.page.goto(self.fixture.url + f'?project={self.identifier(part)}&page=learning')
        expect(self.page.locator('video')).to_be_visible()
        expect(self.page.get_by_role('combobox', name='选择学习材料', exact=True)).to_be_visible()

    def choose_part(self, part):
        self.page.get_by_role('button', name=re.compile(rf'^P{part}\s')).click()
        expect(self.page.get_by_label(f'当前这一讲 P{part} 已学完', exact=True)).to_be_visible()

    def test_summary_does_not_hide_current_video_chapters(self):
        self.open()
        choices = self.page.get_by_role('combobox', name='选择学习材料', exact=True)
        choices.select_option(self.record_id(1, 'timeline'))
        expect(self.page.locator('.chapter-timeline-player')).to_be_visible()
        choices.select_option(self.record_id(1, 'summary'))
        expect(self.page.locator('.analysis-record')).to_contain_text('第1集自己的摘要')
        expect(self.page.locator('.chapter-timeline-player')).to_be_visible()
        expect(self.page.get_by_role('complementary', name='学习侧栏')).to_contain_text('第1集概念')

    def test_compact_learning_layout_brings_materials_into_the_first_screen(self):
        self.page.set_viewport_size({'width': 1440, 'height': 1000})
        self.open()
        self.page.get_by_role('combobox', name='选择学习材料', exact=True).select_option(self.record_id(1, 'summary'))
        expect(self.page.get_by_role('group', name='学习项目切换')).to_have_attribute('aria-busy', 'false')
        self.page.evaluate('window.scrollTo(0,0)')
        self.page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
        player = self.page.locator('video').bounding_box()
        timeline = self.page.locator('.chapter-timeline-player')
        self.assertLess(player['y'], 220, player)
        self.assertLess(timeline.bounding_box()['height'], 160)
        expect(self.page.locator('.analysis-record')).to_contain_text('第1集自己的摘要')
        self.assertLess(self.page.locator('.analysis-record').bounding_box()['y'], 980)
        intro = timeline.locator('.chapter-timeline-description')
        self.assertIsNone(intro.get_attribute('open'))
        intro.locator('summary').click()
        expect(intro.locator('.chapter-timeline-intro-body')).to_be_visible()
        intro.locator('summary').click()
        expect(self.page.get_by_role('complementary', name='学习侧栏')).to_contain_text('第1集概念')
        self.assertNotIn(('POST', '/parse'), self.calls)

    def test_unarchived_current_episode_still_has_a_learning_toggle(self):
        original = self.parsed
        self.parsed = lambda part, online=False: original(part, online=True)
        self.page.goto(self.fixture.url + f'?project={self.identifier(1)}&page=learning')
        toggle = self.page.get_by_label('当前这一讲 P1 已学完', exact=True)
        expect(toggle).to_be_visible(); expect(toggle).to_be_enabled()
        self.assertNotIn(('POST', '/parse'), self.calls)

    def test_switching_workbench_and_learning_preserves_the_player_node(self):
        self.open()
        self.page.locator('video').evaluate('video=>window.existingLearningPlayer=video')
        self.page.locator('.video-context-more > summary').click()
        self.page.get_by_role('button', name='返回视频准备', exact=True).click()
        expect(self.page.get_by_role('button', name='开始学习', exact=True)).to_be_visible()
        self.assertTrue(self.page.evaluate('document.querySelector("video")===window.existingLearningPlayer'))
        self.page.get_by_role('button', name='开始学习', exact=True).click()
        expect(self.page.get_by_role('combobox', name='学习项目', exact=True)).to_be_visible()
        self.assertTrue(self.page.evaluate('document.querySelector("video")===window.existingLearningPlayer'))
        self.assertNotIn(('POST', '/parse'), self.calls)

    def test_archived_episode_uses_local_resume_and_retains_tools(self):
        self.open()
        self.choose_part(2)
        expect(self.page.locator('video')).to_be_visible()
        expect(self.page.get_by_role('complementary', name='学习侧栏')).to_be_visible()
        expect(self.page.locator('.analysis-record')).to_contain_text('第2集自己的摘要')
        expect(self.page.locator('.analysis-record')).not_to_contain_text('第1集自己的摘要')
        self.page.locator('.video-context-more > summary').click()
        expect(self.page.get_by_role('button', name='生成字幕', exact=True)).to_be_visible()
        expect(self.page.get_by_role('tab', name='AI 对话', exact=True)).to_be_visible()
        expect(self.page.locator('.video-context-actions').get_by_role('button', name='AI 对话', exact=True)).to_have_count(0)
        self.assertNotIn(('POST', '/parse'), self.calls)
        self.choose_part(1)
        expect(self.page.locator('.analysis-record')).to_contain_text('第1集自己的摘要')

    def test_empty_episode_preserves_tools_without_foreign_material(self):
        self.open()
        self.empty_parts.add(2)
        self.choose_part(2)
        expect(self.page.get_by_role('complementary', name='学习侧栏')).to_be_visible()
        self.page.locator('.video-context-more > summary').click()
        expect(self.page.get_by_role('button', name='生成字幕', exact=True)).to_be_visible()
        expect(self.page.get_by_role('button', name='生成/管理 AI 学习材料', exact=True)).to_be_visible()
        expect(self.page.locator('.analysis-record')).to_have_count(0)
        expect(self.page.locator('.learning-materials')).to_contain_text('还没有当前视频的 AI 学习材料')
        self.assertNotIn(('POST', '/parse'), self.calls)

    def test_learning_project_picker_restores_another_project_locally(self):
        self.open()
        picker = self.page.get_by_role('combobox', name='学习项目', exact=True)
        expect(picker).to_be_visible()
        picker.select_option(self.identifier(3))
        expect(self.page.locator('.video-context-heading')).to_contain_text('合成课程乙')
        expect(self.page.locator('.analysis-record')).to_contain_text('第3集自己的摘要')
        expect(self.page.locator('.analysis-record')).not_to_contain_text('第1集自己的摘要')
        self.assertNotIn(('POST', '/parse'), self.calls)
        for width in (1440, 760, 390, 280):
            self.page.set_viewport_size({'width': width, 'height': 1000})
            self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), width)


    def test_empty_learning_view_can_choose_a_lightweight_project_row(self):
        self.page.goto(self.fixture.url + '?page=learning')
        picker = self.page.get_by_role('combobox', name='学习项目', exact=True)
        expect(picker).to_be_enabled()
        expect(self.page.get_by_role('group', name='学习项目切换')).to_have_attribute('aria-busy', 'false')
        expect(self.page.get_by_role('alert')).to_have_count(0)
        picker.select_option(self.identifier(3))
        expect(self.page.locator('.video-context-heading')).to_contain_text('合成课程乙')
        expect(self.page.locator('.analysis-record')).to_contain_text('第3集自己的摘要')
        self.assertNotIn(('POST', '/parse'), self.calls)


if __name__ == '__main__':
    unittest.main(verbosity=2)
