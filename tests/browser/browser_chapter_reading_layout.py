"""Synthetic variable-height chapter scrolling; never real generation or archive writes."""
import re,unittest
from playwright.sync_api import expect
from tests.browser import browser_markdown_math as harness

ROWS='\n'.join(f'## [{i*2//60:02d}:{i*2%60:02d}] '+ ('这是需要换行但必须完整展示的较长章节标题，介绍线性方程组与空间的几何解释。' if i%4==1 else r'矩阵 \(\begin{bmatrix}1&2\\3&4\end{bmatrix}\)' if i%4==2 else f'第{i+1}章 · 分量 $x_1$') for i in range(30))
WHOLE='''() => {
 const l=document.querySelector('.chapter-timeline-directory .chapter-timeline-list');if(!l)return false;
 const box=l.getBoundingClientRect();if(box.height<1)return false;
 const visible=[...l.children].map(e=>e.getBoundingClientRect()).filter(r=>r.bottom>box.top+1&&r.top<box.bottom-1);
 return visible.length>0&&visible.every(r=>r.top>=box.top-1&&r.bottom<=box.bottom+1);
}'''

class ChapterReadingLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):harness.MarkdownMathBrowserTests.setUpClass()
    @classmethod
    def tearDownClass(cls):harness.MarkdownMathBrowserTests.tearDownClass()
    def setUp(self):
        self.h=harness.MarkdownMathBrowserTests('test_all_four_delimiters_and_multiline_matrix');self.h.setUp()
        self.page=self.h.page;self.h.record.update(template='chapters',template_name='章节时间轴')
        # This fixture must support byte ranges to exercise seeking far into the WAV.
        def media(route):
            data=self.h.f.audio;headers={'Content-Type':'audio/wav','Accept-Ranges':'bytes'}
            match=re.fullmatch(r'bytes=(\d+)-(\d*)',route.request.headers.get('range',''))
            if match:
                start=int(match[1]);end=min(int(match[2]) if match[2] else len(data)-1,len(data)-1)
                if start>end:return route.fulfill(status=416,headers={'Content-Range':f'bytes */{len(data)}'},body=b'')
                headers['Content-Range']=f'bytes {start}-{end}/{len(data)}'
                return route.fulfill(status=206,headers=headers,body=data[start:end+1])
            return route.fulfill(headers=headers,body=data)
        self.page.route('**/product-fixture.wav',media)
        self.h.open(ROWS,learning=True);self.page.get_by_role('tab',name='章节',exact=True).click()
        self.list=self.page.locator('.chapter-timeline-directory .chapter-timeline-list')
    def tearDown(self):self.h.tearDown()
    def whole(self):self.page.wait_for_function(WHOLE)
    def test_variable_rows_wheel_keyboard_resize_and_inner_frame(self):
        expect(self.page.locator('.learning-materials .analysis-markdown')).to_have_css('font-size','14px')
        self.whole();frame=self.page.locator('.chapter-directory-frame')
        expect(frame).to_have_css('border-top-width','1px');expect(frame).to_have_css('padding-top','8px')
        for width,height in [(1440,1000),(1170,800),(768,800),(390,800),(280,520)]:
            self.page.set_viewport_size({'width':width,'height':height})
            self.page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');self.whole()
            self.list.hover();old=self.list.evaluate('(l)=>l.scrollTop');page_top=self.page.evaluate('scrollY')
            self.page.mouse.wheel(0,137)
            self.page.wait_for_function('(old)=>document.querySelector(".chapter-timeline-list").scrollTop>old+1',arg=old)
            self.whole();self.assertAlmostEqual(self.page.evaluate('scrollY'),page_top,delta=1)
            self.assertEqual(self.page.locator('.study-sidebar-body').evaluate('(e)=>e.scrollTop'),0)
            self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
        self.list.focus();self.page.keyboard.press('End')
        self.page.wait_for_function('()=>{const l=document.querySelector(".chapter-timeline-list");return l.scrollTop+l.clientHeight>=l.scrollHeight-2}')
        self.whole();expect(self.list.locator('li').last).to_be_in_viewport()
        self.page.keyboard.press('Home');self.page.wait_for_function('document.querySelector(".chapter-timeline-list").scrollTop<1');self.whole()
    def test_current_chapter_focus_and_tab_switch(self):
        self.page.wait_for_function('()=>{const v=document.querySelector("video");return v.seekable.length>0&&v.seekable.end(0)>48}')
        self.page.locator('video').evaluate('(v)=>{v.pause();v.currentTime=48.2;v.dispatchEvent(new Event("timeupdate"));}')
        current=self.list.locator('button[aria-current=true]');expect(current).to_contain_text('第25章')
        self.whole();expect(current).to_be_in_viewport()
        page_top=self.page.evaluate('scrollY')
        last=self.list.locator('button').last;last.focus();self.whole()
        expect(last).to_be_in_viewport()
        self.assertAlmostEqual(self.page.evaluate('scrollY'),page_top,delta=1)
        self.assertEqual(self.page.locator('.study-sidebar-body').evaluate('(e)=>e.scrollTop'),0)
        self.page.keyboard.press('Enter');self.page.wait_for_function('document.querySelector("video").currentTime>=58.1');self.page.locator('video').evaluate('(v)=>v.pause()')
        self.whole();expect(last).to_have_attribute('aria-current','true')
        self.page.get_by_role('tab',name='个人笔记',exact=True).click()
        self.page.get_by_role('tab',name='章节',exact=True).click();self.whole();expect(last).to_be_in_viewport()
        for theme in ('dark','light'):
            self.page.evaluate('(v)=>document.documentElement.dataset.theme=v',theme)
            for width in (1440,390):
                self.page.set_viewport_size({'width':width,'height':1000});self.whole()
                self.page.locator('.study-sidebar').screenshot(path=str(self.h.f.output/f'chapter-frame-{theme}-{width}.png'),animations='disabled')
        self.page.locator('.learning-materials').screenshot(path=str(self.h.f.output/'reading-14px.png'),animations='disabled')

    def test_continue_hint_scrolls_without_seeking_and_disappears_at_end(self):
        self.whole();hint=self.page.get_by_role('button',name='下方还有章节',exact=True)
        expect(hint).to_be_visible();before=self.page.locator('video').evaluate('(v)=>{v.pause();return v.currentTime}')
        height=self.list.evaluate('(l)=>l.parentElement.clientHeight')
        hint.click();self.page.wait_for_function('document.querySelector(".chapter-timeline-list").scrollTop>0');self.whole()
        self.assertAlmostEqual(self.page.locator('video').evaluate('(v)=>v.currentTime'),before,delta=.1)
        self.list.focus();self.page.keyboard.press('End');self.whole();expect(hint).to_have_count(0)
        self.assertEqual(self.list.evaluate('(l)=>l.parentElement.clientHeight'),height)
        self.page.keyboard.press('Home');self.whole();expect(hint).to_be_visible()
        self.assertFalse(any(path=='/translations' for _,path,_ in getattr(self.h,'calls',[])))

    def test_short_directory_needs_no_continue_hint(self):
        self.h.open('## [00:01] 唯一章节',learning=True)
        self.page.get_by_role('tab',name='章节',exact=True).click()
        expect(self.page.locator('.chapter-timeline-directory .chapter-timeline-list li')).to_have_count(1)
        self.whole();expect(self.page.get_by_role('button',name='下方还有章节',exact=True)).to_have_count(0)

    def test_directory_has_no_redundant_heading_but_keeps_controls_and_accessible_name(self):
        directory=self.page.get_by_role('region',name='章节目录',exact=True)
        expect(directory).to_have_count(1);expect(directory.locator('.chapter-timeline-heading,h3')).to_have_count(0)
        self.assertIsNone(directory.get_attribute('aria-labelledby'))
        self.assertEqual(directory.evaluate('(e)=>e.firstElementChild.className'),'chapter-directory-frame')
        expect(self.page.get_by_role('heading',name='AI 章节时间线',exact=True)).to_be_visible()
        expect(self.list.locator('li')).to_have_count(30)
        for theme in ('dark','light'):
            self.page.evaluate('(x)=>document.documentElement.dataset.theme=x',theme)
            for width in (1440,390,280):
                self.page.set_viewport_size({'width':width,'height':1000});self.whole()
                for name in ('章节','个人笔记','AI 对话','字幕'):
                    expect(self.page.get_by_role('tab',name=name,exact=True)).to_be_visible()
                expect(self.page.get_by_role('button',name='下方还有章节',exact=True)).to_be_visible()
                self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
        self.page.set_viewport_size({'width':1440,'height':1000});self.whole()
        self.page.wait_for_function('()=>{const v=document.querySelector("video");return v.seekable.length>0&&v.seekable.end(0)>2}')
        self.list.locator('button').nth(1).click()
        self.page.wait_for_function('()=>{const v=document.querySelector("video");return !v.seeking&&v.currentTime>=2&&v.currentTime<3}')
        self.page.locator('video').evaluate('(v)=>v.pause()');expect(self.list.locator('button').nth(1)).to_have_attribute('aria-current','true')

if __name__=='__main__':unittest.main()
