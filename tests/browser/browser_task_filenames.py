"""Filename-only task headlines/search, mocked APIs and desktop/mobile visual checks."""
from pathlib import Path
import unittest
from playwright.sync_api import expect
from tests.browser import browser_product_improvements as harness


class TaskFilenameBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): harness.ProductImprovementsBrowserTests.setUpClass()
    @classmethod
    def tearDownClass(cls): harness.ProductImprovementsBrowserTests.tearDownClass()

    def setUp(self):
        self.base = harness.ProductImprovementsBrowserTests('test_task_facets_search_counts_and_recovery_after_clear')
        self.base.setUp(); self.page = self.base.page
        self.base.jobs = [
            {'id': '1'*32, 'kind': 'naming', 'state': 'failed', 'part': 8, 'project_id': harness.PROJECT_ID, 'file_names': ['2.1 可解性和解的结构.mp4', '2.2 零空间与特解.mp4']},
            {'id': '2'*32, 'kind': 'transcriptions', 'operation': 'translation', 'state': 'completed', 'part': 8, 'project_id': harness.PROJECT_ID, 'video_names': ['2.1 可解性和解的结构.mp4'], 'file_names': ['旧课程标题-中文.srt', '旧课程标题-中文.txt']},
            {'id': '3'*32, 'kind': 'transcriptions', 'state': 'queued', 'part': 7, 'project_id': harness.PROJECT_ID, 'file_names': ['1.3 求解Ax=0：主变量与特解.mp4']},
            {'id': '4'*32, 'kind': 'video', 'state': 'completed', 'part': 8, 'project_id': harness.PROJECT_ID, 'file_names': ['2.1 可解性和解的结构.mp4']},
            {'id': '5'*32, 'kind': 'subtitles', 'state': 'failed', 'part': 2, 'project_id': None, 'file_names': []},
        ]
        self.page.goto(self.base.url + '?page=tasks')
        expect(self.page.locator('.task-list > li')).to_have_count(5)

    def tearDown(self): self.base.tearDown()

    def test_headlines_show_files_never_course_and_keep_part(self):
        headings = self.page.locator('.task-list > li strong')
        expect(headings.nth(0)).to_contain_text('2.1 可解性和解的结构.mp4 +1')
        expect(headings.nth(0)).to_contain_text('P8')
        expect(headings.nth(1)).to_contain_text('AI 翻译 · 2.1 可解性和解的结构.mp4')
        expect(headings.nth(1)).not_to_contain_text('旧课程标题')
        expect(headings.nth(1)).not_to_contain_text('+1')
        details = self.page.locator('.task-list > li').nth(1).locator('.task-files')
        details.locator('summary').click()
        expect(details).to_contain_text('旧课程标题-中文.srt')
        expect(details).to_contain_text('全部文件（3）')
        expect(headings.nth(4)).to_contain_text('文件名暂不可用')
        for heading in headings.all():
            expect(heading).not_to_contain_text('原课程标题')
            expect(heading).not_to_contain_text('旧平台标题')
        self.page.locator('.task-files summary').first.click()
        expect(self.page.locator('.task-files').first).to_contain_text('2.2 零空间与特解.mp4')
        art = Path(__file__).resolve().parents[2] / '.local/work/artifacts/task-filenames'
        art.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(art / 'desktop.png'), full_page=True, animations='disabled')
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.page.screenshot(path=str(art / 'mobile.png'), full_page=True, animations='disabled')
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))

    def test_search_indexes_every_file_and_retains_project_part_search(self):
        search = self.page.get_by_role('searchbox', name='搜索任务', exact=True)
        search.fill('零空间')
        expect(self.page.locator('.task-list > li')).to_have_count(1)
        search.fill('中文.txt')
        expect(self.page.locator('.task-list > li')).to_have_count(1)
        search.fill('P7')
        expect(self.page.locator('.task-list > li')).to_have_count(1)
        search.fill('原课程标题')
        expect(self.page.locator('.task-list > li')).to_have_count(4)
        search.press('Escape')
        expect(self.page.locator('.task-list > li')).to_have_count(5)

    def test_failed_translation_and_completed_transcription_keep_video_headlines(self):
        self.base.jobs[1].update(state='failed', video_names=['独特源视频.mp4'])
        self.base.jobs[2].update(state='completed', video_names=['源转写视频.mp4'], file_names=['旧课程转写.srt', '旧课程转写.txt'])
        self.page.reload()
        expect(self.page.locator('.task-list > li strong').nth(1)).to_contain_text('独特源视频.mp4')
        expect(self.page.locator('.task-list > li strong').nth(2)).to_contain_text('源转写视频.mp4')
        search = self.page.get_by_role('searchbox', name='搜索任务', exact=True)
        search.fill('独特源视频')
        expect(self.page.locator('.task-list > li')).to_have_count(1)
        search.fill('旧课程转写.txt')
        expect(self.page.locator('.task-list > li')).to_have_count(1)

    def test_source_already_in_file_inventory_is_not_duplicated(self):
        self.base.jobs[3]['video_names'] = self.base.jobs[3]['file_names'][:]
        self.page.reload()
        expect(self.page.locator('.task-list > li').nth(3).locator('.task-files')).to_have_count(0)

    def test_episode_titles_batch_parts_and_typed_files(self):
        self.base.jobs[0].update(subjects=[{'project_id': 'p', 'part': 7, 'title': '主变量与特解'}, {'project_id': 'q', 'part': 9, 'title': '线性相关'}],
            file_details=[{'project_id': pid, 'part': part, 'role': 'video', 'name': '480p_internal.mp4'} for pid, part in [('p', 7), ('q', 9)]])
        self.base.jobs[1].update(subjects=[{'project_id': 'q', 'part': 8, 'title': '可解性和解的结构'}], file_details=[
            {'project_id': 'q', 'part': 8, 'role': role, 'name': name} for role, name in [('video', '480p_internal.mp4'), ('source_subtitle', '旧课程.en.srt'), ('translation', '旧课程.zh.srt')]])
        self.page.reload()
        headings = self.page.locator('.task-list > li strong')
        expect(headings.nth(0)).to_contain_text('文件重命名 · P7、P9 · 共 2 集')
        expect(headings.nth(0)).not_to_contain_text('P8')
        expect(headings.nth(1)).to_contain_text('AI 翻译 · P8 · 可解性和解的结构')
        expect(headings.nth(1)).not_to_contain_text('.mp4')
        row = self.page.locator('.task-list > li').nth(1)
        row.locator('.task-files summary').click()
        for label in ('源视频：', '原字幕：', '译文：'): expect(row).to_contain_text(label)
        self.page.locator('.task-list > li').first.locator('summary').click()
        art = Path(__file__).resolve().parents[2] / '.local/work/artifacts/task-episode-labels'
        art.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(art / 'fixture-desktop.png'), full_page=True)
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.page.screenshot(path=str(art / 'fixture-mobile.png'), full_page=True)
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))
        search = self.page.get_by_role('searchbox', name='搜索任务', exact=True)
        search.fill('线性相关'); expect(self.page.locator('.task-list > li')).to_have_count(1)
        search.fill('P9'); expect(self.page.locator('.task-list > li')).to_have_count(1)
        search.fill('旧课程.zh.srt'); expect(self.page.locator('.task-list > li')).to_have_count(1)

    def test_missing_episode_metadata_does_not_expose_internal_name_as_heading(self):
        self.base.jobs[1].update(subjects=[{'project_id': 'q', 'part': 8, 'title': ''}], file_details=[{'project_id': 'q', 'part': 8, 'role': 'video', 'name': '480p_internal.mp4'}])
        self.page.reload()
        heading = self.page.locator('.task-list > li strong').nth(1)
        expect(heading).to_contain_text('P8 · 分集名称暂不可用')
        expect(heading).not_to_contain_text('480p')
        expect(self.page.locator('.task-list > li').nth(1).locator('summary')).to_contain_text('全部文件（1）')


if __name__ == '__main__': unittest.main()
