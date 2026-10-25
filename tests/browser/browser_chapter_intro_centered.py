"""Default-expanded chapter intro and true card-centered time/title; fixture APIs only."""
import unittest
from playwright.sync_api import expect
from tests.browser import browser_markdown_math as math

TEXT='## [00:00] 开场\n这是第一章的介绍。\n## [00:12] 中国私募市场的退出与 S 基金\n说明投资门槛、最低投资额与退出方式。\n## [00:24] 结语\n'
GEOMETRY='''() => {
 const c=document.querySelector('.chapter-timeline-player .chapter-timeline-intro'),g=c.querySelector('.chapter-timeline-current-heading'),n=c.querySelector('.chapter-timeline-intro-meta'),t=g.querySelector('time'),h=g.querySelector('h4');
 const r=c.getBoundingClientRect(),a=g.getBoundingClientRect(),b=n.getBoundingClientRect(),x=t.getBoundingClientRect(),y=h.getBoundingClientRect();
 return {center:Math.abs((a.left+a.right-r.left-r.right)/2),ink:Math.abs((Math.min(x.left,y.left)+Math.max(x.right,y.right)-r.left-r.right)/2),overlap:Math.min(a.right,b.right)-Math.max(a.left,b.left)>1&&Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>1,countLeft:Math.abs(b.left-r.left),clipped:g.scrollWidth>g.clientWidth+1,overflow:document.documentElement.scrollWidth>innerWidth,rangeWrap:x.height>28,title:g.innerText};
}'''
class ChapterIntroCenteredTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):math.MarkdownMathBrowserTests.setUpClass()
    @classmethod
    def tearDownClass(cls):math.MarkdownMathBrowserTests.tearDownClass()
    def setUp(self):
        self.h=math.MarkdownMathBrowserTests('test_all_four_delimiters_and_multiline_matrix');self.h.setUp();self.addCleanup(self.h.tearDown);self.page=self.h.page
        self.h.record.update(template='chapters',template_name='章节时间轴')
        self.second={**self.h.record,'id':'20261026-090000-aabbccdd','text':'## [00:00] 另一份章节记录\n另一份记录的介绍。'};self.h.f.records.append(self.second)
        self.h.open(TEXT,learning=True);self.page.get_by_role('combobox',name='选择学习材料',exact=True).select_option(self.h.record['id'])
        self.player=self.page.locator('.chapter-timeline-player');self.intro=self.player.locator('.chapter-timeline-intro');self.details=self.player.locator('details');self.video=self.page.locator('video')
        self.page.wait_for_function('document.querySelector("video").readyState>=1');self.video.evaluate('(v)=>v.pause()')
        expect(self.details).to_have_attribute('open','')
    def go(self,index):
        self.player.locator('.chapter-timeline-marker').nth(index).click()
        target=(0,12,24)[index];self.page.wait_for_function('(s)=>document.querySelector("video").currentTime>=s',arg=target)
        self.video.evaluate('(v)=>v.pause()');expect(self.player.locator('.chapter-timeline-marker').nth(index)).to_have_attribute('aria-current','true')
    def geometry(self):
        value=self.page.evaluate(GEOMETRY)
        self.assertLess(value['center'],1,value);self.assertLess(value['ink'],1,value);self.assertLess(value['countLeft'],1,value)
        self.assertFalse(value['overlap'] or value['clipped'] or value['overflow'] or value['rangeWrap'],value)
    def test_default_open_toggle_and_chapter_changes(self):
        expect(self.details.locator('p')).to_be_visible();expect(self.details).to_contain_text('这是第一章的介绍。')
        self.go(1);expect(self.details).to_have_attribute('open','');expect(self.details).to_contain_text('说明投资门槛')
        self.details.locator('summary').click();expect(self.details.locator('p')).to_be_hidden()
        self.go(2);expect(self.details.locator('p')).to_be_hidden()
        self.details.locator('summary').click();expect(self.details.locator('p')).to_be_visible();expect(self.details).to_contain_text('暂无详细介绍')
    def test_time_title_centered_in_both_themes_and_card_sizes(self):
        self.go(1)
        for theme in ('dark','light'):
            self.page.evaluate('(x)=>document.documentElement.dataset.theme=x',theme)
            for width in (1920,1440,1024,768,390,280):
                self.page.set_viewport_size({'width':width,'height':1000});self.geometry();expect(self.details.locator('p')).to_be_visible()
                self.player.screenshot(path=str(self.h.f.output/f'chapter-intro-{theme}-{width}.png'),animations='disabled')
    def test_long_title_and_formula_wrap_without_overlap(self):
        self.h.open('## [00:00] '+('这是需要换行但不能裁切的较长章节标题'*6)+r' \(x_1\)'+'\n介绍中的公式'+r' \(x^2\)'+'。',learning=True)
        for width in (1440,768,390,280):
            self.page.set_viewport_size({'width':width,'height':1000});self.geometry()
            expect(self.intro.locator('h4')).to_contain_text('这是需要换行');expect(self.details.locator('.katex')).to_have_count(1)
        self.player.screenshot(path=str(self.h.f.output/'chapter-intro-long-title-280.png'),animations='disabled')
    def test_new_record_and_reload_restore_default_open(self):
        self.details.locator('summary').click();expect(self.details.locator('p')).to_be_hidden()
        self.video.evaluate('(v)=>window.chapterPlayerBefore=v')
        self.page.get_by_role('combobox',name='选择学习材料',exact=True).select_option(self.second['id'])
        expect(self.details).to_have_attribute('open','');expect(self.details.locator('p')).to_be_visible();expect(self.details).to_contain_text('另一份记录的介绍')
        self.assertTrue(self.video.evaluate('(v)=>v===window.chapterPlayerBefore'))
        self.details.locator('summary').click();self.page.reload();self.page.get_by_role('button',name='学习视图',exact=True).click()
        expect(self.details).to_have_attribute('open','');expect(self.details.locator('p')).to_be_visible()
