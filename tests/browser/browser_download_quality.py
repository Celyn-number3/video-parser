"""Low-resolution download preferences; isolated storage and intercepted network only."""
import unittest
from urllib.parse import urlsplit
from playwright.sync_api import expect
from tests.browser import browser_product_improvements as harness
from tests.browser.browser_settings import check_quality_selection


def fixture_type():
    class Fixture(harness.ProductImprovementsBrowserTests):
        def parsed(self):
            result = super().parsed()
            result['qualities'] = [{'id': f'q{height}', 'label': f'{height}P', 'width': None,
                                    'height': height, 'media': None} for height in (1080, 720, 480, 360)]
            result['default_quality_id'] = 'q1080'
            return result
        def route(self, route):
            url = urlsplit(route.request.url)
            if url.hostname == '127.0.0.1' and url.port == self.server.server_port and (url.path.endswith('/prepare-task') or url.path == '/api/workspace/tasks/' + 'f'*32):
                self.requests.append((route.request.method, url.path.removeprefix('/api/workspace'), route.request.post_data_json))
                return route.fulfill(json={'id': 'f'*32, 'kind': 'video', 'state': 'failed', 'phase': 'failed',
                    'message': '隔离测试：只检查画质请求，不下载', 'result': None, 'progress': {}})
            return super().route(route)
    return Fixture


class DownloadQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): harness.ProductImprovementsBrowserTests.setUpClass()
    @classmethod
    def tearDownClass(cls): harness.ProductImprovementsBrowserTests.tearDownClass()
    def setUp(self):
        self.f = fixture_type()('test_settings_cross_tab_updates'); self.f.setUp(); self.page = self.f.page
    def tearDown(self): self.f.tearDown()

    def test_quality_normalization_and_missing_resolution_fallback(self):
        check_quality_selection()

    def check_preference(self, preference, label):
        self.page.goto(self.f.url + '?page=settings')
        selector = self.page.locator('#default-quality')
        expect(selector.locator('option')).to_have_text(['最高可用', '1080P 高清', '720P 准高清', '480P 标清', '360P 流畅'])
        selector.select_option(preference)
        self.page.get_by_label('归档完成提醒', exact=True).check()
        self.page.reload()
        expect(selector).to_have_value(preference)
        expect(self.page.get_by_label('归档完成提醒', exact=True)).to_be_checked()
        self.assertEqual(self.page.evaluate("JSON.parse(localStorage.getItem('video-parser:settings')).qualityPreference"), preference)
        self.page.locator('.app-sidebar').get_by_role('button', name='视频工作台', exact=True).click()
        self.page.locator('#source').fill(self.f.parsed()['source_url'])
        self.page.get_by_role('button', name='解析视频', exact=True).click()
        expect(self.page.locator('#video-quality')).to_have_value('q' + preference[:-1])
        self.page.locator('.download-button').click()
        expect(self.page.locator('#video-stage')).to_contain_text('隔离测试：只检查画质请求，不下载')
        posts = [(path, body) for method, path, body in self.f.requests if method == 'POST' and path.endswith('/prepare-task')]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0][1], {'quality_id': 'q' + preference[:-1]})
        self.page.locator('.sidebar-settings').get_by_role('button', name='设置', exact=True).click()
        expect(selector).to_have_value(preference)
        self.page.locator('.language-switch label', has_text='English').click()
        expect(selector.locator(f'option[value="{preference}"]')).to_have_text(label)
        for width in (1440, 390, 320):
            self.page.set_viewport_size({'width': width, 'height': 1000})
            self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
        self.page.get_by_role('button', name='Restore general defaults', exact=True).click()
        expect(selector).to_have_value('best')
        self.page.reload()
        expect(selector).to_have_value('best')

    def test_480p_persists_and_reaches_download_request(self):
        self.check_preference('480p', '480P Standard definition')

    def test_360p_persists_and_reaches_download_request(self):
        self.check_preference('360p', '360P Smooth')
