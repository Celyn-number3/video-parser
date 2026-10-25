"""User-approved combined result/format choices: three results, six choices."""
import unittest,re
from urllib.parse import urlsplit,parse_qs
from playwright.sync_api import expect
from tests.browser import browser_translation_status as harness

class SubtitleVersionsBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):harness.TranslationStatusBrowserTests.setUpClass()
    @classmethod
    def tearDownClass(cls):harness.TranslationStatusBrowserTests.tearDownClass()
    def setUp(self):
        self.h=harness.TranslationStatusBrowserTests('test_saved_translation_survives_reload_without_any_remembered_task');self.h.setUp();self.addCleanup(self.h.tearDown);self.page=self.h.page
        self.same_day=False;self.hold_txt=False;self.held=[];self.reads=[]
        self.h.base.fixture.context.route('**/projects/*/subtitles*',self.route)
    def payload(self,key):
        original={'resource':'subtitles/original.srt','filename':'原文.srt','kind':'subtitle','origin':'platform','language':'','url':'/fixture'}
        rows=[original]
        for i in range(3):
            for fmt in ('srt','txt'):
                rows.append({'resource':f'subtitles/{i}.{fmt}','version_id':f'result-{i}','format':fmt.upper(),'filename':f'译文{i}.{fmt}','kind':'translation','origin':'translation','language':'zh' if i==0 else 'en','source_origin':'local' if i==0 else 'platform','source_language':'en' if i==0 else '', 'generated_at':1792841694 if i<2 or self.same_day else 1792368643,'url':'/fixture'})
        selected=next((r for r in rows if r['resource']==key),original)
        return {'project_id':self.h.pid,'has_subtitles':True,'files':[original],'versions':rows,'selected':selected,'text':selected['resource']+' body','translations':[]}
    def route(self,route):
        key=parse_qs(urlsplit(route.request.url).query).get('subtitle_resource',[''])[0];self.reads.append(key)
        if self.hold_txt and key.endswith('.txt'):self.held.append((route,key));return
        route.fulfill(json=self.payload(key))
    def open_ai(self):
        self.h.open();self.h.choose(0);card=self.page.get_by_role('region',name='当前视频字幕',exact=True);card.get_by_role('button',name='AI翻译字幕',exact=True).click()
        expect(card.get_by_label('译文',exact=True)).to_have_value('subtitles/0.srt body')
        expect(card.get_by_role('button',name='AI 中英互译',exact=True)).to_be_visible()
        return card,card.get_by_role('combobox',name='字幕版本',exact=True)
    def test_three_results_six_format_choices_and_reload(self):
        card,select=self.open_ai();expect(select.locator('option')).to_have_count(6)
        labels=select.locator('option').all_text_contents();self.assertEqual(len(set(labels)),6);self.assertIn('本地英文转写 → 中文译文',labels[0])
        for i in range(3):
            for j,fmt in enumerate(('srt','txt')):
                self.assertTrue(labels[i*2+j].endswith('（'+fmt.upper()+'）'))
                select.select_option(f'subtitles/{i}.{fmt}');expect(card.get_by_label('译文',exact=True)).to_have_value(f'subtitles/{i}.{fmt} body')
                expect(select).to_have_value(f'subtitles/{i}.{fmt}')
                expect(card.locator('.subtitle-selected-format')).to_have_text(fmt.upper())
                details=card.locator('.subtitle-file-details')
                if details.get_attribute('open') is None:details.locator('summary').click()
                expect(card.get_by_role('combobox',name='文件格式',exact=True)).to_have_count(0)
                expect(card.locator('.subtitle-version-file')).to_contain_text(f'译文{i}.{fmt}')
        self.assertTrue(all(f'subtitles/{i}.{fmt}' in self.reads for i in range(3) for fmt in ('srt','txt')))
        self.page.reload();self.page.get_by_role('button',name=re.compile(r'^已归档视频')).click();self.h.choose(0);card.get_by_role('button',name='AI翻译字幕',exact=True).click();expect(select.locator('option')).to_have_count(6)
        self.assertFalse(any(m=='POST' and p=='/translations' for m,p,_ in self.h.calls))
    def test_format_pairs_keep_the_same_result_number_on_same_second(self):
        self.same_day=True;card,select=self.open_ai();labels=select.locator('option').all_text_contents()
        for i in range(3):self.assertEqual(labels[2*i].removesuffix('（SRT）'),labels[2*i+1].removesuffix('（TXT）'))
        self.assertIn('版本1',labels[2]);self.assertIn('版本2',labels[4]);self.assertEqual(len(set(labels)),6)
    def test_format_switch_preserves_reading_frame_and_cached_return(self):
        card,select=self.open_ai()
        geometry=lambda:card.evaluate("e=>{const r=e.querySelector('.subtitle-reader').getBoundingClientRect(),a=e.querySelector('.subtitle-file-details').getBoundingClientRect();return [r.y+scrollY,r.height,a.y+scrollY]}")
        before=geometry();self.hold_txt=True;select.select_option('subtitles/0.txt')
        expect(card.get_by_role('status')).to_have_text('正在读取字幕…');expect(card.get_by_label('译文',exact=True)).to_have_value('')
        self.assertEqual(before,geometry());route,key=self.held.pop();route.fulfill(json=self.payload(key))
        expect(card.get_by_label('译文',exact=True)).to_have_value('subtitles/0.txt body');self.assertEqual(before,geometry())
        count=len(self.reads);select.select_option('subtitles/0.srt');expect(card.get_by_label('译文',exact=True)).to_have_value('subtitles/0.srt body')
        select.select_option('subtitles/0.txt');expect(card.get_by_label('译文',exact=True)).to_have_value('subtitles/0.txt body');self.assertEqual(count,len(self.reads))
        self.assertFalse(any(m=='POST' and p=='/translations' for m,p,_ in self.h.calls))
