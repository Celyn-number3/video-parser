"""Synthetic regressions for green archived-subtitle status and explicit AI translation."""
import re
import unittest
from urllib.parse import urlsplit

from playwright.sync_api import expect
from tests.browser import browser_learning_workflow as learning


class TranslationStatusBrowserTests(unittest.TestCase):
    job_id = 'e' * 32

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
        self.completed = False
        self.language = 'en'
        self.source_job = None
        self.base.fixture.context.unroute('**/*')
        self.base.fixture.context.route('**/*', self.route)
        self.pid = self.base.identifier(1)
        self.text = 'I want to know why you describe yourself as salty.\nWhat does that mean?'
        self.base.fixture.jobs = []

    def tearDown(self):
        self.base.tearDown()

    def sources(self):
        common = {'project_id': self.pid, 'resource': 'video/fixture.wav', 'title': '合成课程甲 P1', 'platform': '哔哩哔哩',
                  'part': 1, 'source_url': 'https://www.bilibili.com/video/BV1TaqYBcEJc?p=1', 'quality': '720p',
                  'duration_seconds': 20, 'size_bytes': len(self.base.fixture.audio), 'archived_at': '2026-10-17'}
        return [{**common, 'has_subtitles': True, 'subtitle_count': 1},
                {**common, 'project_id': self.base.identifier(2), 'resource': 'video/fixture-2.wav', 'title': '合成课程甲 P2', 'part': 2, 'has_subtitles': False, 'subtitle_count': 0}]

    def translation_job(self):
        return {'id': self.job_id, 'kind': 'transcriptions', 'project_id': self.pid, 'part': 1, 'operation': 'translation', 'state': 'completed',
                'phase': 'completed', 'message': 'AI 翻译完成，原字幕保留；译文请人工校对。', 'title': '合成课程甲 P1',
                'text': '我想知道你为何把自己描述为“咸”。\n那是什么意思？', 'language': 'zh', 'translation_target': 'zh',
                'requested_language': 'auto', 'source_project_id': self.pid, 'source_resource': 'video/fixture.wav',
                'files': [{'name': 'original.AI翻译.zh.srt', 'format': 'srt', 'url': f'/api/workspace/transcriptions/{self.job_id}/files/srt'}],
                'saved_to': {'type': 'project', 'location': 'outputs/fixture/subtitles'}, 'progress': {}, 'created': 1}

    def route(self, route):
        request = route.request; url = urlsplit(request.url)
        if url.hostname != '127.0.0.1' or url.port != self.base.fixture.server.server_port:
            return self.base.route(route)
        path = url.path.removeprefix('/api/workspace')
        if path == '/transcriptions/sources':
            self.calls.append((request.method, path, None))
            return route.fulfill(json={'sources': self.sources()})
        if path == f'/projects/{self.pid}/subtitles':
            self.calls.append((request.method, path, None))
            selected = {'resource': 'subtitles/original.srt', 'filename': 'P01_原始字幕.srt', 'kind': 'subtitle', 'language': self.language,
                        'url': f'/api/workspace/projects/{self.pid}/files/subtitles/original.srt'}
            return route.fulfill(json={'project_id': self.pid, 'has_subtitles': True, 'files': [selected], 'selected': selected, 'text': self.text})
        if path == '/translations' and request.method == 'POST':
            body = request.post_data_json
            self.calls.append((request.method, path, body))
            self.assertEqual(body['target'], 'zh')
            self.assertIs(body['consent'], True)
            self.assertEqual((body['project_id'], body['resource'], body['video_resource']), (self.pid, 'subtitles/original.srt', 'video/fixture.wav'))
            self.completed = True
            job = self.translation_job(); self.base.fixture.jobs = [job]
            return route.fulfill(status=202, json=job)
        if path == f'/transcriptions/{self.job_id}' and request.method == 'GET':
            self.calls.append((request.method, path, None))
            return route.fulfill(json=self.source_job or self.translation_job())
        if path.endswith('/open') and request.method == 'POST':
            self.calls.append((request.method, path, request.post_data_json))
            return route.fulfill(json={'message': '已打开项目文件夹。' if path.startswith('/projects/') else '已打开保存文件夹。'})
        if path == f'/transcriptions/{self.job_id}/files/srt':
            return route.fulfill(body='1\n00:00:00,000 --> 00:00:01,000\n译文\n', content_type='application/x-subrip')
        return self.base.route(route)

    def open(self):
        self.page.goto(self.base.fixture.url + '?page=transcription')
        self.page.get_by_role('button', name=re.compile(r'^已归档视频')).click()
        expect(self.page.get_by_role('radiogroup', name='选择视频', exact=True)).to_be_visible()
        expect(self.page.get_by_role('radiogroup', name='选择视频').get_by_role('radio')).to_have_count(2)

    def choose(self, index):
        self.page.get_by_role('radiogroup', name='选择视频').get_by_role('radio').nth(index).check()

    def test_archived_subtitle_is_green_and_shown_without_download_or_transcription(self):
        self.open()
        # Compact list: only the exception (no local subtitles) carries a marker.
        items = self.page.get_by_role('radiogroup', name='选择视频').locator('li')
        expect(items.nth(0).locator('.subtitle-badge, .subtitle-missing')).to_have_count(0)
        expect(items.nth(1).locator('.subtitle-missing')).to_have_text('无字幕')
        self.choose(0)
        panel = self.page.get_by_role('region', name='当前视频字幕', exact=True)
        # "已有字幕" is announced exactly once, by the status badge of the selected video.
        badge = panel.locator('.subtitle-badge')
        expect(badge).to_have_text('✓ 已有字幕')
        self.page.evaluate("document.documentElement.setAttribute('data-theme', 'light')")
        expect(badge).to_have_css('color', 'rgb(22, 101, 52)')
        expect(badge).to_have_css('background-color', 'rgba(36, 143, 80, 0.14)')
        self.page.evaluate("document.documentElement.setAttribute('data-theme', 'dark')")
        expect(badge).to_have_css('color', 'rgb(101, 217, 151)')
        self.page.evaluate("document.documentElement.setAttribute('data-theme', 'light')")
        self.assertEqual(self.page.locator('.transcription-panel').inner_text().count('已有字幕'), 1)
        # Acquisition controls stay folded until asked for; no disabled "已有字幕" button anywhere.
        acquire = self.page.locator('#subtitle-acquire')
        expect(acquire).to_be_hidden()
        expect(self.page.get_by_role('button', name='已有字幕', exact=True)).to_have_count(0)
        # 字幕来源 is a view-level switch in the header, above the video list.
        method = self.page.get_by_role('group', name='字幕来源', exact=True)
        expect(self.page.locator('.transcription-head').get_by_role('group', name='字幕来源', exact=True)).to_be_visible()
        self.assertLess(method.bounding_box()['y'], self.page.get_by_role('radiogroup', name='选择视频').bounding_box()['y'])
        toggle = panel.get_by_role('button', name='重新下载字幕', exact=True)
        expect(toggle).to_have_attribute('aria-expanded', 'false')
        toggle.click()
        expect(acquire).to_be_visible()
        expect(panel.get_by_role('button', name='收起获取选项', exact=True)).to_have_attribute('aria-expanded', 'true')
        panel.get_by_role('button', name='收起获取选项', exact=True).click()
        expect(acquire).to_be_hidden()
        # Choosing a method in the header unfolds the controls for it.
        method.get_by_role('button', name='本地转写', exact=True).click()
        expect(acquire).to_be_visible()
        expect(acquire.get_by_role('button', name='开始转写', exact=True)).to_be_visible()
        panel.get_by_role('button', name='收起获取选项', exact=True).click()
        expect(panel.get_by_label('字幕原文', exact=True)).to_have_value(self.text)
        expect(panel.get_by_label('字幕原文', exact=True)).to_have_attribute('readonly', '')
        heading = panel.locator('.translation-heading')
        expect(heading.locator('label')).to_have_text('字幕原文')
        expect(heading.get_by_role('button', name='AI 中英互译', exact=True)).to_be_visible()
        # Subtitles are already in the project folder: show the location, no extra download button.
        expect(panel.get_by_role('button', name=re.compile('^下载'))).to_have_count(0)
        expect(panel.locator('.saved-location')).to_contain_text('subtitles')
        panel.get_by_role('button', name='打开文件夹', exact=True).click()
        expect(panel.get_by_role('status').filter(has_text='已打开项目文件夹。')).to_be_visible()
        self.assertIn(('POST', f'/projects/{self.pid}/open', {'folder': 'subtitles'}), self.calls)
        self.choose(1)
        expect(self.page.get_by_text('尚无本地字幕，可下载平台字幕或进行本地转写。', exact=True)).to_be_visible()
        # Missing subtitles: the acquisition controls are shown directly.
        expect(self.page.locator('#subtitle-acquire')).to_be_visible()
        expect(self.page.get_by_role('region', name='当前视频字幕', exact=True)).not_to_contain_text('字幕原文')
        self.assertFalse(any(path == '/translations' for _, path, _ in self.calls))
        self.assertFalse(any(path in ('/transcriptions', '/subtitles') for _, path, _ in self.calls))
        for width in (1440, 760, 390, 280):
            self.page.set_viewport_size({'width': width, 'height': 1000})
            self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'overflow at {width}px')

    def test_restored_translation_stays_in_subtitle_card(self):
        # A finished translation restored after a reload is shown in the card's AI 中英互译 section,
        # not as a transcription result, and it does not force the acquisition controls open.
        self.base.fixture.jobs = [self.translation_job()]
        self.page.add_init_script("localStorage.setItem('video-parser:task:transcriptions', '" + self.job_id + "')")
        self.open(); self.choose(0)
        card = self.page.get_by_role('region', name='当前视频字幕', exact=True)
        translation = card.get_by_role('region', name='AI 中英互译', exact=True)
        expect(translation.get_by_label('译文', exact=True)).to_have_value('我想知道你为何把自己描述为“咸”。\n那是什么意思？')
        expect(translation.locator('.saved-location')).to_contain_text('outputs/fixture/subtitles')
        expect(self.page.locator('#subtitle-acquire')).to_be_hidden()
        expect(self.page.locator('#transcription-text')).to_have_count(0)
        expect(self.page.get_by_text('本次任务', exact=False)).to_have_count(0)
        toggle = card.get_by_role('button', name=re.compile('^(重新下载字幕|重新转写)$'))
        expect(toggle).to_be_enabled()
        # 打开文件夹 is a real button, aligned with the toggle in the same action group.
        actions = card.locator(':scope > .saved-location .saved-location-actions')
        expect(actions.get_by_role('button', name='打开文件夹', exact=True)).to_be_visible()
        expect(actions.get_by_role('button', name=re.compile('^(重新下载字幕|重新转写)$'))).to_be_visible()
        # Each saved row says what it is, there is no redundant "完成" note, and both 打开文件夹 buttons line up.
        expect(translation.locator('.saved-location-text')).to_contain_text('译文已保存到')
        expect(card.locator(':scope > .saved-location .saved-location-text')).to_contain_text('字幕已保存到')
        expect(card.locator('.translation-status')).to_have_count(0)
        edges = [box['x'] + box['width'] for box in (b.bounding_box() for b in card.get_by_role('button', name='打开文件夹', exact=True).all())]
        self.assertEqual(len(edges), 2); self.assertLessEqual(abs(edges[0] - edges[1]), 1, edges)
        # 字幕来源 starts at the detail column's left edge.
        self.page.set_viewport_size({'width': 1440, 'height': 1000})
        picker = self.page.get_by_role('group', name='字幕来源', exact=True).bounding_box()
        detail = self.page.locator('.transcription-detail').bounding_box()
        self.assertLessEqual(abs(picker['x'] - detail['x']), 1, (picker, detail))
        self.assertFalse(any(path == '/translations' for _, path, _ in self.calls))

    def test_chinese_subtitles_default_to_english_without_automatic_model_call(self):
        self.language = 'zh'
        self.text = '这是中文原字幕。\n原始文件必须保留。'
        self.open(); self.choose(0)
        panel = self.page.get_by_role('region', name='AI 中英互译', exact=True)
        panel.get_by_role('button', name='AI 中英互译', exact=True).click()
        expect(panel.get_by_role('combobox', name='翻译方向', exact=True)).to_have_value('en')
        expect(panel.get_by_label('字幕原文', exact=True)).to_have_value(self.text)
        self.assertFalse(any(path == '/translations' for _, path, _ in self.calls))

    def test_transcription_result_places_translation_button_beside_text_heading(self):
        self.source_job = {**self.translation_job(), 'operation': 'transcription', 'language': 'en',
                           'text': self.text, 'source_project_id': None, 'source_resource': None,
                           'title': '合成上传音频', 'message': '转录完成。'}
        self.page.add_init_script("localStorage.setItem('video-parser:task:transcriptions', '" + self.job_id + "')")
        self.page.goto(self.base.fixture.url + '?page=transcription')
        result = self.page.locator('.transcription-result')
        expect(result.get_by_label('识别文字', exact=True)).to_have_value(self.text)
        heading = result.locator('.translation-heading')
        expect(heading.locator('label')).to_have_text('识别文字')
        button = heading.get_by_role('button', name='AI 中英互译', exact=True)
        expect(button).to_be_visible()
        label_box = heading.locator('label').bounding_box()
        button_box = button.bounding_box()
        self.assertLess(abs((label_box['y'] + label_box['height'] / 2) -
                            (button_box['y'] + button_box['height'] / 2)), 4)
        button.click()
        expect(result.get_by_role('combobox', name='翻译方向', exact=True)).to_have_value('zh')
        self.assertFalse(any(path == '/translations' for _, path, _ in self.calls))

    def test_translation_requires_consent_keeps_original_and_reports_on_tasks_page(self):
        self.open(); self.choose(0)
        panel = self.page.get_by_role('region', name='AI 中英互译', exact=True)
        panel.get_by_role('button', name='AI 中英互译', exact=True).click()
        direction = panel.get_by_role('combobox', name='翻译方向', exact=True)
        expect(direction).to_have_value('zh')
        expect(direction.locator('option')).to_contain_text(['英文 → 中文', '中文 → 英文'])
        start = panel.get_by_role('button', name='开始 AI 翻译', exact=True)
        expect(start).to_be_disabled()
        panel.get_by_role('checkbox', name=re.compile('^同意本次')).check()
        expect(start).to_be_enabled()
        self.assertFalse(any(path == '/translations' for _, path, _ in self.calls), 'no paid request before explicit consent')
        start.click()
        expect(panel.get_by_label('译文', exact=True)).to_have_value('我想知道你为何把自己描述为“咸”。\n那是什么意思？')
        expect(panel.get_by_role('button', name=re.compile('^下载译文'))).to_have_count(0)
        expect(panel.locator('.saved-location')).to_contain_text('outputs/fixture/subtitles')
        panel.get_by_role('button', name='打开文件夹', exact=True).click()
        expect(panel.get_by_text('已打开保存文件夹。', exact=True)).to_be_visible()
        self.assertIn(('POST', f'/transcriptions/{self.job_id}/open', {}), self.calls)
        body = next(body for method, path, body in self.calls if path == '/translations')
        self.assertEqual(set(body), {'project_id', 'resource', 'video_resource', 'target', 'consent', 'agent', 'output_confirmed'})
        self.assertIs(body['output_confirmed'], False, 'large cloud batches need the explicit 32K output confirmation')
        expect(self.page.get_by_label('字幕原文', exact=True)).to_have_value(self.text)
        self.page.get_by_role('button', name=re.compile('^任务中心')).click()
        row = self.page.locator('.task-list > li').filter(has_text='AI 翻译')
        expect(row.locator('strong')).to_contain_text('AI 翻译')


if __name__ == '__main__':
    unittest.main(verbosity=2)
