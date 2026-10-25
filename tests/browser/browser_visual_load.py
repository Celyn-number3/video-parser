"""Visual load disclosures: real bundle, intercepted fixture APIs, no real models/data."""
import unittest
from playwright.sync_api import expect
from tests.browser import browser_learning_feedback as learning
from tests.browser import browser_workspace_polish as folders


class ReadingAndDisclosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.Fixture = learning.fixture_type(); cls.Fixture.setUpClass()
    @classmethod
    def tearDownClass(cls): cls.Fixture.tearDownClass()
    def setUp(self):
        self.f = self.Fixture('test_settings_cross_tab_updates'); self.f.setUp(); self.page = self.f.page
    def tearDown(self): self.f.tearDown()
    def analyze(self):
        self.f.parse(); self.page.get_by_role('tab', name='AI 分析', exact=True).click()
        expect(self.page.locator('.analysis-markdown')).to_be_visible()
    def test_existing_result_config_keyboard_draft_and_evidence(self):
        self.f.records[0]['frames'] = [{'url':'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==','time':0,'label':'00:00'}]
        self.analyze()
        config=self.page.locator('#analysis-configuration')
        expect(config).not_to_be_visible()
        before=list(self.f.requests)
        button=self.page.get_by_role('button',name='生成新材料',exact=True)
        button.focus(); self.page.keyboard.press('Space'); expect(config).to_be_visible()
        self.page.locator('#prompt').fill('保留这份草稿')
        self.page.get_by_role('button',name='收起生成配置',exact=True).click(); expect(config).not_to_be_visible()
        button.click(); expect(self.page.locator('#prompt')).to_have_value('保留这份草稿')
        summary=self.page.locator('.analysis-evidence > summary')
        frame=self.page.locator('.analysis-evidence img'); expect(frame).to_be_visible()
        summary.focus(); self.page.keyboard.press('Enter'); expect(frame).not_to_be_visible()
        self.page.keyboard.press('Enter'); expect(frame).to_be_visible()
        self.page.locator('.analysis-evidence button').click(); expect(self.page.get_by_role('dialog',name='画面大图')).to_be_visible()
        self.page.keyboard.press('Escape'); expect(self.page.get_by_role('dialog',name='画面大图')).not_to_be_visible()
        self.assertEqual(self.f.requests,before)
    def test_active_analysis_keeps_progress_and_cancel_visible(self):
        job={'id':'b'*32,'kind':'analysis','state':'running','phase':'analyzing','message':'fixture analysis running','result':{}}
        submissions=[]
        def submit(route):
            submissions.append(route.request.post_data_json); route.fulfill(json=job)
        def cancel(route):
            job.update(state='cancelled',phase='cancelled',message='fixture analysis cancelled'); route.fulfill(json=job)
        self.page.route('**/analyze-task',submit)
        self.page.route('**/api/workspace/tasks/'+job['id'],lambda route:route.fulfill(json=job))
        self.page.route('**/api/workspace/tasks/analysis/'+job['id']+'/cancel',cancel)
        self.analyze(); self.page.get_by_role('button',name='生成新材料',exact=True).click()
        self.page.locator('.analysis-segment label').filter(has=self.page.get_by_role('radio',name='只用画面',exact=True)).click()
        expect(self.page.get_by_role('radio',name='只用画面',exact=True)).to_be_checked()
        self.page.get_by_role('button',name='开始分析',exact=True).click()
        expect(self.page.get_by_role('button',name='收起生成配置',exact=True)).to_be_disabled()
        expect(self.page.locator('#analysis-configuration')).to_be_visible()
        expect(self.page.locator('.analysis-status')).to_contain_text('fixture analysis running')
        self.page.get_by_role('button',name='取消分析',exact=True).click()
        expect(self.page.locator('#analysis-configuration .error-text')).to_contain_text('fixture analysis cancelled')
        self.assertEqual(len(submissions),1)

    def test_empty_results_leave_generation_controls_visible(self):
        self.f.records=[]; self.f.parse(); self.page.get_by_role('tab',name='AI 分析',exact=True).click()
        expect(self.page.get_by_role('button',name='开始分析',exact=True)).to_be_visible()
        expect(self.page.get_by_role('button',name='生成新材料',exact=True)).to_have_count(0)
    def test_context_error_stays_visible(self):
        self.page.route('**/analysis/context?*',lambda route:route.fulfill(status=503,json={'detail':'fixture: context unavailable'}))
        self.f.parse(); self.page.get_by_role('tab',name='AI 分析',exact=True).click()
        expect(self.page.get_by_role('button',name='重新载入材料',exact=True)).to_be_visible()
        expect(self.page.locator('#analysis-configuration')).to_be_visible()
    def test_filters_stay_applied_when_collapsed_and_reset_is_reachable(self):
        jobs=[{'id':str(i)*32,'kind':'analysis','state':'completed','phase':'completed','project_id':self.f.project()['id'],'part':1,
               'subjects':[{'part':1,'title':'合成课程'}],'details':{'engine':engine,'template':'summary','model':'fixture-model','source':'both'}} for i,engine in [(1,'codex'),(2,'claude')]]
        self.page.route('**/api/workspace/tasks',lambda route:route.fulfill(json={'jobs':jobs}))
        self.f.parse(); self.page.get_by_role('button',name='任务中心',exact=True).click()
        expect(self.page.locator('.task-list > li')).to_have_count(2)
        summary=self.page.locator('.task-filter-details > summary')
        expect(self.page.get_by_label('执行工具',exact=True)).not_to_be_visible()
        summary.focus(); self.page.keyboard.press('Enter')
        self.page.get_by_label('执行工具',exact=True).select_option('codex')
        expect(self.page.locator('.task-list > li')).to_have_count(1)
        summary.click(); expect(self.page.get_by_label('执行工具',exact=True)).not_to_be_visible()
        expect(summary).to_contain_text('1'); expect(self.page.get_by_label('已应用筛选')).to_contain_text('Codex')
        self.page.get_by_role('button',name='重置筛选',exact=True).click()
        expect(self.page.locator('.task-list > li')).to_have_count(2)
        expect(self.page.get_by_label('已应用筛选')).to_have_count(0)
        for theme in ('light','dark'):
            self.page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
            for width in (1440,1170,768,390):
                self.page.set_viewport_size({'width':width,'height':1000})
                self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                self.page.screenshot(path=str(self.f.output/f'filters-{theme}-{width}.png'),animations='disabled')
    def test_reading_sizes_and_mobile_overflow(self):
        self.f.parse(); self.page.get_by_role('button',name='学习视图',exact=True).click()
        md=self.page.locator('.learning-materials .analysis-markdown')
        expect(md).to_have_css('font-size','14px')
        expect(md.locator('h4').first).to_have_css('font-size','18px')
        for width in (1440,1170,768,390):
            self.page.set_viewport_size({'width':width,'height':1000})
            self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=innerWidth'))


class FolderAndSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): folders.WorkspacePolishTests.setUpClass()
    @classmethod
    def tearDownClass(cls): folders.WorkspacePolishTests.tearDownClass()
    def setUp(self):
        self.w=folders.WorkspacePolishTests('test_folder_manual_preview_is_required_and_edit_invalidates_confirmation')
        self.w.setUp(); self.f=self.w.f; self.page=self.w.page
    def tearDown(self): self.w.tearDown()
    def plan(self,state,**extra):
        self.f.folder={'id':self.f.folder_id,'scope':'project_folder','project_id':self.f.base.identifier(1),'state':state,'suggestion':'合成课程',**extra}
    def test_completed_folder_compacts_without_mutation_and_editor_can_reopen(self):
        self.plan('applied'); self.f.open()
        body=self.page.locator('#folder-naming-body'); expect(body).not_to_be_visible()
        expect(self.page.locator('.folder-current')).to_be_visible()
        expect(self.page.locator('.subtitle-naming-panel')).to_be_visible()
        self.page.get_by_role('button',name='编辑文件夹名称',exact=True).click(); expect(body).to_be_visible()
        expect(self.page.get_by_role('textbox',name='新文件夹名称',exact=True)).to_have_value('合成课程')
        self.page.get_by_role('button',name='收起文件夹编辑',exact=True).click(); expect(body).not_to_be_visible()
        self.assertEqual(self.f.folder_calls,[])
    def test_recovery_and_errors_never_compact(self):
        self.plan('recovery_required',recovery_status='not_moved',last_error='fixture: needs recovery'); self.f.open()
        expect(self.page.locator('#folder-naming-body')).to_be_visible()
        expect(self.page.get_by_role('button',name='核对并解除失败状态',exact=True)).to_be_disabled()
        expect(self.page.get_by_role('button',name='编辑文件夹名称',exact=True)).to_have_count(0)
        self.assertEqual(self.f.folder_calls,[])
    def test_applied_plan_opened_from_task_remains_expanded(self):
        self.plan('applied')
        self.f.folder_job={'id':self.f.folder_job_id,'project_id':self.f.base.identifier(1),'operation':'folder_apply','kind':'naming','state':'completed','message':'已改名','result':{'plan_id':self.f.folder_id}}
        self.f.open(); expect(self.page.locator('#folder-naming-body')).not_to_be_visible()
        self.page.evaluate("id=>window.dispatchEvent(new CustomEvent('video-parser:restore-task',{detail:{kind:'naming',id}}))",self.f.folder_job_id)
        expect(self.page.locator('#folder-naming-body')).to_be_visible()
        self.assertEqual(self.f.folder_calls,[])
    def test_current_episode_readable_enabled_and_repeat_selection_is_noop(self):
        self.f.base.open(); self.page.set_viewport_size({'width':1440,'height':1000})
        button=self.page.locator('.learning-episode-row.is-current .learning-episode-open')
        expect(button).to_be_enabled(); expect(button).to_have_attribute('aria-current','true')
        for theme,color in [('dark','rgb(250, 250, 250)'),('light','rgb(10, 10, 10)')]:
            self.page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
            expect(button).to_have_css('color',color)
            expect(button.locator('.learning-episode-title')).to_have_css('color',color)
            button.click(); expect(button).to_have_attribute('aria-current','true')
        self.assertEqual(self.f.calls,[])

if __name__=='__main__': unittest.main()
