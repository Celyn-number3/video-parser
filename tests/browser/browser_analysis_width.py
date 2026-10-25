"""Analysis prose fills its own card; long content stays within the page."""
import unittest
from playwright.sync_api import expect
from tests.browser import browser_markdown_math as math

PARAGRAPH='公司上市时间变晚，私募市场融资规模扩大。普通投资者需要关注参与门槛、流动性和信息披露，不能将概括当作投资建议。'
SUMMARY='## 一句话概括\n\n'+PARAGRAPH*8+'\n\n## 核心要点\n\n- **融资方式变化。** '+PARAGRAPH*4+' [00:12]\n- **市场风险。** '+PARAGRAPH*4+'\n'
TIMELINE='\n\n'.join(f'[{i:02d}:00] 章节{i+1} —— '+PARAGRAPH*3 for i in range(3))

class AnalysisWidthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):math.MarkdownMathBrowserTests.setUpClass()
    @classmethod
    def tearDownClass(cls):math.MarkdownMathBrowserTests.tearDownClass()
    def setUp(self):
        self.h=math.MarkdownMathBrowserTests('test_all_four_delimiters_and_multiline_matrix');self.h.setUp();self.addCleanup(self.h.tearDown);self.page=self.h.page
    def assert_width(self):
        md=self.page.locator('.analysis-markdown');expect(md).to_have_css('max-width','none')
        self.page.evaluate('()=>document.fonts.ready')
        bounds=md.evaluate('''e=>{const p=e.parentElement,s=getComputedStyle(p);return {body:e.getBoundingClientRect().width,available:p.clientWidth-parseFloat(s.paddingLeft)-parseFloat(s.paddingRight),page:document.documentElement.scrollWidth,viewport:innerWidth}}''')
        self.assertAlmostEqual(bounds['body'],bounds['available'],delta=1)
        self.assertLessEqual(bounds['page'],bounds['viewport'])
        return bounds
    def test_summary_fills_card_in_analysis_and_learning_without_changing_text_or_font(self):
        for learning in (False,True):
            self.page.set_viewport_size({'width':1440,'height':1000})
            self.h.open(SUMMARY,learning=learning);md=self.page.locator('.analysis-markdown');before=md.inner_text();font=md.evaluate('(e)=>getComputedStyle(e).fontSize')
            for theme in ('dark','light'):
                self.page.evaluate('(x)=>document.documentElement.dataset.theme=x',theme)
                for width in (1440,1308,1920,390,280):
                    self.page.set_viewport_size({'width':width,'height':1000});bounds=self.assert_width()
                    if not learning and width>=1308:self.assertGreater(bounds['body'],850)
                    self.assertEqual(md.inner_text(),before);expect(md).to_have_css('font-size',font)
                    expect(md.locator('.md-time')).to_have_count(1)
            if learning:expect(md).to_have_css('font-size','14px')
        self.assertEqual(self.h.record['text'],SUMMARY)
    def test_chapter_paragraphs_fill_card_in_both_contexts(self):
        self.h.record.update(template='chapters',template_name='章节时间轴')
        for learning in (False,True):
            self.page.set_viewport_size({'width':1440,'height':1000})
            self.h.open(TIMELINE,learning=learning)
            for width in (1440,1308,390,280):
                self.page.set_viewport_size({'width':width,'height':1000});self.assert_width()
            expect(self.page.locator('.analysis-markdown p')).to_have_count(3)
            self.assertEqual(self.h.record['text'],TIMELINE)
    def test_long_formula_table_code_and_timestamp_keep_local_overflow_and_seek(self):
        text=SUMMARY+'\n\n$$'+ '+'.join('x_{'+str(i)+'}' for i in range(100))+'$$\n\n```text\n'+'column_'*120+'\n```\n\n| '+ ' | '.join('表头'+str(i) for i in range(14))+' |\n| '+' | '.join('---' for _ in range(14))+' |\n| '+' | '.join('很长的单元格' for _ in range(14))+' |'
        self.h.open(text)
        for width in (1440,390,280):
            self.page.set_viewport_size({'width':width,'height':1000});self.assert_width()
            for selector in ('.md-math-display','pre','.md-table'):
                expect(self.page.locator('.analysis-markdown '+selector)).to_have_css('overflow-x','auto')
        expect(self.page.locator('.analysis-markdown .katex')).to_have_count(1)
        self.page.locator('.analysis-markdown .md-time').click()
        expect(self.page.get_by_role('heading',name='学习视图',exact=True)).to_be_visible();self.page.wait_for_function('document.querySelector("video").currentTime>=12')
        self.page.locator('video').evaluate('(v)=>v.pause()');self.assert_width();self.assertEqual(self.h.record['text'],text)
