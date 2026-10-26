"""Subtitle-parity chapter rows and native scrolling; fixture-only, no real writes."""
import re,unittest
from playwright.sync_api import expect
from tests.browser import browser_markdown_math as harness

ROWS='\n'.join(f'## [{i*2//60:02d}:{i*2%60:02d}] '+ ('这是需要换行但必须完整展示的较长章节标题，介绍线性方程组与空间的几何解释。' if i%4==1 else r'矩阵 \(\begin{bmatrix}1&2\\3&4\end{bmatrix}\)' if i%4==2 else f'第{i+1}章 · 分量 $x_1$') for i in range(30))
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
        self.page.route('**/api/workspace/projects/*/subtitle-cues*',lambda r:r.fulfill(json={'resource':'subtitles/fixture.srt','sources':[{'resource':'subtitles/fixture.srt','label':'测试字幕'}],'cues':[{'time':i*2,'text':f'第{i+1}章 · 分量 $x_1$'} for i in range(30)]}))
        self.h.open(ROWS,learning=True);self.page.get_by_role('tab',name='章节',exact=True).click()
        self.list=self.page.locator('.chapter-timeline-directory .chapter-timeline-list')
    def tearDown(self):self.h.tearDown()
    def toggle(self):return self.page.locator('.chapter-directory-toolbar button')
    def seek(self,time):
        self.page.wait_for_function('()=>{const v=document.querySelector("video");return v.seekable.length>0&&v.seekable.end(0)>60}')
        self.page.locator('video').evaluate('(v,t)=>{v.pause();v.currentTime=t}',time)
        self.page.wait_for_function('!document.querySelector("video").seeking')
    def visible_current(self):
        self.page.wait_for_function('()=>{const l=document.querySelector(".chapter-timeline-list"),b=l.getBoundingClientRect(),r=l.querySelector("[aria-current=true]")?.getBoundingClientRect();return r&&r.top>=b.top-1&&r.bottom<=b.bottom+1}')
    def pause(self):
        self.list.dispatch_event('wheel',{'deltaY':100});expect(self.toggle()).to_have_attribute('aria-pressed','false')
    def test_rows_and_scroll_geometry_match_subtitles_in_both_themes(self):
        style="""e=>{const s=getComputedStyle(e);return Object.fromEntries(['display','padding','gap','borderTopWidth','borderRadius','backgroundColor','fontSize','fontWeight','lineHeight','textAlign','alignItems','outlineWidth','outlineOffset','boxShadow'].map(k=>[k,s[k]]))}"""
        for theme in ('dark','light'):
            self.page.evaluate('(x)=>document.documentElement.dataset.theme=x',theme)
            for width in (1440,768,390,280):
                self.page.set_viewport_size({'width':width,'height':1000});self.seek(.1)
                self.page.evaluate('()=>document.fonts.ready.then(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))))')
                chapter=[self.list.locator('button').nth(i).evaluate(style) for i in (0,3)]
                height=self.list.evaluate('(e)=>e.clientHeight')
                self.page.get_by_role('tab',name='字幕',exact=True).click()
                sub=self.page.locator('#study-panel-subtitles .subtitle-scroll-list');expect(sub.locator('button')).to_have_count(30)
                subtitle=[sub.locator('button').nth(i).evaluate(style) for i in (0,3)]
                self.assertEqual(chapter,subtitle);self.assertEqual(height,sub.evaluate('(e)=>e.clientHeight'),f'{theme} {width}')
                self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                self.page.get_by_role('tab',name='章节',exact=True).click()
        expect(self.list.locator('.katex')).not_to_have_count(0)
    def test_native_free_scrolling_has_no_row_snapping_or_extra_frame(self):
        expect(self.page.locator('.chapter-directory-frame,.chapter-directory-more')).to_have_count(0)
        for width,height in ((1440,1000),(768,800),(390,800),(280,520)):
            self.page.set_viewport_size({'width':width,'height':height});self.pause()
            self.list.evaluate('(l)=>l.scrollTop=137');self.page.wait_for_timeout(240)
            self.assertAlmostEqual(self.list.evaluate('(l)=>l.scrollTop'),137,delta=1)
            before=self.list.evaluate('(l)=>l.clientHeight');self.list.hover();top=self.page.evaluate('scrollY')
            self.page.mouse.wheel(0,137)
            self.page.wait_for_function('document.querySelector(".chapter-timeline-list").scrollTop>138')
            self.assertEqual(self.list.evaluate('(l)=>l.clientHeight'),before)
            self.assertAlmostEqual(self.page.evaluate('scrollY'),top,delta=1)
            self.assertEqual(self.page.locator('.study-sidebar-body').evaluate('(e)=>e.scrollTop'),0)
            self.assertFalse(self.list.evaluate('(e)=>!!e.style.height||e.hasAttribute("data-settled")'))
    def test_manual_browsing_pauses_follow_during_playback_and_toggle_restores(self):
        self.seek(20.2);self.visible_current();self.pause();self.list.evaluate('(l)=>l.scrollTop=0')
        self.page.locator('video').evaluate('(v)=>v.play()')
        self.page.wait_for_function('document.querySelector("video").currentTime>22.1');self.page.locator('video').evaluate('(v)=>v.pause()')
        expect(self.toggle()).to_have_attribute('aria-pressed','false');self.assertEqual(self.list.evaluate('(l)=>l.scrollTop'),0)
        self.toggle().click();expect(self.toggle()).to_have_attribute('aria-pressed','true');self.visible_current()
    def test_media_seek_hidden_tab_and_touch_pause_match_subtitles(self):
        self.pause();self.seek(48.2);expect(self.toggle()).to_have_attribute('aria-pressed','true');self.visible_current()
        self.page.locator('video').dispatch_event('seeking');self.list.dispatch_event('touchmove');expect(self.toggle()).to_have_attribute('aria-pressed','false')
        self.page.locator('video').dispatch_event('seeked');expect(self.toggle()).to_have_attribute('aria-pressed','false')
        self.page.get_by_role('tab',name='个人笔记',exact=True).click();self.seek(30.2)
        self.page.get_by_role('tab',name='章节',exact=True).click();expect(self.toggle()).to_have_attribute('aria-pressed','true');self.visible_current()
        self.pause();self.list.evaluate('(l)=>l.scrollTop=137');self.page.get_by_role('tab',name='字幕',exact=True).click();self.page.get_by_role('tab',name='章节',exact=True).click()
        self.assertAlmostEqual(self.list.evaluate('(l)=>l.scrollTop'),137,delta=1);expect(self.toggle()).to_have_attribute('aria-pressed','false')
    def test_keyboard_scroll_and_chapter_activation_keep_exact_seek(self):
        self.seek(.1);self.list.focus();self.list.press('End');expect(self.toggle()).to_have_attribute('aria-pressed','false')
        self.page.wait_for_function('()=>{const l=document.querySelector(".chapter-timeline-list");return l.scrollTop+l.clientHeight>=l.scrollHeight-2}')
        last=self.list.locator('button').last;last.focus();last.press('Enter')
        self.page.wait_for_function('()=>{const v=document.querySelector("video");return !v.seeking&&v.currentTime>=58&&v.currentTime<59}')
        self.page.locator('video').evaluate('(v)=>v.pause()');expect(last).to_have_attribute('aria-current','true');expect(self.toggle()).to_have_attribute('aria-pressed','true');self.visible_current()
        self.list.focus();self.list.press('Home');expect(self.toggle()).to_have_attribute('aria-pressed','false');self.page.wait_for_function('document.querySelector(".chapter-timeline-list").scrollTop<1')
    def test_short_directory_has_no_hint_and_preserves_full_height(self):
        self.h.open('## [00:01] 唯一章节',learning=True);self.page.get_by_role('tab',name='章节',exact=True).click()
        expect(self.list.locator('li')).to_have_count(1);expect(self.page.get_by_role('button',name='下方还有章节',exact=True)).to_have_count(0)
        self.assertGreater(self.list.evaluate('(l)=>l.clientHeight'),self.list.locator('li').evaluate('(e)=>e.clientHeight'))
        expect(self.toggle()).to_have_attribute('aria-pressed','true')
    def test_accessible_name_player_title_and_current_intro_are_retained(self):
        directory=self.page.get_by_role('region',name='章节目录',exact=True)
        expect(directory.locator('.chapter-timeline-heading,h3')).to_have_count(0);self.assertIsNone(directory.get_attribute('aria-labelledby'))
        expect(self.page.get_by_role('heading',name='AI 章节时间线',exact=True)).to_be_visible();expect(self.list.locator('li')).to_have_count(30)
        self.seek(2.1);expect(self.list.locator('button').nth(1)).to_have_attribute('aria-current','true')
        expect(self.page.locator('.chapter-timeline-intro')).to_contain_text('这是需要换行')
        expect(self.page.locator('.learning-materials .analysis-markdown')).to_have_css('font-size','14px')
        for name in ('章节','个人笔记','AI 对话','字幕'):expect(self.page.get_by_role('tab',name=name,exact=True)).to_be_visible()

if __name__=='__main__':unittest.main()
