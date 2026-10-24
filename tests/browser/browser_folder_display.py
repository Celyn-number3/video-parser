"""Project display names follow confirmed folders, never overwrite source or episode titles."""
import unittest
from playwright.sync_api import expect
from tests.browser import browser_workspace_polish as harness
from tests.browser.project_picker import select_project


class FolderDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): harness.WorkspacePolishTests.setUpClass()
    @classmethod
    def tearDownClass(cls): harness.WorkspacePolishTests.tearDownClass()
    def setUp(self):
        harness.WorkspacePolishTests.setUp(self)
        self.single = False
        original = self.f.base.project
        def project(part):
            p = original(part)
            if part in (1,2):
                p['title'] = '原始平台课程标题'
                p['episode_title'] = None if self.single else f'第{part}集 内容名'
                p['is_single'] = self.single
                p['display_title'] = self.f.folder['suggestion'] if self.f.folder and self.f.folder['state']=='applied' else p['title']
            return p
        self.f.base.project = project
        self.page.route('**/api/workspace/projects/'+self.f.base.identifier(2)+'/naming',
                        lambda route: route.fulfill(json={'project_id':self.f.base.identifier(2),'title':'原始平台课程标题','entries':self.f.entries(),'history':[]}))
        self.page.route('**/api/workspace/projects', lambda route: route.fulfill(json={'projects':[
            {**project(n),'archived':True} for n in (1,2,3)]}))
    def tearDown(self): harness.WorkspacePolishTests.tearDown(self)
    def test_confirmed_folder_updates_all_contexts_reload_and_other_episode_without_losing_draft(self):
        self.f.open(); heading=self.page.locator('.video-context-heading')
        self.page.get_by_role('tab',name='AI 分析',exact=True).click();self.page.locator('#prompt').fill('保留未提交的分析要求')
        self.page.get_by_role('tab',name='文件重命名',exact=True).click()
        card=self.page.locator('.project-folder-naming');card.get_by_role('textbox',name='新文件夹名称',exact=True).fill('简短新项目名')
        card.get_by_role('button',name='预览文件夹改名',exact=True).click()
        expect(heading).to_contain_text('原始平台课程标题')
        card.get_by_role('button',name='确认修改项目文件夹',exact=True).click()
        expect(heading.locator('span')).to_have_text('P1 · 简短新项目名')
        expect(heading.locator('strong')).to_have_text('第1集 内容名')
        expect(self.page.get_by_role('tab',name='文件重命名',exact=True)).to_have_attribute('aria-selected','true')
        self.page.get_by_role('tab',name='AI 分析',exact=True).click()
        expect(heading.locator('span')).to_have_text('P1 · 简短新项目名')
        expect(self.page.locator('#prompt')).to_have_value('保留未提交的分析要求')
        self.page.get_by_role('tab',name='视频',exact=True).click()
        expect(self.page.locator('.info-title')).to_have_text('第1集 内容名')
        expect(self.page.locator('.inspector-identity > .muted')).to_have_text('简短新项目名')
        self.page.get_by_role('button',name='重命名',exact=True).click()
        field=self.page.get_by_role('textbox',name='项目标题',exact=True)
        expect(field).to_have_value('简短新项目名');field.press('Escape')
        self.page.get_by_role('button',name='学习视图',exact=True).click()
        expect(heading.locator('span')).to_have_text('P1 · 简短新项目名')
        picker=self.page.get_by_role('combobox',name='学习项目',exact=True)
        picker.click();popup=self.page.locator('.project-picker-popup')
        expect(popup.get_by_role('group',name='简短新项目名',exact=True)).to_be_visible()
        self.page.get_by_role('searchbox',name='筛选视频列表',exact=True).fill('原始平台课程标题')
        expect(popup.get_by_role('option')).to_have_count(2)
        self.page.get_by_role('searchbox',name='筛选视频列表',exact=True).press('Escape')
        select_project(picker,self.f.base.identifier(2))
        expect(heading.locator('span')).to_have_text('P2 · 简短新项目名')
        expect(heading.locator('strong')).to_have_text('第2集 内容名')
        self.page.reload();expect(heading.locator('span')).to_have_text('P2 · 简短新项目名')
        self.assertEqual(self.f.base.project(1)['title'],'原始平台课程标题')
        self.assertEqual([p.rsplit('/',1)[1] for p,_ in self.f.folder_calls],['preview','apply'])
        self.page.screenshot(path=str(self.f.base.fixture.output/'folder-display-learning.png'))

    def test_single_without_episode_title_uses_folder_name_as_heading_after_reload(self):
        self.single=True
        self.f.folder={'id':self.f.folder_id,'scope':'project_folder','project_id':self.f.base.identifier(1),
            'state':'applied','suggestion':'单视频新文件夹名'}
        self.f.open()
        expect(self.page.locator('.video-context-heading strong')).to_have_text('单视频新文件夹名')
        self.page.get_by_role('tab',name='视频',exact=True).click()
        expect(self.page.locator('.info-title')).to_have_text('单视频新文件夹名')
        expect(self.page.locator('.inspector-identity > .muted')).to_have_count(0)
        self.page.reload();expect(self.page.locator('.info-title')).to_have_text('单视频新文件夹名')
        self.assertEqual(self.f.folder_calls,[])
