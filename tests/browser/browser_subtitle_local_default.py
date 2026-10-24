"""Local-first viewing against a platform-first API, with fully isolated fixtures."""
import re
import unittest
from urllib.parse import urlsplit, parse_qs
from playwright.sync_api import expect
from tests.browser import browser_translation_status as fixture_tests


class SubtitleLocalDefaultBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture_tests.TranslationStatusBrowserTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        fixture_tests.TranslationStatusBrowserTests.tearDownClass()

    def setUp(self):
        self.fixture = fixture_tests.TranslationStatusBrowserTests('test_legacy_subtitle_has_explicit_unknown_provenance')
        self.fixture.setUp()
        self.page = self.fixture.page
        project = self.fixture.base.project
        self.fixture.base.project = lambda part: {**project(part), 'location': f'bilibili/合成课程/P{part:03d}'}
        self.calls = []
        self.bad_requests = []
        self.with_local = True
        self.unknown_only = False
        self.legacy_local = False
        old = self.fixture.sources
        self.fixture.sources = lambda: [{**row, 'has_subtitles': True, 'subtitle_count': 2} for row in old()]
        self.page.route('**/api/workspace/projects/*/subtitles?*', self.subtitles)

    def tearDown(self):
        try:
            self.assertEqual(self.bad_requests, [], 'No cross-episode resource requests')
            self.assertFalse(any(method == 'POST' and path in ('/transcriptions', '/subtitles', '/translations')
                                 for method, path, _ in self.fixture.calls))
        finally:
            self.fixture.tearDown()

    def subtitles(self, route):
        url = urlsplit(route.request.url)
        part = int(url.path.split('/')[4], 16)
        prefix = f'subtitles/p{part}'
        platform = {'resource': prefix + '-platform.srt', 'filename': '平台字幕.srt', 'kind': 'subtitle',
                    'origin': 'platform', 'language': 'zh', 'url': '/fixture'}
        unknown = {**platform, 'resource': prefix + '-unknown.srt', 'filename': '本地转写.en.srt', 'origin': 'unknown'}
        local = {**platform, 'resource': prefix + '-local.srt', 'filename': '本地转写.en.srt',
                 'kind': 'transcription', 'origin': 'local', 'language': 'en'}
        if self.legacy_local:
            local.pop('origin')
        translated = {**platform, 'resource': prefix + '-translation.srt', 'filename': 'AI译文.zh.srt',
                      'kind': 'translation', 'origin': 'translation', 'source_origin': 'local'}
        versions = [unknown] if self.unknown_only else [platform, unknown]
        if self.with_local:
            versions += [local, {**local, 'resource': prefix + '-local.txt', 'filename': '本地转写.en.txt'}]
        versions.append(translated)
        requested = parse_qs(url.query).get('subtitle_resource', [''])[0]
        self.calls.append((part, requested))
        selected = next((row for row in versions if row['resource'] == requested), None) if requested else versions[0]
        if selected is None:
            self.bad_requests.append((part, requested))
            return route.fulfill(status=404, json={'detail': 'Wrong episode resource'})
        text = f'第{part}集平台字幕。' if selected.get('origin') == 'platform' else f'第{part}集独立译文。' if selected['kind'] == 'translation' else f'Local transcript for episode {part}.' if selected['kind'] == 'transcription' else f'第{part}集来源未知。'
        return route.fulfill(json={'project_id': f'{part:032x}', 'has_subtitles': True,
                                  'files': [row for row in versions if row['kind'] != 'translation'],
                                  'versions': versions, 'selected': selected, 'text': text, 'translations': []})

    def open(self):
        self.fixture.open(); self.fixture.choose(0)
        self.card = self.page.get_by_role('region', name='当前视频字幕', exact=True)

    def expect_local(self, part=1):
        expect(self.card.get_by_role('button', name='本地转写字幕', exact=True)).to_have_attribute('aria-pressed', 'true')
        expect(self.card.get_by_label('字幕原文', exact=True)).to_have_value(f'Local transcript for episode {part}.')
        expect(self.card.get_by_role('combobox', name='字幕版本', exact=True)).to_have_value(f'subtitles/p{part}-local.srt')
        expect(self.card.locator('textarea')).to_have_count(1)

    def reload_archived(self):
        # Source mode is intentionally not persisted by the existing application.
        self.page.reload()
        self.page.get_by_role('button', name=re.compile(r'^已归档视频')).click()
        self.fixture.choose(0)

    def refresh(self):
        with self.page.expect_response(lambda response: '/subtitles?' in response.url):
            self.page.evaluate("window.dispatchEvent(new Event('video-parser:subtitles-changed'))")

    def test_local_is_default_on_entry_and_page_reload(self):
        self.open(); self.expect_local()
        self.reload_archived(); self.expect_local()
        expect(self.page.locator('#subtitle-acquire')).to_be_hidden()
        self.assertIn((1, 'subtitles/p1-local.srt'), self.calls)
        self.page.get_by_role('button', name='切换到深色主题', exact=True).click()
        expect(self.page.locator('body')).to_have_css('color', 'rgb(250, 250, 250)')
        expect(self.page.locator('body')).to_have_css('background-color', 'rgb(10, 10, 10)')
        self.page.screenshot(path=str(self.fixture.base.fixture.output / 'local-default-desktop.png'), animations='disabled')
        self.page.set_viewport_size({'width': 390, 'height': 1000})
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
        self.card.screenshot(path=str(self.fixture.base.fixture.output / 'local-default-mobile.png'), animations='disabled')

    def test_manual_platform_translation_and_local_version_survive_refresh(self):
        self.open(); self.expect_local()
        self.card.get_by_role('button', name='平台字幕', exact=True).click()
        expect(self.card.get_by_label('字幕原文', exact=True)).to_have_value('第1集平台字幕。')
        self.refresh()
        expect(self.card.get_by_label('字幕原文', exact=True)).to_have_value('第1集平台字幕。')
        self.card.get_by_role('button', name='AI 译文', exact=True).click()
        expect(self.card.get_by_label('译文', exact=True)).to_have_value('第1集独立译文。')
        self.refresh()
        expect(self.card.get_by_label('译文', exact=True)).to_have_value('第1集独立译文。')
        self.card.get_by_role('button', name='本地转写字幕', exact=True).click()
        self.card.get_by_role('combobox', name='字幕版本', exact=True).select_option('subtitles/p1-local.txt')
        expect(self.card.get_by_label('字幕原文', exact=True)).to_have_value('Local transcript for episode 1.')
        self.refresh()
        expect(self.card.get_by_role('combobox', name='字幕版本', exact=True)).to_have_value('subtitles/p1-local.txt')

    def test_platform_fallback_is_not_stolen_by_newly_arrived_local_file(self):
        self.with_local = False
        self.open()
        expect(self.card.get_by_label('字幕原文', exact=True)).to_have_value('第1集平台字幕。')
        self.with_local = True
        self.refresh()
        expect(self.card.get_by_role('button', name='本地转写字幕', exact=True)).to_be_visible()
        expect(self.card.get_by_label('字幕原文', exact=True)).to_have_value('第1集平台字幕。')
        self.reload_archived(); self.expect_local()

    def test_new_episode_uses_its_own_local_default_not_previous_manual_resource(self):
        self.open(); self.expect_local()
        self.card.get_by_role('button', name='平台字幕', exact=True).click()
        expect(self.card.get_by_label('字幕原文', exact=True)).to_have_value('第1集平台字幕。')
        self.fixture.choose(1); self.expect_local(2)
        self.fixture.choose(0); self.expect_local(1)

    def test_unknown_named_local_is_not_treated_as_a_transcript(self):
        self.with_local = False; self.unknown_only = True
        self.open()
        expect(self.card.get_by_role('button', name='来源未确认', exact=True)).to_have_attribute('aria-pressed', 'true')
        expect(self.card.get_by_role('button', name='本地转写字幕', exact=True)).to_have_count(0)
        expect(self.card.get_by_label('字幕原文', exact=True)).to_have_value('第1集来源未知。')

    def test_legacy_typed_transcription_is_local_without_origin_field(self):
        self.legacy_local = True
        self.open(); self.expect_local()


if __name__ == '__main__':
    unittest.main()
