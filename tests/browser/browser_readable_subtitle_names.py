"""Readable version labels with accessible on-demand filesystem details."""
import unittest
from playwright.sync_api import expect
from tests.browser import browser_translation_status as harness

class ReadableSubtitleBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):harness.TranslationStatusBrowserTests.setUpClass()
    @classmethod
    def tearDownClass(cls):harness.TranslationStatusBrowserTests.tearDownClass()
    def setUp(self):
        self.h=harness.TranslationStatusBrowserTests('test_saved_translation_survives_reload_without_any_remembered_task');self.h.setUp();self.page=self.h.page
    def tearDown(self):self.h.tearDown()
    def test_short_labels_hidden_file_details_and_no_middle_dot(self):
        self.h.completed=True;self.h.open();self.h.choose(0)
        card=self.page.get_by_role('region',name='当前视频字幕',exact=True)
        expect(card.locator('.subtitle-selected-title')).to_have_text('合成课程甲 P1')
        select=card.get_by_role('combobox',name='字幕版本',exact=True)
        expect(select.locator('option')).to_have_text(['英文原文（SRT）'])
        expect(card.locator('.subtitle-version-file')).to_be_hidden()
        self.assertNotIn('·',card.inner_text())
        self.assertNotIn('·',self.page.locator('.source-list').inner_text())
        expect(self.page.locator('.source-meta').first).to_have_css('display','flex')
        expect(self.page.locator('.source-meta').first).to_have_css('column-gap','10px')
        details=card.locator('.subtitle-file-details');details.locator('summary').focus();self.page.keyboard.press('Enter')
        expect(card.locator('.subtitle-version-file')).to_contain_text('P01_原始字幕.srt')
        expect(card.get_by_role('button',name='打开文件夹',exact=True)).to_be_visible()
        details.locator('summary').click()
        card.get_by_role('button',name='AI翻译字幕',exact=True).click()
        expect(select.locator('option')).to_have_text(['B站平台字幕 → 中文译文　时间未记录（SRT）'])
        expect(card.get_by_label('译文',exact=True)).to_have_value(self.h.translation_job()['text'])
        for theme in ('dark','light'):
            self.page.evaluate('(t)=>document.documentElement.dataset.theme=t',theme)
            active=card.locator('.subtitle-view-sources button[aria-pressed=true]');active.hover()
            active.evaluate('async e => { await Promise.allSettled(e.getAnimations().map(a => a.finished)); }')
            contrast=active.evaluate(r"""e=>{const c=getComputedStyle(e),lum=x=>{const v=x.match(/[\d.]+/g).slice(0,3).map(x=>{x=+x/255;return x<=.04045?x/12.92:((x+.055)/1.055)**2.4});return .2126*v[0]+.7152*v[1]+.0722*v[2]};const a=lum(c.color),b=lum(c.backgroundColor);return (Math.max(a,b)+.05)/(Math.min(a,b)+.05)}""")
            self.assertGreaterEqual(contrast,4.5)
        for width in (1440,390,280):
            self.page.set_viewport_size({'width':width,'height':900})
            self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
        self.assertFalse(any(m=='POST' and p=='/translations' for m,p,_ in self.h.calls))

if __name__=='__main__':unittest.main()
