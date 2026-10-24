"""Audit UI regressions with isolated API fixtures, never paid or live operations."""
from pathlib import Path
import unittest
from playwright.sync_api import expect
from tests.browser import browser_product_improvements as harness


class AuditFixBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): harness.ProductImprovementsBrowserTests.setUpClass()
    @classmethod
    def tearDownClass(cls): harness.ProductImprovementsBrowserTests.tearDownClass()

    def test_progress_units_english_fallback_and_original_filenames(self):
        fixture = harness.ProductImprovementsBrowserTests('test_task_facets_search_counts_and_recovery_after_clear')
        fixture.setUp()
        try:
            art = Path(__file__).resolve().parents[2] / '.local/work/artifacts/audit-fixes'; art.mkdir(parents=True, exist_ok=True)
            rows = [
                {'id': 'a'*32, 'kind': 'transcriptions', 'operation': 'translation', 'state': 'completed', 'phase': 'completed', 'part': 8, 'created': 1, 'progress': {'done': 3, 'total': 3}, 'file_names': ['2.1 可解性-中文.srt', '2.1 可解性-中文.txt']},
                {'id': 'b'*32, 'kind': 'transcriptions', 'operation': 'transcription', 'state': 'running', 'phase': 'transcribing', 'part': 7, 'created': 1, 'progress': {'done': 30, 'total': 70}, 'file_names': ['1.3 求解Ax=0.mp4']},
                {'id': 'c'*32, 'kind': 'subtitles', 'state': 'failed', 'phase': 'failed', 'created': 1, 'progress': {'done': 1, 'total': 5}, 'file_names': []},
            ]
            fixture.context.route('**/api/workspace/tasks', lambda route: route.fulfill(json={'jobs': rows}))
            page = fixture.page; page.goto(fixture.url + '?page=tasks')
            items = page.locator('.task-list > li')
            expect(items).to_have_count(3)
            expect(items.nth(0)).to_contain_text('3/3 批')
            expect(items.nth(1)).to_contain_text('0:30 / 1:10')
            expect(items.nth(1)).not_to_contain_text('30/70 集')
            expect(items.nth(2)).to_contain_text('1/5 集')
            page.screenshot(path=str(art / 'task-units-zh.png'), full_page=True, animations='disabled')
            page.evaluate("localStorage.setItem('vp-language', 'en')"); page.reload()
            expect(page.locator('html')).to_have_attribute('lang', 'en')
            expect(page.locator('.task-search input')).to_have_attribute('placeholder', 'Search filenames, episodes (e.g. P3), or task IDs')
            expect(items.nth(0)).to_contain_text('3/3 batches')
            expect(items.nth(2)).to_contain_text('Filename unavailable')
            expect(items.nth(2)).not_to_contain_text('文件名暂不可用')
            expect(page.locator('.task-files summary')).to_contain_text('All files')
            expect(items.nth(0).locator('strong')).to_contain_text(rows[0]['file_names'][0])
            page.locator('.task-files summary').click()
            expect(page.locator('.task-files')).to_contain_text(rows[0]['file_names'][1])
            page.screenshot(path=str(art / 'task-units-en.png'), full_page=True, animations='disabled')
            for width in (390, 280):
                page.set_viewport_size({'width': width, 'height': 844})
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                page.screenshot(path=str(art / f'task-en-{width}.png'), full_page=True, animations='disabled')
            page.evaluate("localStorage.setItem('vp-language', 'zh')"); page.reload()
            expect(items.nth(2)).to_contain_text('文件名暂不可用')
            expect(items.nth(0)).to_contain_text('3/3 批')
        finally: fixture.tearDown()


if __name__ == '__main__': unittest.main()
