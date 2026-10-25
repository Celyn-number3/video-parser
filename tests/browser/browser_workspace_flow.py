"""Synthetic pagination and subtitle-function regressions; all APIs mocked."""
import re,unittest
from urllib.parse import urlsplit,parse_qs
from playwright.sync_api import expect
from tests.browser import browser_product_improvements as tasks
from tests.browser import browser_translation_status as subtitles

class PaginationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):tasks.ProductImprovementsBrowserTests.setUpClass()
    @classmethod
    def tearDownClass(cls):tasks.ProductImprovementsBrowserTests.tearDownClass()
    def setUp(self):
        self.h=tasks.ProductImprovementsBrowserTests('test_task_facets_search_counts_and_recovery_after_clear');self.h.setUp();self.addCleanup(self.h.tearDown);self.page=self.h.page
        self.h.jobs=[{'id':f'{i+1:032x}','kind':'transcriptions','project_id':None,'state':'completed' if i%2 else 'failed','file_names':[f'episode-{i:03d}.srt']} for i in range(75)]
        self.page.goto(self.h.url+'?page=tasks');self.rows=self.page.locator('.task-list > li');self.nav=self.page.get_by_role('navigation',name='任务分页')
        expect(self.rows).to_have_count(20)
    def test_pages_filters_counts_and_mobile(self):
        expect(self.nav).to_contain_text('共 75 条');expect(self.nav.get_by_role('button',name='上一页')).to_be_disabled()
        self.nav.get_by_role('button',name='第 4 页',exact=True).click();expect(self.rows).to_have_count(15);expect(self.rows.first).to_contain_text('episode-060')
        expect(self.nav.get_by_role('button',name='下一页')).to_be_disabled()
        current=self.nav.locator('button[aria-current=page]')
        for theme in ('dark','light'):
            self.page.evaluate('(t)=>document.documentElement.dataset.theme=t',theme);current.hover()
            current.evaluate('async e=>{await Promise.allSettled(e.getAnimations().map(a=>a.finished))}')
            contrast=current.evaluate(r"""e=>{const c=getComputedStyle(e),lum=x=>{const v=x.match(/[\d.]+/g).slice(0,3).map(x=>{x=+x/255;return x<=.04045?x/12.92:((x+.055)/1.055)**2.4});return .2126*v[0]+.7152*v[1]+.0722*v[2]};const a=lum(c.color),b=lum(c.backgroundColor);return (Math.max(a,b)+.05)/(Math.min(a,b)+.05)}""")
            self.assertGreaterEqual(contrast,4.5)
        self.page.get_by_role('searchbox',name='搜索任务').fill('episode-00');expect(self.rows).to_have_count(10);expect(self.nav).to_contain_text('第 1 / 1 页')
        self.page.get_by_role('searchbox',name='搜索任务').fill('');expect(self.rows).to_have_count(20);expect(self.rows.first).to_contain_text('episode-000')
        self.nav.get_by_role('button',name='第 3 页',exact=True).click();self.page.get_by_role('group',name='任务筛选',exact=True).get_by_role('button',name=re.compile('^已完成')).click()
        expect(self.nav).to_contain_text('共 37 条');expect(self.nav).to_contain_text('第 1 / 2 页')
        for width in (1440,390,280):
            self.page.set_viewport_size({'width':width,'height':900});self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
    def test_poll_keeps_page_then_clamps_when_records_removed(self):
        self.nav.get_by_role('button',name='第 4 页',exact=True).click()
        self.h.jobs[60]['file_names']=['updated-result.srt'];expect(self.rows.first).to_contain_text('updated-result',timeout=10000);expect(self.nav).to_contain_text('第 4 / 4 页')
        self.h.jobs=self.h.jobs[:21];expect(self.nav).to_contain_text('第 2 / 2 页',timeout=10000);expect(self.rows).to_have_count(1)
        self.h.jobs=[];expect(self.rows).to_have_count(0,timeout=10000);expect(self.nav).to_have_count(0)
        self.h.jobs=[{'id':'f'*32,'kind':'transcriptions','project_id':None,'state':'completed','file_names':['only.srt']}];expect(self.rows).to_have_count(1,timeout=10000);expect(self.nav).to_contain_text('第 1 / 1 页')
    def test_twenty_exact_and_no_matches(self):
        self.h.jobs=self.h.jobs[:20];expect(self.nav).to_contain_text('共 20 条',timeout=10000);expect(self.nav.get_by_role('button',name='下一页')).to_be_disabled()
        self.page.get_by_role('searchbox',name='搜索任务').fill('not-found');expect(self.rows).to_have_count(0);expect(self.nav).to_have_count(0)

class SubtitleFunctionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):subtitles.TranslationStatusBrowserTests.setUpClass()
    @classmethod
    def tearDownClass(cls):subtitles.TranslationStatusBrowserTests.tearDownClass()
    def setUp(self):
        self.h=subtitles.TranslationStatusBrowserTests('test_saved_translation_survives_reload_without_any_remembered_task');self.h.setUp();self.addCleanup(self.h.tearDown);self.page=self.h.page;self.submitted=[];self.fail_source=False
        self.rows=[{'resource':'subtitles/original.srt','filename':'platform.srt','origin':'platform','kind':'subtitle','language':'en','url':'/fixture'},
                   {'resource':'subtitles/local.srt','filename':'local.srt','origin':'local','kind':'transcription','language':'zh','url':'/fixture'}]
        for i,created in enumerate((1792841694,1792841694,1792841754,None,None)):
            self.rows.append({'resource':f'subtitles/t{i}.srt','version_id':f'result-{i}','filename':f't{i}.srt','kind':'translation','origin':'translation','language':'en','source_origin':'platform','source_resource':'subtitles/original.srt','generated_at':created,'url':'/fixture'})
        self.h.base.fixture.context.route('**/projects/*/subtitles*',self.route)
        self.h.base.fixture.context.route('**/api/workspace/translations',self.translate)
        self.h.open();self.h.choose(0);self.card=self.page.get_by_role('region',name='当前视频字幕',exact=True)
    def route(self,route):
        key=parse_qs(urlsplit(route.request.url).query).get('subtitle_resource',[''])[0]
        if self.fail_source and key=='subtitles/local.srt':return route.fulfill(status=404,json={'detail':'Synthetic source unavailable'})
        selected=next((r for r in self.rows if r['resource']==key),self.rows[0])
        text='这是中文原字幕。' if selected['origin']=='local' else 'English original.' if selected['origin']=='platform' else 'Saved translation '+selected['resource']
        route.fulfill(json={'project_id':self.h.pid,'has_subtitles':True,'files':self.rows[:2],'versions':self.rows,'selected':selected,'text':text,'translations':[]})
    def translate(self,route):
        self.submitted.append(route.request.post_data_json);route.fulfill(status=202,json=self.h.translation_job())
    def ai(self):self.card.get_by_role('button',name='AI翻译字幕',exact=True).click();expect(self.card.get_by_role('combobox',name='翻译原字幕')).to_be_visible()
    def test_function_labels_acquisition_actions_and_no_implicit_work(self):
        expect(self.card.get_by_role('group',name='字幕功能')).to_contain_text('功能')
        expect(self.card.get_by_role('button',name='本地生成字幕',exact=True)).to_have_attribute('aria-pressed','true')
        expect(self.card.get_by_role('button',name='AI 中英互译',exact=True)).to_have_count(0)
        self.card.get_by_role('button',name='重新生成字幕',exact=True).click();expect(self.page.locator('#subtitle-acquire').get_by_role('button',name='确认生成字幕',exact=True)).to_be_visible()
        self.card.get_by_role('button',name='平台下载字幕',exact=True).click();expect(self.page.locator('#subtitle-acquire')).to_be_hidden()
        self.card.get_by_role('button',name='重新下载字幕',exact=True).click();expect(self.card.get_by_role('group',name='平台字幕获取确认')).to_be_visible();expect(self.page.get_by_role('group',name='获取方式')).to_have_count(0)
        self.ai();expect(self.page.locator('#subtitle-acquire')).to_be_hidden();self.assertEqual(self.submitted,[])
        self.card.get_by_role('button',name='AI 中英互译',exact=True).click();expect(self.card.get_by_role('button',name='开始 AI 翻译')).to_be_enabled();self.assertEqual(self.submitted,[])
        self.card.get_by_role('button',name='本地生成字幕',exact=True).click();expect(self.card.get_by_role('button',name='AI 中英互译')).to_have_count(0)
    def test_original_picker_changes_target_and_submits_exact_source(self):
        self.ai();picker=self.card.get_by_role('combobox',name='翻译原字幕');expect(picker.locator('option')).to_have_count(2)
        self.card.get_by_role('button',name='AI 中英互译').click();expect(self.card.get_by_role('combobox',name='翻译方向')).to_have_value('en')
        picker.select_option('subtitles/original.srt');expect(self.card.get_by_role('combobox',name='翻译方向')).to_have_value('zh')
        self.assertEqual(self.submitted,[]);self.card.get_by_role('button',name='开始 AI 翻译').click()
        expect(self.card.get_by_label('译文',exact=True)).to_have_value(self.h.translation_job()['text'])
        self.assertEqual(self.submitted[0]['resource'],'subtitles/original.srt');self.assertEqual(self.submitted[0]['target'],'zh')
        self.card.get_by_role('button',name='平台下载字幕',exact=True).click();expect(self.card.get_by_label('字幕原文',exact=True)).to_have_value('English original.')
    def test_same_day_second_and_unknown_dates_never_share_labels(self):
        self.ai();labels=self.card.get_by_role('combobox',name='字幕版本',exact=True).locator('option').all_text_contents()
        self.assertEqual(len(labels),len(set(labels)));self.assertTrue(all(re.search(r'\d{2}:\d{2}:\d{2}',label) and '版本' in label for label in labels[:3]));self.assertTrue(all('时间未记录' in label and '版本' in label for label in labels[3:]))
        self.card.get_by_role('combobox',name='字幕版本',exact=True).select_option('subtitles/t2.srt');expect(self.card.locator('.subtitle-provenance')).to_contain_text('生成于')
    def test_failed_original_read_cannot_submit_previous_body(self):
        self.card.get_by_role('button',name='平台下载字幕',exact=True).click();self.ai();self.card.get_by_role('button',name='AI 中英互译').click()
        self.fail_source=True;self.card.get_by_role('combobox',name='翻译原字幕').select_option('subtitles/local.srt')
        expect(self.card.get_by_role('alert')).to_contain_text('Synthetic source unavailable');expect(self.card.get_by_role('button',name='开始 AI 翻译')).to_have_count(0);self.assertEqual(self.submitted,[])

    def test_confirmed_action_order_and_result_metadata_ownership(self):
        for width in (1440,390):
            self.page.set_viewport_size({'width':width,'height':1100})
            for function,action in (('平台下载字幕','重新下载字幕'),('本地生成字幕','重新生成字幕')):
                self.card.get_by_role('button',name=function,exact=True).click()
                expect(self.card.locator('.subtitle-reader')).to_have_attribute('aria-busy','false')
                button=self.card.get_by_role('button',name=action,exact=True)
                expect(button).to_have_count(1);expect(self.card.locator('.subtitle-result-actions').get_by_role('button',name=action,exact=True)).to_be_visible();expect(self.card.locator('.subtitle-provenance')).to_have_count(0)
                self.assertLess(button.bounding_box()['y'],self.card.locator('.subtitle-reader').bounding_box()['y'])
                expect(self.card.locator('.subtitle-viewer > .subtitle-result-actions')).to_have_count(1)
            self.ai();info=self.card.locator('.subtitle-provenance');toggle=self.card.get_by_role('button',name='AI 中英互译',exact=True)
            expect(toggle).to_be_visible();expect(info).to_have_count(1)
            expect(self.card.get_by_role('button',name='重新翻译字幕',exact=True)).to_have_count(0)
            source=self.card.get_by_role('combobox',name='翻译原字幕');saved=self.card.get_by_role('combobox',name='字幕版本',exact=True)
            source.scroll_into_view_if_needed()
            self.assertLess(source.bounding_box()['y'],toggle.bounding_box()['y'])
            self.assertLess(toggle.bounding_box()['y'],saved.bounding_box()['y'])
            self.assertLess(toggle.bounding_box()['y']+toggle.bounding_box()['height'],info.bounding_box()['y'])
            self.assertLess(info.bounding_box()['y']+info.bounding_box()['height'],saved.bounding_box()['y'])
            expect(self.card.get_by_text('已保存译文',exact=True)).to_have_count(0)
            expect(self.card.locator('.translation-workspace')).to_have_css('border-bottom-width','0px')
            self.assertLess(info.bounding_box()['y']+info.bounding_box()['height'],self.card.locator('.subtitle-body-label').bounding_box()['y']+1)
            expect(self.card.locator('.translation-workspace .subtitle-provenance')).to_have_count(0)
            expect(self.card.locator('.subtitle-viewer > .subtitle-provenance')).to_have_count(1)
            body_label=self.card.locator('.subtitle-body-label').bounding_box();saved_box=saved.bounding_box()
            self.assertGreaterEqual(body_label['y']-saved_box['y']-saved_box['height'],11)
            expected=info.text_content();source.select_option('subtitles/original.srt');expect(toggle).to_be_visible();expect(info).to_have_text(expected)
            saved.select_option('subtitles/t2.srt');expect(self.card.get_by_label('译文',exact=True)).to_have_value('Saved translation subtitles/t2.srt')
            self.assertNotEqual(info.text_content(),expected)
            if toggle.get_attribute('aria-expanded')!='true':toggle.click()
            expect(self.card.get_by_role('button',name='开始 AI 翻译',exact=True)).to_be_enabled()
            self.assertLess(self.card.get_by_role('button',name='开始 AI 翻译',exact=True).bounding_box()['y'],saved.bounding_box()['y'])
            self.assertLess(info.bounding_box()['y'],saved.bounding_box()['y'])
            self.assertLess(info.bounding_box()['y'],self.card.locator('.subtitle-body-label').bounding_box()['y'])
            self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
        self.assertEqual(self.submitted,[])
    def test_no_saved_translation_does_not_invent_result_information(self):
        self.rows=self.rows[:2];self.h.open();self.h.choose(0);self.ai()
        expect(self.card.get_by_role('button',name='AI 中英互译',exact=True)).to_be_visible()
        expect(self.card.locator('.subtitle-provenance')).to_have_count(0)
        expect(self.card.get_by_text('暂无已保存译文，请选择上方原字幕后开始翻译。',exact=True)).to_be_visible()
        expect(self.card.get_by_role('button',name='重新翻译字幕',exact=True)).to_have_count(0)
        self.assertEqual(self.submitted,[])
