"""Hold reads in flight: inspect the transition, not only settled screenshots."""
import json, os, unittest
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from playwright.sync_api import expect
from tests.browser import browser_workspace_flow as flow

class SubtitleSwitchStabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): flow.SubtitleFunctionTests.setUpClass()
    @classmethod
    def tearDownClass(cls): flow.SubtitleFunctionTests.tearDownClass()
    def setUp(self):
        self.h = flow.SubtitleFunctionTests('test_function_labels_acquisition_actions_and_no_implicit_work')
        self.h.setUp(); self.addCleanup(self.h.doCleanups)
        self.page = self.h.page; self.card = self.h.card
        self.held = []; self.block = False; self.reads = []; self.platform_text = 'English platform original.'
        self.h.h.base.fixture.context.route('**/projects/*/subtitles?*', self.route)
        self.open()
    def data(self, key):
        selected = next((r for r in self.h.rows if r['resource'] == key), self.h.rows[1])
        text = '这是中文原字幕。' if selected['origin']=='local' else self.platform_text if selected['origin']=='platform' else 'Saved translation '+selected['resource']
        return {'project_id':self.h.h.pid,'has_subtitles':True,'files':self.h.rows[:2], 'versions':self.h.rows,'selected':selected,'text':text,'translations':[]}
    def route(self, route):
        key = parse_qs(urlsplit(route.request.url).query).get('subtitle_resource',[''])[0]; self.reads.append(key)
        if self.block and key == 'subtitles/original.srt': self.held.append(route); return
        route.fulfill(json=self.data(key))
    def open(self):
        self.h.h.open(); self.h.h.choose(0)
        expect(self.card.get_by_label('字幕原文',exact=True)).to_have_value('这是中文原字幕。')
    def switch(self, name): self.card.get_by_role('button',name=name,exact=True).click()
    def geometry(self):
        return self.card.evaluate("e=>{const rect=s=>{const r=e.querySelector(s).getBoundingClientRect();return [r.y+scrollY,r.height]};return [rect('.subtitle-reader'),rect('.subtitle-file-details'),rect('.subtitle-result-actions')].flat()}")
    def assert_still(self, before):
        for a,b in zip(before,self.geometry()): self.assertLessEqual(abs(a-b),1.0)
    def test_delayed_reads_keep_geometry_in_both_themes_and_sizes(self):
        out=Path(os.environ['VIDEO_PARSER_TEST_OUTPUT'])/'switch-states';out.mkdir(parents=True,exist_ok=True);shots=[]
        for theme in ('dark','light'):
            for width in (1440,390):
                self.block=False;self.open();self.page.set_viewport_size({'width':width,'height':1000});self.page.evaluate('(t)=>document.documentElement.dataset.theme=t',theme)
                self.page.evaluate('()=>document.fonts.ready');before=self.geometry()
                def shot(state):
                    n=f'subtitles-switch-{theme}-{width}-{state}.png';self.card.screenshot(path=str(out/n),animations='disabled');shots.append(n)
                shot('before');self.block=True;self.switch('平台下载字幕')
                expect(self.card.locator('.subtitle-reader')).to_have_attribute('aria-busy','true')
                expect(self.card.get_by_label('字幕原文',exact=True)).to_have_value('');self.assert_still(before)
                expect(self.card.get_by_role('status')).to_have_text('正在读取字幕…');self.assert_still(before);shot('loading')
                self.assertTrue(self.held);self.held.pop().fulfill(json=self.data('subtitles/original.srt'))
                expect(self.card.get_by_label('字幕原文',exact=True)).to_have_value(self.platform_text)
                self.assert_still(before);expect(self.card.get_by_role('status')).to_have_count(0);shot('after')
                self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
        (out/'summary.json').write_text(json.dumps({'completed':True,'screenshots':shots,'synthetic_delayed_reads':True}),encoding='utf-8')
        self.assertEqual(self.h.submitted,[])
    def test_cached_roundtrips_do_not_fetch_or_blank_the_reader(self):
        self.switch('平台下载字幕');expect(self.card.get_by_label('字幕原文',exact=True)).to_have_value(self.platform_text)
        count=len(self.reads)
        self.card.evaluate("e=>{window.readerBlanks=[];window.readerObserver=new MutationObserver(()=>{const r=e.querySelector('.subtitle-reader');if(r?.getAttribute('aria-busy')==='true')window.readerBlanks.push(true)});readerObserver.observe(e,{subtree:true,attributes:true,childList:true})}")
        for _ in range(4):
            self.switch('本地生成字幕');expect(self.card.get_by_label('字幕原文',exact=True)).to_have_value('这是中文原字幕。')
            self.switch('平台下载字幕');expect(self.card.get_by_label('字幕原文',exact=True)).to_have_value(self.platform_text)
        self.assertEqual(len(self.reads),count);self.assertEqual(self.page.evaluate('window.readerBlanks'),[])
    def test_error_stays_in_frame_and_retry_does_not_cache_failures(self):
        before=self.geometry();self.block=True;self.switch('平台下载字幕')
        expect(self.card.get_by_role('status')).to_be_visible();self.held.pop().fulfill(status=503,json={'detail':'模拟读取失败，请重新选择。'})
        expect(self.card.get_by_role('alert')).to_have_text('模拟读取失败，请重新选择。');self.assert_still(before)
        expect(self.card.get_by_label('字幕原文',exact=True)).to_have_value('')
        self.switch('本地生成字幕');expect(self.card.get_by_role('alert')).to_have_count(0)
        self.block=False;self.switch('平台下载字幕');expect(self.card.get_by_label('字幕原文',exact=True)).to_have_value(self.platform_text)
        self.assertEqual(self.reads.count('subtitles/original.srt'),2)
    def test_late_cancelled_response_cannot_replace_current_text(self):
        self.block=True;self.switch('平台下载字幕');expect(self.card.get_by_role('status')).to_be_visible()
        old=self.held.pop();self.switch('本地生成字幕')
        expect(self.card.get_by_label('字幕原文',exact=True)).to_have_value('这是中文原字幕。')
        old.fulfill(json=self.data('subtitles/original.srt'))
        self.page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
        expect(self.card.get_by_label('字幕原文',exact=True)).to_have_value('这是中文原字幕。')
        self.switch('平台下载字幕');expect(self.card.get_by_role('status')).to_be_visible()
        self.held.pop().fulfill(json=self.data('subtitles/original.srt'));expect(self.card.get_by_label('字幕原文',exact=True)).to_have_value(self.platform_text)
    def test_mismatched_response_is_rejected_not_cached(self):
        self.block=True;self.switch('平台下载字幕');expect(self.card.get_by_role('status')).to_be_visible()
        self.held.pop().fulfill(json=self.data('subtitles/local.srt'))
        expect(self.card.get_by_role('alert')).to_contain_text('字幕版本已变化')
        expect(self.card.get_by_label('字幕原文',exact=True)).to_have_value('')
    def test_source_list_refresh_invalidates_cached_bodies(self):
        self.switch('平台下载字幕');expect(self.card.get_by_label('字幕原文',exact=True)).to_have_value(self.platform_text)
        self.platform_text='Updated platform after refresh.'
        self.page.evaluate("window.dispatchEvent(new Event('video-parser:subtitles-changed'))")
        expect(self.card.get_by_label('字幕原文',exact=True)).to_have_value(self.platform_text)
        self.switch('本地生成字幕');self.switch('平台下载字幕')
        expect(self.card.get_by_label('字幕原文',exact=True)).to_have_value(self.platform_text)
    def test_formula_and_source_view_fit_the_same_resizable_frame(self):
        before=self.geometry();self.platform_text=r'Formula: \(x^2 + y^2 = 1\)'
        self.switch('平台下载字幕');expect(self.card.locator('.katex')).to_be_visible();self.assert_still(before)
        self.card.get_by_role('button',name='查看原始文本').click()
        expect(self.card.get_by_label('字幕原文',exact=True)).to_have_value(self.platform_text);self.assert_still(before)
        self.card.locator('.subtitle-reader').evaluate("e=>e.style.height='290px'")
        enlarged=self.geometry();self.switch('本地生成字幕');self.assert_still(enlarged)
        self.assertEqual(self.h.submitted,[])

    def test_switch_resets_text_scroll_without_resetting_reader_height(self):
        self.platform_text='\n'.join('Long original line '+str(i) for i in range(100))
        self.switch('平台下载字幕');text=self.card.get_by_label('字幕原文',exact=True)
        expect(text).to_have_value(self.platform_text)
        text.evaluate('e=>e.scrollTop=150');self.assertGreater(text.evaluate('e=>e.scrollTop'),0)
        self.switch('本地生成字幕');self.assertEqual(text.evaluate('e=>e.scrollTop'),0)
        self.switch('平台下载字幕');self.assertEqual(text.evaluate('e=>e.scrollTop'),0)
