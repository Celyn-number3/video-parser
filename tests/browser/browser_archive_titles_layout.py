"""Isolated UI checks; no actual naming, learning-state writes or model calls."""
import unittest
from tests.browser.project_picker import select_project
from playwright.sync_api import expect
from tests.browser import browser_subtitle_naming as naming


def fixture_type():
    class Fixture(naming.SubtitleNamingBrowserTests):
        def entries(self):
            values = super().entries()
            return [dict(values[0], single_episode=True)] if getattr(self, 'single', False) else values
    return Fixture


class ArchiveTitlesLayoutBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): naming.SubtitleNamingBrowserTests.setUpClass()
    @classmethod
    def tearDownClass(cls): naming.SubtitleNamingBrowserTests.tearDownClass()
    def setUp(self):
        self.f = fixture_type()('test_single_page_controls_remain_before_and_after_generation')
        self.f.setUp(); self.page = self.f.page
    def tearDown(self): self.f.tearDown()

    def test_existing_single_proposal_is_editable_without_number_or_paid_regeneration(self):
        self.f.single = True; self.f.rows = self.f.rows[:1]
        self.f.original_entries = self.f.entries(); self.f.plan_created = True
        self.f.open(); self.f.from_task_center(); self.f.validate()
        dialog = self.f.dialog
        expect(dialog.get_by_role('textbox', name='P1 层级序号', exact=True)).to_have_count(0)
        expect(dialog.get_by_role('textbox', name='P1 新名称', exact=True)).to_have_value('变量基础')
        expect(dialog.get_by_role('region', name='真实文件改名预览')).to_contain_text('video/变量基础.wav')
        self.assertEqual(self.f.preview['rows'][0]['number'], '')
        self.assertEqual(self.f.count_post('/plan'), 0)
        self.assertEqual(self.f.count_post('/apply'), 0)
        expect(dialog.locator('.agent-model-row button, .agent-mode')).to_have_count(0)
        for width in (1440, 760, 390, 320):
            self.page.set_viewport_size({'width': width, 'height': 1000})
            self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            self.page.screenshot(path=str(self.f.base.fixture.output / f'single-title-only-{width}.png'), full_page=True)
        dialog.get_by_role('button', name='确认并重命名', exact=True).click()
        expect(dialog).to_contain_text('文件重命名完成')
        self.assertEqual(self.f.count_post('/apply'), 1)

    def test_multi_keeps_hierarchy_and_model_selector_but_no_toolbar_buttons(self):
        self.f.open(); self.f.suggest(); self.f.validate()
        expect(self.f.dialog.get_by_role('textbox', name='P1 层级序号', exact=True)).to_have_value('1.1')
        expect(self.f.dialog.get_by_role('combobox', name='引擎与模型', exact=True)).to_be_visible()
        expect(self.f.dialog.locator('.agent-model-row button, .agent-mode')).to_have_count(0)
        self.assertEqual(self.f.count_post('/apply'), 0)
        self.page.get_by_role('tab', name='AI 分析', exact=True).click()
        expect(self.page.locator('.analysis-form .agent-model-row button, .analysis-form .agent-mode')).to_have_count(0)

    def test_learning_completion_is_beside_picker_and_switches_episode_without_duplicate(self):
        self.f.base.open()
        header = self.page.locator('.learning-context-header')
        checkbox = header.get_by_role('checkbox', name='当前这一讲 P1 已学完', exact=True)
        expect(checkbox).to_be_visible()
        expect(self.page.locator('.playback-resume .learning-player-toggle')).to_have_count(0)
        picker = header.get_by_role('combobox', name='学习项目', exact=True)
        bounds = self.page.evaluate("[...document.querySelectorAll('.learning-header-completion, .learning-context-header .learning-project-picker')].map(e=>e.getBoundingClientRect().toJSON())")
        self.assertLessEqual(bounds[0]['right'], bounds[1]['x'])
        self.assertLess(abs((bounds[0]['y'] + bounds[0]['height']/2) - (bounds[1]['y'] + bounds[1]['height']/2)), 2)
        select_project(picker, self.f.base.identifier(2))
        expect(header.get_by_role('checkbox', name='当前这一讲 P2 已学完', exact=True)).to_be_visible()
        expect(header.get_by_role('checkbox', name='当前这一讲 P1 已学完', exact=True)).to_have_count(0)
        for width in (1440, 760, 390, 320, 280):
            self.page.set_viewport_size({'width': width, 'height': 1000})
            expect(header.get_by_role('checkbox')).to_be_visible()
            self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            self.page.screenshot(path=str(self.f.base.fixture.output / f'learning-header-completion-{width}.png'), full_page=True)
