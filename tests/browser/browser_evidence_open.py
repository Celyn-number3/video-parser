"""Default-open evidence with native disclosure interactions; fixture-only."""
import unittest
from playwright.sync_api import expect
from tests.browser import browser_markdown_math as math

class EvidenceOpenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):math.MarkdownMathBrowserTests.setUpClass()
    @classmethod
    def tearDownClass(cls):math.MarkdownMathBrowserTests.tearDownClass()
    def test_default_open_toggle_switch_reload_and_lightbox(self):
        h=math.MarkdownMathBrowserTests('test_all_four_delimiters_and_multiline_matrix');h.setUp();self.addCleanup(h.tearDown);p=h.page
        frame={'url':'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="320" height="180"%3E%3Crect width="320" height="180" fill="teal"/%3E%3C/svg%3E','label':'00:12','seconds':12}
        h.record.update(frames=[frame],frame_count=1)
        other={**h.record,'id':'fixture-evidence-second','template':'chapters','template_name':'章节时间轴'}
        h.f.records=[h.record,other];h.open()
        evidence=p.locator('.analysis-evidence');summary=evidence.locator('summary');image=evidence.locator('img')
        expect(evidence).to_have_attribute('open','');expect(image).to_be_visible()
        summary.click();expect(evidence).not_to_have_attribute('open','');expect(image).to_be_hidden()
        summary.focus();summary.press('Enter');expect(image).to_be_visible()
        evidence.get_by_role('button').click();expect(p.get_by_role('dialog')).to_be_visible();p.keyboard.press('Escape');expect(p.get_by_role('dialog')).to_have_count(0)
        summary.click();expect(image).to_be_hidden()
        picker=p.get_by_role('combobox',name='选择分析记录',exact=True);picker.select_option(other['id']);expect(evidence).to_have_attribute('open','')
        summary.click();picker.select_option(h.record['id']);expect(image).to_be_visible()
        summary.click();p.reload();p.get_by_role('tab',name='AI 分析',exact=True).click();expect(evidence).to_have_attribute('open','');expect(image).to_be_visible()
