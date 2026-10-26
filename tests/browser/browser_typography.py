"""Semantic UI typography and reflow; fixture APIs only, no real generation."""
import unittest
from playwright.sync_api import expect
from tests.browser import browser_markdown_math as math

class TypographyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):math.MarkdownMathBrowserTests.setUpClass()
    @classmethod
    def tearDownClass(cls):math.MarkdownMathBrowserTests.tearDownClass()
    def setUp(self):
        self.h=math.MarkdownMathBrowserTests('test_all_four_delimiters_and_multiline_matrix');self.h.setUp();self.addCleanup(self.h.tearDown);self.page=self.h.page
        self.page.route('**/api/workspace/projects/*/folder-naming',lambda r:r.fulfill(json={'location':'fixture/course','title':'合成课程','projects':1,'latest':None}))
        self.page.route('**/api/workspace/projects/*/naming',lambda r:r.fulfill(json={'title':'合成课程','entries':[],'subtitle_count':0,'ready_count':0,'max_selected':50,'history':[]}))
    def geometry(self):
        self.page.evaluate('()=>document.fonts.ready')
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=document.documentElement.clientWidth'), 'page overflow')
        title=self.page.locator('.topbar-title');expect(title).to_have_css('font-weight','600')
        expect(title).to_have_css('font-size','22px' if self.page.viewport_size['width']<=640 else '24px')
        self.assertTrue(title.evaluate('(e)=>e.scrollWidth<=e.clientWidth'),'title clipped')
        tiny=self.page.evaluate('''()=>[...document.querySelectorAll('.modern-app *')].filter(e=>e.checkVisibility() && !e.closest('.markdown,.math-text,svg,video,.sr-only') && [...e.childNodes].some(n=>n.nodeType===3&&n.textContent.trim()) && parseFloat(getComputedStyle(e).fontSize)<12).map(e=>({tag:e.tagName,cls:e.className,text:e.textContent.slice(0,45),size:getComputedStyle(e).fontSize}))''')
        self.assertEqual(tiny,[],'UI text below 12px')
        # Snapshot in one browser task: responsive transitions can change the visible
        # selector between .all() and successive nth() lookups. Keep every size check.
        controls=self.page.locator('button:visible, select:visible, textarea:visible').evaluate_all(
            '(els)=>els.filter(e=>!e.closest(".markdown") && (e.textContent.trim() || e.tagName!=="BUTTON")).map(e=>({size:parseFloat(getComputedStyle(e).fontSize),html:e.outerHTML.slice(0,250)}))')
        self.assertTrue(controls,'No visible controls were inspected')
        for control in controls:self.assertGreaterEqual(control['size'],13,control['html'])
    def responsive(self):
        for theme in ('dark','light'):
            self.page.evaluate('(x)=>document.documentElement.dataset.theme=x',theme)
            for width in (1440,1024,760,390,320,280):
                self.page.set_viewport_size({'width':width,'height':1000});self.geometry()
        self.page.set_viewport_size({'width':1440,'height':1000})
    def test_workspace_all_tabs(self):
        self.h.open()
        for tab in ('视频','字幕与转写','AI 分析','文件重命名'):
            self.page.get_by_role('tab',name=tab,exact=True).click();self.responsive()
        self.page.get_by_role('tab',name='AI 分析',exact=True).click()
        expect(self.page.locator('.analysis-markdown')).to_have_css('font-size','16px')
        expect(self.page.locator('.analysis-markdown')).to_have_css('max-width','none')
        for e in self.page.locator('.analysis-record-actions button').all():expect(e).to_have_css('font-size','13px')
    def test_tasks_accounts_and_settings_sections(self):
        for query in ('tasks','accounts','settings','settings&settings_section=ai','settings&settings_section=maintenance'):
            self.page.goto(self.h.f.url+'?page='+query);expect(self.page.locator('.topbar-title')).to_be_visible();self.page.wait_for_timeout(150);self.responsive()
            if query=='tasks':
                for e in self.page.locator('.task-list strong:visible').all():expect(e).to_have_css('font-size','14px')
            if query=='settings':
                expect(self.page.locator('#settings-group-general')).to_have_css('font-size','18px')
                expect(self.page.locator('#settings-language')).to_have_css('font-size','15px')
    def test_learning_materials_and_chat_reading_roles(self):
        self.h.f.sessions=[{'id':'f'*32,'title':'排版测试对话','video_resource':self.h.f.resource,'origin_record':None,'agent':{'engine':'api','model':'','effort':''},'messages':[{'id':'one','question':'如何理解？','answer':'这是一段已有回答，保持十五像素的正常字重。','position':0,'created_at':''}],'created_at':'','updated_at':''}]
        self.h.open(learning=True);self.responsive()
        md=self.page.locator('.learning-materials .analysis-markdown');expect(md).to_have_css('font-size','14px');expect(md).to_have_css('max-width','none')
        self.page.get_by_role('tab',name='AI 对话',exact=True).click()
        expect(self.page.locator('.ai-chat-log .markdown').first).to_have_css('font-size','15px');self.responsive()
        self.page.get_by_role('tab',name='个人笔记',exact=True).click();self.responsive()
    def test_effective_half_width_reflow_and_keyboard_focus(self):
        self.h.open();self.page.set_viewport_size({'width':720,'height':500});self.geometry()
        self.page.get_by_role('tab',name='AI 分析',exact=True).focus();self.page.keyboard.press('ArrowLeft')
        focused=self.page.locator(':focus');expect(focused).to_be_visible()
        self.assertTrue(focused.evaluate('(e)=>e.getBoundingClientRect().right<=innerWidth'))
        # Effective 200%-zoom desktop width; browser zoom itself is not changed.
        self.page.get_by_role('tab',name='AI 分析',exact=True).click();expect(self.page.locator('.analysis-markdown .katex').first).to_be_visible()
