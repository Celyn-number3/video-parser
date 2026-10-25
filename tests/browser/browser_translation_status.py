"""Synthetic regressions for green archived-subtitle status and explicit AI translation."""
import re
from pathlib import Path
import unittest
from urllib.parse import urlsplit, parse_qs

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
                'translation_source': 'subtitles/original.srt', 'requested_language': 'auto', 'source_project_id': self.pid, 'source_resource': 'video/fixture.wav',
                'files': [{'name': 'original.AI翻译.zh.srt', 'sha256': 'b'*64, 'format': 'srt', 'url': f'/api/workspace/transcriptions/{self.job_id}/files/srt'}],
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
            selected = {'resource': 'subtitles/original.srt', 'filename': 'P01_原始字幕.srt', 'kind': 'subtitle', 'origin': 'platform', 'language': self.language,
                        'url': f'/api/workspace/projects/{self.pid}/files/subtitles/original.srt'}
            translated = {'resource': 'subtitles/original.AI翻译.zh.srt', 'filename': 'original.AI翻译.zh.srt', 'kind': 'translation',
                          'origin': 'translation', 'sha256': 'b'*64, 'source_resource': selected['resource'], 'source_origin': 'platform',
                          'source_language': self.language, 'language': 'zh', 'url': '/fixture', 'text': self.translation_job()['text']}
            versions = [selected, translated] if self.completed else [selected]
            viewed = next((row for row in versions if row['resource'] == parse_qs(url.query).get('subtitle_resource', [''])[0]), selected)
            return route.fulfill(json={'project_id': self.pid, 'has_subtitles': True, 'files': [selected], 'versions': versions,
                                      'selected': viewed, 'text': translated['text'] if viewed is translated else self.text,
                                      'translations': [translated] if self.completed and viewed is selected else []})
        if path == f'/projects/{self.pid}/subtitle-cues':
            original = {'resource': 'subtitles/original.srt', 'label': '本地转写（英文）', 'kind': 'transcription', 'language': 'en'}
            translated = {'resource': 'subtitles/original.AI翻译.zh.srt', 'label': 'AI 翻译（中文）', 'kind': 'translation', 'language': 'zh'}
            selected = parse_qs(url.query).get('resource', [''])[0] or (translated['resource'] if self.completed else original['resource'])
            body = self.translation_job()['text'] if selected == translated['resource'] else self.text
            return route.fulfill(json={'sources': [original, translated] if self.completed else [original], 'resource': selected,
                                       'cues': [{'time': i * 4 + 1, 'text': text} for i, text in enumerate(body.splitlines())]})
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
        # Selection now commits after the shared workbench restore, not inside the click event.
        radio = self.page.get_by_role('radiogroup', name='选择视频').get_by_role('radio').nth(index)
        radio.click(); expect(radio).to_be_checked()

    def view_translation(self):
        card = self.page.get_by_role('region', name='当前视频字幕', exact=True)
        card.get_by_role('button', name='AI翻译字幕', exact=True).click()
        expect(card.get_by_label('译文', exact=True)).to_have_value(self.translation_job()['text'])
        expect(card.locator('textarea')).to_have_count(1)
        expect(card.get_by_role('button', name='AI 中英互译', exact=True)).to_be_visible()
        return card

    def test_learning_lists_saved_chinese_and_can_switch_back_to_original(self):
        self.completed = True
        self.base.open()
        self.page.get_by_role('tab', name='字幕', exact=True).click()
        panel = self.page.get_by_role('region', name='滚动字幕', exact=True)
        choices = panel.get_by_role('combobox', name='字幕版本', exact=True)
        expect(choices.locator('option')).to_have_text(['本地转写（英文）', 'AI 翻译（中文）'])
        expect(choices).to_have_value('subtitles/original.AI翻译.zh.srt')
        expect(panel).to_contain_text('我想知道你为何')
        choices.select_option('subtitles/original.srt')
        expect(panel).to_contain_text('I want to know')
        choices.select_option('subtitles/original.AI翻译.zh.srt')
        expect(panel).to_contain_text('我想知道你为何')
        self.page.reload()
        self.page.get_by_role('tab', name='字幕', exact=True).click()
        expect(panel).to_contain_text('我想知道你为何')
        expect(self.page.get_by_text('语义检索 · 当前视频字幕', exact=True)).to_have_count(0)
        self.assertFalse(any(path == '/translations' for _, path, _ in self.calls))
        artifacts = Path(__file__).resolve().parents[2] / '.local/work/artifacts/subtitle-results'
        artifacts.mkdir(parents=True, exist_ok=True)
        self.page.evaluate('document.documentElement.setAttribute("data-theme", "dark")')
        self.page.screenshot(path=str(artifacts / 'learning-chinese.png'), full_page=True, animations='disabled')

    def test_saved_translation_survives_reload_without_any_remembered_task(self):
        self.completed = True
        self.open(); self.choose(0)
        self.view_translation()
        self.choose(1)
        expect(self.page.get_by_label('译文', exact=True)).to_have_count(0)
        self.choose(0)
        self.view_translation()
        self.page.evaluate("localStorage.removeItem('video-parser:task:transcriptions')")
        self.page.reload()
        self.page.get_by_role('button', name=re.compile(r'^已归档视频')).click(); self.choose(0)
        self.view_translation()
        expect(self.page.get_by_role('button', name='AI 中英互译', exact=True)).to_be_visible()
        self.assertFalse(any(path == '/translations' for _, path, _ in self.calls))
        artifacts = Path(__file__).resolve().parents[2] / '.local/work/artifacts/subtitle-results'
        artifacts.mkdir(parents=True, exist_ok=True)
        for width, theme in [(1440, 'light'), (1440, 'dark'), (390, 'dark')]:
            self.page.set_viewport_size({'width': width, 'height': 1000})
            self.page.evaluate('(theme) => document.documentElement.setAttribute("data-theme", theme)', theme)
            self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'))
            self.page.screenshot(path=str(artifacts / f'translation-{theme}-{width}.png'), full_page=True, animations='disabled')

    def test_source_rows_have_no_tooltips_and_switch_loading_is_silent(self):
        original_sources = self.sources
        self.sources = lambda: [{**row, 'has_subtitles': True, 'subtitle_count': 1} for row in original_sources()]
        pid = self.base.identifier(2); held = []
        self.page.route('**/api/workspace/projects/'+pid+'/subtitles?*', lambda route: held.append(route))
        self.open()
        rows = self.page.get_by_role('radiogroup', name='选择视频', exact=True)
        expect(rows.locator('[title]')).to_have_count(0)
        rows.locator('label').first.hover()
        expect(rows.get_by_role('radio')).to_have_count(2)
        self.choose(0)
        expect(self.page.get_by_role('textbox', name='字幕原文', exact=True)).to_have_value(self.text)
        self.choose(1)
        panel = self.page.get_by_role('region', name='当前视频字幕', exact=True)
        expect(panel).to_have_attribute('aria-busy', 'true')
        expect(self.page.get_by_text('正在读取已有字幕…', exact=True)).to_have_count(0)
        expect(panel.get_by_role('textbox', name='字幕原文', exact=True)).to_have_count(0)
        self.assertTrue(held)
        selected = {'resource':'subtitles/second.srt','filename':'第二集.srt','kind':'subtitle','language':'en','url':'/fixture'}
        held.pop().fulfill(json={'project_id':pid,'has_subtitles':True,'files':[selected],'selected':selected,
                                'text':'Second video subtitles.','translations':[]})
        expect(panel.get_by_role('textbox', name='字幕原文', exact=True)).to_have_value('Second video subtitles.')
        expect(panel).to_have_attribute('aria-busy', 'false')
        self.choose(0)
        expect(panel.get_by_role('textbox', name='字幕原文', exact=True)).to_have_value(self.text)
        self.assertFalse(any(method == 'POST' and path in ('/transcriptions','/subtitles','/translations') for method,path,_ in self.calls))

    def test_silent_archive_loading_still_shows_read_errors(self):
        self.page.route('**/api/workspace/projects/'+self.pid+'/subtitles?*',
                        lambda route: route.fulfill(status=503, json={'detail':'模拟字幕读取失败'}))
        self.open(); self.choose(0)
        panel = self.page.get_by_role('region', name='当前视频字幕', exact=True)
        expect(panel.get_by_role('alert')).to_have_text('模拟字幕读取失败')
        expect(panel).to_have_attribute('aria-busy','false')
        expect(self.page.get_by_text('正在读取已有字幕…', exact=True)).to_have_count(0)

    def test_archived_subtitle_is_green_and_shown_without_download_or_transcription(self):
        self.open()
        # Every known subtitle state has a horizontal status marker.
        items = self.page.get_by_role('radiogroup', name='选择视频').locator('li')
        expect(items.nth(0).locator('.source-subtitle-status')).to_have_text('有字幕')
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
        # Viewing source is visible; generation controls live only in the acquisition area.
        expect(panel.get_by_role('group', name='字幕功能', exact=True)).to_be_visible()
        method = self.page.get_by_role('group', name='获取方式', exact=True)
        expect(method).to_be_hidden()
        toggle = panel.get_by_role('button', name='重新下载字幕', exact=True)
        expect(toggle).to_have_attribute('aria-expanded', 'false')
        toggle.click()
        expect(acquire).to_be_visible()
        expect(panel.get_by_role('button', name='收起获取选项', exact=True)).to_have_attribute('aria-expanded', 'true')
        panel.get_by_role('button', name='收起获取选项', exact=True).click()
        expect(acquire).to_be_hidden()
        # The existing function selector owns acquisition; no second method picker.
        panel.get_by_role('button', name='本地生成字幕', exact=True).click()
        panel.get_by_role('button', name='重新生成字幕', exact=True).click()
        expect(acquire).to_be_visible()
        expect(acquire.get_by_role('button', name='确认生成字幕', exact=True)).to_be_visible()
        panel.get_by_role('button', name='收起获取选项', exact=True).click()
        panel.get_by_role('button', name='平台下载字幕', exact=True).click()
        expect(panel.get_by_label('字幕原文', exact=True)).to_have_value(self.text)
        expect(panel.get_by_label('字幕原文', exact=True)).to_have_attribute('readonly', '')
        expect(panel.get_by_role('button', name='AI 中英互译', exact=True)).to_have_count(0)
        # Subtitles are already in the project folder: show the location, no extra download button.
        expect(panel.get_by_role('button', name=re.compile('^下载'))).to_have_count(0)
        expect(panel.locator('.saved-location')).to_contain_text('subtitles')
        panel.locator('.subtitle-file-details > summary').click()
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
        expect(card.get_by_label('字幕原文', exact=True)).to_have_value(self.text)
        self.view_translation()
        expect(card.locator('.saved-location')).to_contain_text('subtitles')
        expect(self.page.locator('#subtitle-acquire')).to_be_hidden()
        expect(self.page.locator('#transcription-text')).to_have_count(0)
        expect(self.page.get_by_text('本次任务', exact=False)).to_have_count(0)
        toggle = card.get_by_role('button', name='AI 中英互译', exact=True)
        expect(toggle).to_be_enabled()
        actions = card.locator(':scope > .saved-location .saved-location-actions')
        card.locator('.subtitle-file-details > summary').click()
        expect(card.get_by_role('button', name='打开文件夹', exact=True)).to_be_visible()
        expect(card.get_by_role('button', name='打开文件夹', exact=True)).to_have_count(1)
        expect(card.locator('.subtitle-provenance')).to_contain_text('原字幕：平台下载字幕')
        expect(card.locator('.translation-status')).to_have_count(0)
        self.assertFalse(any(path == '/translations' for _, path, _ in self.calls))

    def test_completed_transcription_joins_versions_without_stealing_platform_selection(self):
        self.source_job = {**self.translation_job(), 'operation': 'transcription', 'language': 'en',
                           'text': 'Local English transcript.', 'files': [{'name': 'local.en.srt', 'format': 'srt', 'url': '/fixture'}]}
        self.page.add_init_script("localStorage.setItem('video-parser:task:transcriptions', '" + self.job_id + "')")
        self.open(); self.choose(0)
        card = self.page.get_by_role('region', name='当前视频字幕', exact=True)
        expect(card.get_by_label('字幕原文', exact=True)).to_have_value(self.text)
        card.get_by_role('button', name='本地生成字幕', exact=True).click()
        expect(card.get_by_label('字幕原文', exact=True)).to_have_value('Local English transcript.')
        expect(card.locator('.subtitle-provenance')).to_have_count(0)
        expect(card.get_by_role('combobox', name='字幕版本', exact=True).locator('option:checked')).to_contain_text('英文原文')
        expect(card.get_by_role('button', name='重新生成字幕', exact=True)).to_be_visible()
        expect(self.page.locator('.transcription-detail textarea')).to_have_count(1)
        expect(self.page.locator('.transcription-result')).to_have_count(0)
        card.get_by_role('button', name='平台下载字幕', exact=True).click()
        expect(card.get_by_label('字幕原文', exact=True)).to_have_value(self.text)
        self.assertFalse(any(method == 'POST' and path in ('/transcriptions','/subtitles','/translations') for method,path,_ in self.calls))

    def test_legacy_subtitle_has_explicit_unknown_provenance(self):
        selected = {'resource': 'subtitles/legacy.srt', 'filename': 'English.srt', 'kind': 'subtitle', 'language': 'en', 'url': '/fixture'}
        self.page.route('**/api/workspace/projects/'+self.pid+'/subtitles?*', lambda route: route.fulfill(json={
            'project_id': self.pid, 'has_subtitles': True, 'files': [selected], 'selected': selected, 'text': self.text}))
        self.open(); self.choose(0)
        card = self.page.get_by_role('region', name='当前视频字幕', exact=True)
        expect(card.get_by_role('button', name='来源未确认', exact=True)).to_be_visible()
        expect(card.get_by_role('button', name='平台下载字幕', exact=True)).to_have_attribute('aria-pressed','false')
        expect(card.get_by_role('button', name='本地生成字幕', exact=True)).to_have_attribute('aria-pressed','false')

    def test_chinese_subtitles_default_to_english_without_automatic_model_call(self):
        self.language = 'zh'
        self.text = '这是中文原字幕。\n原始文件必须保留。'
        self.open(); self.choose(0)
        self.page.get_by_role('button',name='AI翻译字幕',exact=True).click()
        panel = self.page.get_by_role('region', name='AI 中英互译', exact=True)
        panel.get_by_role('button', name='AI 中英互译', exact=True).click()
        expect(panel.get_by_role('combobox', name='翻译方向', exact=True)).to_have_value('en')
        expect(self.page.get_by_role('combobox',name='翻译原字幕',exact=True)).to_be_visible()
        self.assertFalse(any(path == '/translations' for _, path, _ in self.calls))

    def test_uploaded_transcription_has_separate_translation_function(self):
        self.source_job = {**self.translation_job(), 'operation': 'transcription', 'language': 'en',
                           'text': self.text, 'source_project_id': None, 'source_resource': None,
                           'title': '合成上传音频', 'message': '转录完成。'}
        self.page.add_init_script("localStorage.setItem('video-parser:task:transcriptions', '" + self.job_id + "')")
        self.page.goto(self.base.fixture.url + '?page=transcription')
        result = self.page.locator('.transcription-result')
        expect(result.get_by_label('字幕原文', exact=True)).to_have_value(self.text)
        expect(result.get_by_role('button',name='AI 中英互译',exact=True)).to_have_count(0)
        result.get_by_role('button',name='AI翻译字幕',exact=True).click()
        result.get_by_role('button',name='AI 中英互译',exact=True).click()
        expect(result.get_by_role('combobox', name='翻译方向', exact=True)).to_have_value('zh')
        self.assertFalse(any(path == '/translations' for _, path, _ in self.calls))

    def test_translation_explicit_start_keeps_original_and_reports_on_tasks_page(self):
        self.open(); self.choose(0)
        self.page.get_by_role('button',name='AI翻译字幕',exact=True).click()
        panel = self.page.get_by_role('region', name='AI 中英互译', exact=True)
        panel.get_by_role('button', name='AI 中英互译', exact=True).click()
        direction = panel.get_by_role('combobox', name='翻译方向', exact=True)
        expect(direction).to_have_value('zh')
        expect(direction.locator('option')).to_contain_text(['英文 → 中文', '中文 → 英文'])
        start = panel.get_by_role('button', name='开始 AI 翻译', exact=True)
        expect(panel.get_by_role('checkbox', name=re.compile('^同意本次'))).to_have_count(0)
        expect(start).to_be_enabled()
        self.assertFalse(any(path == '/translations' for _, path, _ in self.calls), 'no paid request before explicit Start click')
        start.click()
        card = self.view_translation()
        expect(card.get_by_role('button', name=re.compile('^下载译文'))).to_have_count(0)
        expect(card.locator('.saved-location')).to_contain_text('subtitles')
        card.locator('.subtitle-file-details > summary').click()
        card.get_by_role('button', name='打开文件夹', exact=True).click()
        expect(card.get_by_text('已打开项目文件夹。', exact=True)).to_be_visible()
        self.assertIn(('POST', f'/projects/{self.pid}/open', {'folder': 'subtitles'}), self.calls)
        body = next(body for method, path, body in self.calls if path == '/translations')
        self.assertEqual(set(body), {'project_id', 'resource', 'video_resource', 'target', 'consent', 'agent', 'output_confirmed'})
        self.assertIs(body['output_confirmed'], False, 'large cloud batches need the explicit 32K output confirmation')
        card.get_by_role('button', name='平台下载字幕', exact=True).click()
        expect(self.page.get_by_label('字幕原文', exact=True)).to_have_value(self.text)
        self.page.get_by_role('button', name=re.compile('^任务中心')).click()
        row = self.page.locator('.task-list > li').filter(has_text='AI 翻译')
        expect(row.locator('strong')).to_contain_text('AI 翻译')


    def test_local_model_ignores_but_does_not_erase_cloud_batch_choice(self):
        self.base.fixture.ai['provider'] = 'llamacpp'
        self.open(); self.choose(0)
        self.page.get_by_role('button',name='AI翻译字幕',exact=True).click()
        panel = self.page.get_by_role('region', name='AI 中英互译', exact=True)
        panel.get_by_role('button', name='AI 中英互译', exact=True).click()
        picker = panel.get_by_role('combobox', name='引擎与模型', exact=True)
        batch = panel.get_by_role('checkbox', name=re.compile('^我已确认所选模型'))
        expect(batch).to_have_count(0)
        picker.select_option('codex|')
        batch.check()
        picker.select_option('api|')
        expect(batch).to_have_count(0)
        picker.select_option('codex|')
        expect(batch).to_be_checked()
        picker.select_option('api|')
        self.assertFalse(any(path == '/translations' for _, path, _ in self.calls))
        panel.get_by_role('button', name='开始 AI 翻译', exact=True).click()
        self.view_translation()
        body = next(body for method, path, body in self.calls if path == '/translations')
        self.assertIs(body['output_confirmed'], False)

    def test_large_batch_choice_survives_model_changes_and_is_centered(self):
        self.open(); self.choose(0)
        self.page.get_by_role('button',name='AI翻译字幕',exact=True).click()
        panel = self.page.get_by_role('region', name='AI 中英互译', exact=True)
        panel.get_by_role('button', name='AI 中英互译', exact=True).click()
        batch = panel.get_by_role('checkbox', name=re.compile('^我已确认所选模型'))
        picker = panel.get_by_role('combobox', name='引擎与模型', exact=True)
        expect(batch).not_to_be_checked()
        batch.check()
        picker.select_option('codex|')
        expect(batch).to_be_checked()
        picker.select_option('api|')
        expect(batch).to_be_checked()
        batch.uncheck()
        picker.select_option('codex|')
        expect(batch).not_to_be_checked()
        picker.select_option('api|')
        expect(batch).not_to_be_checked()
        batch.check()
        panel.get_by_role('button', name='AI 中英互译', exact=True).click()
        panel.get_by_role('button', name='AI 中英互译', exact=True).click()
        expect(batch).to_be_checked()
        self.assertFalse(any(path == '/translations' for _, path, _ in self.calls))
        artifacts = Path(__file__).resolve().parents[2] / '.local/work/artifacts/translation-controls'
        artifacts.mkdir(parents=True, exist_ok=True)
        for width, theme in [(1440, 'light'), (1440, 'dark'), (390, 'dark')]:
            self.page.set_viewport_size({'width': width, 'height': 1000})
            self.page.evaluate('(theme) => document.documentElement.setAttribute("data-theme", theme)', theme)
            label = panel.locator('.translation-batch-option > span')
            box, text_box = batch.bounding_box(), label.bounding_box()
            self.assertLessEqual(abs(box['y'] + box['height']/2 - text_box['y'] - text_box['height']/2), 1)
            self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width)
            panel.screenshot(path=str(artifacts / f'{theme}-{width}.png'), animations='disabled')
        panel.get_by_role('button', name='开始 AI 翻译', exact=True).click()
        self.view_translation()
        body = next(body for method, path, body in self.calls if path == '/translations')
        self.assertIs(body['output_confirmed'], True)
        self.assertIs(body['consent'], True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
