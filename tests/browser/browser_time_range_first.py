"""Display-only range citations, safe boundaries and both seek targets."""
import unittest
from playwright.sync_api import expect
from tests.browser import browser_markdown_math as math

VARIANTS=['([00:12]–[00:24])','（00:12 - 00:24）','[00:12–00:24]','00:12～00:24','[00:12]—[00:24]','(00:12至00:24)']
class TimeRangeFirstTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):math.MarkdownMathBrowserTests.setUpClass()
    @classmethod
    def tearDownClass(cls):math.MarkdownMathBrowserTests.tearDownClass()
    def setUp(self):
        self.h=math.MarkdownMathBrowserTests('test_all_four_delimiters_and_multiline_matrix');self.h.setUp();self.addCleanup(self.h.tearDown);self.page=self.h.page
    def test_variants_move_before_bold_list_text_in_both_contexts(self):
        text='\n'.join('- **要点。** 正文保留（普通解释）。 '+x for x in VARIANTS)
        for learning in (False,True):
            self.page.set_viewport_size({'width':1440,'height':1000});self.h.open(text,learning=learning)
            md=self.page.locator('.analysis-markdown');expect(md.locator('.md-time-range')).to_have_count(len(VARIANTS))
            for li in md.locator('li').all():
                self.assertEqual(li.evaluate('(e)=>e.firstElementChild.className'),'md-time-range')
                expect(li.locator('.md-time-range .md-time')).to_have_text(['00:12','00:24'])
                expect(li.locator('strong')).to_have_text('要点。');expect(li).to_contain_text('正文保留（普通解释）。')
                self.assertNotRegex(li.locator('.md-time-range').inner_text(),r'[()（）\[\]]')
            for theme in ('dark','light'):
                self.page.evaluate('(x)=>document.documentElement.dataset.theme=x',theme)
                for width in (1440,390,280):
                    self.page.set_viewport_size({'width':width,'height':1000})
                    self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                    r=md.locator('.md-time-range').first
                    self.assertTrue(r.evaluate('(e)=>{const a=e.firstElementChild.getBoundingClientRect(),b=e.lastElementChild.getBoundingClientRect();return Math.abs(a.top-b.top)<1}'))
            self.assertEqual(self.h.record['text'],text)
    def test_paragraph_leading_range_and_nested_list(self):
        text='段落内容 (00:12-00:24)。\n\n（00:12–00:24） 已经在开头。\n\n1. 父项 [00:12]–[00:24]\n   - 子项 （00:12-00:24）\n\n## [00:12] 章节标题\n\n[00:12] 单点章节不移动。'
        self.h.open(text);md=self.page.locator('.analysis-markdown');expect(md.locator('.md-time-range')).to_have_count(4)
        for p in md.locator(':scope > p').all()[:2]:self.assertEqual(p.evaluate('(e)=>e.firstElementChild.className'),'md-time-range')
        expect(md.locator('h4 .md-time')).to_have_count(1);expect(md.locator('h4 .md-time-range')).to_have_count(0)
        self.assertEqual(self.h.record['text'],text)
    def test_code_math_links_invalid_and_mid_sentence_are_not_relocated(self):
        text=r'''代码 `(00:12–00:24)`

数学 \(00:12-00:24\)

[00:12–00:24](https://example.invalid/ref)

正文 (00:99-00:24)

反向 (00:24-00:12)

超过片长 (00:12-12:24)

错位方括号 00:12]–[00:24

未闭合 (00:12-00:24

中间 00:12–00:24 的内容不搬动。

普通（解释）。

```text
(00:12–00:24)
```
'''
        self.h.open(text);md=self.page.locator('.analysis-markdown');expect(md.locator('.md-time-range')).to_have_count(0)
        expect(md.locator('.katex')).to_have_count(1);expect(md.locator('pre code')).to_have_text('(00:12–00:24)');expect(md.locator('a')).to_have_attribute('href','https://example.invalid/ref')
        self.assertEqual(self.h.record['text'],text)
    def test_both_range_endpoints_seek_to_their_own_times(self):
        self.h.open('- 测试要点 ([00:12]–[00:24])')
        for n,seconds in enumerate((12,24)):
            self.page.locator('.analysis-markdown .md-time-range .md-time').nth(n).click()
            expect(self.page.get_by_role('heading',name='学习视图',exact=True)).to_be_visible()
            self.page.wait_for_function('(x)=>document.querySelector("video").currentTime>=x',arg=seconds)
            self.page.locator('video').evaluate('(v)=>v.pause()');self.assertLess(self.page.locator('video').evaluate('(v)=>v.currentTime'),seconds+1)
    def test_other_markdown_chat_does_not_opt_in(self):
        text='对话原文 (00:12–00:24)'
        self.h.f.sessions=[{'id':'f'*32,'title':'已有测试对话','video_resource':self.h.f.resource,'origin_record':None,'agent':{'engine':'api','model':'','effort':''},'messages':[{'id':'one','question':'测试','answer':text,'position':0,'created_at':''}],'created_at':'','updated_at':''}]
        self.h.open(learning=True);self.page.get_by_role('tab',name='AI 对话',exact=True).click()
        chat=self.page.locator('.ai-chat-answer .markdown').first;expect(chat).to_be_visible();expect(chat.locator('.md-time-range')).to_have_count(0);expect(chat).to_contain_text(text)
