"""Eight-feedback regression, fully intercepted APIs and synthetic media/model results."""
import unittest
from urllib.parse import urlsplit
from playwright.sync_api import expect
from tests.browser import browser_subtitle_naming as naming
from tests.browser import browser_translation_status as translation


def fixture_type():
    class Fixture(naming.SubtitleNamingBrowserTests):
        folder_id = '8' * 32
        folder_job_id = '9' * 32
        def setUp(self):
            self.folder = None; self.folder_calls = []; self.folder_job = None
            super().setUp()
        def route(self, route):
            req = route.request; url = urlsplit(req.url)
            if url.hostname == '127.0.0.1' and url.port == self.base.fixture.server.server_port:
                path = url.path.removeprefix('/api/workspace')
                if path == '/ai/agents':
                    return route.fulfill(json={'engines':[{'id':'codex','name':'Codex','installed':True,'enabled':True,'discovered':True,
                        'models':[{'id':m,'label':m,'efforts':[]} for m in ('deepseek-v4.1-flash','gpt-6-luna')],'commands':[]}]})
                if path.endswith('/conversations') or path.endswith('/conversations/migrate'):
                    return route.fulfill(json={'conversations':[{'id':'7'*32,'title':'历史对话','video_resource':'video/fixture.wav',
                        'agent':{'engine':'codex','model':'gpt-6-luna','effort':''},'messages':[],'created_at':'','updated_at':''}]})
                if path.endswith('/study/progress') and req.method == 'POST':
                    return route.fulfill(json={**req.post_data_json,'revision':req.post_data_json['expected_revision']+1})
                if path.endswith('/subtitle-cues'):
                    return route.fulfill(json={'resource':'subtitles/fixture.srt','sources':[{'resource':'subtitles/fixture.srt','label':'平台字幕'}],
                        'cues':[{'time':i,'text':f'字幕第{i}行：合成课程内容。'} for i in range(100)]})
                if path.endswith('/folder-naming'):
                    return route.fulfill(json={'location':'bilibili/旧课程__fixture','title':'旧课程','projects':2,'latest':self.folder})
                if '/folder-naming/' in path:
                    body=req.post_data_json; self.folder_calls.append((path,body))
                    title=body.get('title','简明线性代数')
                    self.folder={'id':self.folder_id,'scope':'project_folder','project_id':self.base.identifier(1),'state':'proposed','suggestion':title}
                    if path.endswith('/preview'):
                        self.folder.update(state='validated',preview_token='6'*32,folder_preview={'old':'bilibili/旧课程__fixture','new':f'bilibili/{title}__fixture','projects':2,'files':10})
                        return route.fulfill(json=self.folder)
                    self.folder_job={'id':self.folder_job_id,'project_id':self.base.identifier(1),'operation':'folder_plan','kind':'naming','state':'completed','message':'建议已生成','result':{'plan_id':self.folder_id}}
                    return route.fulfill(json=self.folder_job)
                if path == '/naming/tasks/'+self.folder_job_id:
                    return route.fulfill(json=self.folder_job)
                if path == '/naming/plans/'+self.folder_id:
                    return route.fulfill(json=self.folder)
                if path == '/naming/plans/'+self.folder_id+'/restore':
                    self.folder_calls.append((path,req.post_data_json)); self.folder.update(state='rolled_back',last_error='',recovery_outcome='not_moved')
                    self.folder_job={'id':self.folder_job_id,'project_id':self.base.identifier(1),'operation':'folder_restore','kind':'naming','state':'completed','message':'已核对','result':{'plan_id':self.folder_id}}
                    return route.fulfill(json=self.folder_job)
                if path == '/naming/plans/'+self.folder_id+'/apply':
                    self.folder_calls.append((path,req.post_data_json)); self.folder['state']='applied'
                    self.folder_job={'id':self.folder_job_id,'project_id':self.base.identifier(1),'operation':'folder_apply','kind':'naming','state':'completed','message':'已改名','result':{'plan_id':self.folder_id}}
                    return route.fulfill(json=self.folder_job)
            return super().route(route)
    return Fixture


class WorkspacePolishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): naming.SubtitleNamingBrowserTests.setUpClass()
    @classmethod
    def tearDownClass(cls): naming.SubtitleNamingBrowserTests.tearDownClass()
    def setUp(self):
        self.f=fixture_type()('test_single_page_controls_remain_before_and_after_generation'); self.f.setUp(); self.page=self.f.page
        self.page.add_init_script("localStorage.setItem('video-parser:agent-preferences',JSON.stringify({enabled:['api|','codex|deepseek-v4.1-flash'],target:{engine:'codex',model:'deepseek-v4.1-flash',effort:''}}))")
    def tearDown(self): self.f.tearDown()
    def shot(self, name):
        self.page.screenshot(path=str(self.f.base.fixture.output/(name+'.png')),full_page=True,animations='disabled')
    def test_model_default_is_not_replaced_by_hidden_conversation_model_after_reload(self):
        self.f.open(); self.page.get_by_role('tab',name='AI 分析',exact=True).click()
        selector=self.page.locator('.analysis-form').get_by_role('combobox',name='引擎与模型',exact=True)
        for _ in range(2):
            expect(selector).to_have_value('codex|deepseek-v4.1-flash')
            expect(selector.locator('option[value="codex|gpt-6-luna"]')).to_have_count(0)
            selector.select_option('api|'); expect(selector).to_have_value('api|')
            self.page.reload(); self.page.get_by_role('tab',name='AI 分析',exact=True).click()
        expect(selector).to_have_value('codex|deepseek-v4.1-flash')
        self.assertEqual(self.f.folder_calls,[])
        self.shot('analysis-default-model')
    def test_workspace_picker_shares_tab_row_and_responsive_no_overflow(self):
        self.f.open(); self.page.set_viewport_size({'width':1440,'height':1000})
        toolbar=self.page.locator('.workspace-toolbar')
        a=toolbar.locator('.tabs').bounding_box(); b=toolbar.locator('.learning-project-picker').bounding_box()
        self.assertLess(abs(a['y']+a['height']/2-b['y']-b['height']/2),2)
        self.assertLessEqual(a['x']+a['width'],b['x'])
        for theme in ('dark','light'):
            self.page.evaluate('(v)=>document.documentElement.dataset.theme=v',theme)
            for width in (1440,390,280):
                self.page.set_viewport_size({'width':width,'height':1000})
                self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                expect(toolbar.get_by_role('combobox',name='已归档视频',exact=True)).to_be_visible()
                self.shot(f'folder-ui-{theme}-{width}')
    def test_unmoved_folder_recovery_is_explicit_and_unlocks_without_generation(self):
        self.f.folder={'id':self.f.folder_id,'scope':'project_folder','project_id':self.f.base.identifier(1),'state':'recovery_required',
            'suggestion':'保留的建议','recovery_status':'not_moved','last_error':'旧失败提示'}
        self.f.open(); card=self.page.locator('.project-folder-naming')
        field=card.get_by_role('textbox',name='新文件夹名称',exact=True)
        expect(field).to_be_disabled(); expect(card).to_contain_text('目标文件夹未生成')
        restore=card.get_by_role('button',name='核对并解除失败状态',exact=True)
        expect(restore).to_be_disabled(); self.assertEqual(self.f.folder_calls,[])
        card.get_by_role('checkbox',name='确认核对文件并解除失败状态',exact=True).check()
        restore.click(); expect(field).to_be_enabled(); expect(field).to_have_value('保留的建议')
        expect(card).to_contain_text('已解除失败状态，可重新预览')
        expect(card.get_by_role('alert')).to_have_count(0)
        self.assertEqual([p.rsplit('/',1)[1] for p,_ in self.f.folder_calls],['restore'])
        self.shot('folder-recovered')
        self.page.reload(); self.page.get_by_role('tab',name='文件重命名',exact=True).click()
        expect(field).to_be_enabled(); expect(card.get_by_role('alert')).to_have_count(0)

    def test_folder_manual_preview_is_required_and_edit_invalidates_confirmation(self):
        self.f.open(); card=self.page.locator('.project-folder-naming')
        field=card.get_by_role('textbox',name='新文件夹名称',exact=True); field.fill('线性代数')
        expect(card.get_by_role('button',name='确认修改项目文件夹',exact=True)).to_have_count(0)
        card.get_by_role('button',name='预览文件夹改名',exact=True).click()
        confirm=card.get_by_role('button',name='确认修改项目文件夹',exact=True); expect(confirm).to_be_enabled()
        field.fill('简明课程'); expect(confirm).to_be_disabled()
        card.get_by_role('button',name='预览文件夹改名',exact=True).click(); expect(confirm).to_be_enabled()
        self.assertFalse(any(path.endswith('/apply') for path,_ in self.f.folder_calls))
        confirm.click(); expect(card).to_contain_text('项目文件夹已重命名。')
        self.assertEqual(sum(path.endswith('/apply') for path,_ in self.f.folder_calls),1)
        self.assertFalse(any(path.endswith('/plan') for path,_ in self.f.folder_calls))
    def test_folder_ai_is_explicit_and_saved_proposal_restores_without_another_model_call(self):
        self.f.open(); card=self.page.locator('.project-folder-naming')
        self.assertEqual(self.f.folder_calls,[])
        card.get_by_role('button',name='AI 生成文件夹名',exact=True).click()
        expect(card.get_by_role('textbox',name='新文件夹名称',exact=True)).to_have_value('简明线性代数')
        self.assertEqual(self.f.folder_calls[0][1],{'consent':True,'agent':{'engine':'codex','model':'deepseek-v4.1-flash','effort':''}})
        self.page.reload(); self.page.get_by_role('tab',name='文件重命名',exact=True).click()
        expect(card.get_by_role('textbox',name='新文件夹名称',exact=True)).to_have_value('简明线性代数')
        self.assertEqual(len(self.f.folder_calls),1)
        self.page.evaluate("id=>window.dispatchEvent(new CustomEvent('video-parser:restore-task',{detail:{kind:'naming',id}}))",self.f.folder_job_id)
        expect(card.get_by_role('textbox',name='新文件夹名称',exact=True)).to_have_value('简明线性代数')
    def test_material_font_and_subtitle_available_height_follow_and_seek(self):
        self.f.base.open(); self.page.set_viewport_size({'width':1440,'height':1100})
        expect(self.page.locator('.learning-materials .analysis-markdown')).to_have_css('font-size','14px')
        self.page.get_by_role('tab',name='字幕',exact=True).click()
        panel=self.page.locator('.subtitle-scroll-panel'); expect(panel.locator('.subtitle-scroll-list > button')).to_have_count(100)
        expect(panel.get_by_role('button',name='刷新字幕',exact=True)).to_have_count(0)
        select=panel.get_by_role('combobox',name='字幕版本'); follow=panel.get_by_role('button',name='自动跟随：开启')
        a,b=select.bounding_box(),follow.bounding_box(); self.assertAlmostEqual(a['y'],b['y'],delta=1)
        box=panel.bounding_box(); rows=panel.locator('.subtitle-scroll-list').bounding_box()
        self.assertAlmostEqual(rows['y']+rows['height'],box['y']+box['height']-12,delta=2)
        panel.locator('.subtitle-scroll-list > button').nth(5).click()
        self.page.wait_for_function("document.querySelector('video').currentTime >= 4.9")
        self.page.locator('video').evaluate('(e)=>e.pause()')
        follow.click(); expect(follow).to_have_count(0); panel.get_by_role('button',name='恢复自动跟随').click()
        for width in (1440,390):
            self.page.set_viewport_size({'width':width,'height':1100}); self.shot(f'subtitle-fill-{width}')


class SavedTranslationPickerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): translation.TranslationStatusBrowserTests.setUpClass()
    @classmethod
    def tearDownClass(cls): translation.TranslationStatusBrowserTests.tearDownClass()
    def test_single_saved_translation_and_restored_job_both_have_picker(self):
        f=translation.TranslationStatusBrowserTests('test_saved_translation_survives_reload_without_any_remembered_task'); f.setUp()
        try:
            f.completed=True; f.open(); f.choose(0)
            picker=f.page.get_by_role('combobox',name='已保存译文',exact=True)
            expect(picker).to_be_visible(); expect(picker.locator('option')).to_have_count(1)
            f.page.reload(); f.page.get_by_role('button',name=__import__('re').compile(r'^已归档视频')).click(); f.choose(0)
            expect(picker).to_be_visible()
            self.assertFalse(any(path=='/translations' for _,path,_ in f.calls))
        finally: f.tearDown()


if __name__=='__main__': unittest.main()
