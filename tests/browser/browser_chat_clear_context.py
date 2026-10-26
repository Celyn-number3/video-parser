"""Confirm/reset UI with mocked conversation endpoint; no real clears or model jobs."""
import copy,unittest
from playwright.sync_api import expect
from tests.browser import browser_markdown_math as math

class ChatClearContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):math.MarkdownMathBrowserTests.setUpClass()
    @classmethod
    def tearDownClass(cls):math.MarkdownMathBrowserTests.tearDownClass()
    def setUp(self):
        self.h=math.MarkdownMathBrowserTests('test_all_four_delimiters_and_multiline_matrix');self.h.setUp();self.addCleanup(self.h.tearDown);self.page=self.h.page
        self.first={'id':'f'*32,'title':'第一份对话','title_generated':True,'video_resource':self.h.f.resource,'context_after':None,'origin_record':None,'agent':{'engine':'api','model':'','effort':''},'messages':[{'id':'m1','question':'旧问题','answer':r'- **旧回答**：公式 \(Ax=b\) 保留。','position':0,'created_at':''}],'created_at':'','updated_at':''}
        self.second={**copy.deepcopy(self.first),'id':'e'*32,'title':'第二份对话','messages':[]};self.h.f.sessions=[self.first,self.second]
        self.calls=[];self.mode='success';self.held=None
        def clear(route):
            self.calls.append(route.request.post_data_json)
            if self.mode=='hold':self.held=route;return
            if self.mode=='error':return route.fulfill(status=409,json={'detail':'对话已有新消息，请重新载入并确认后再清空上下文。'})
            self.first['context_after']='m1';route.fulfill(json={'conversation':self.first})
        self.page.route('**/conversations/*/clear-context',clear)
        self.h.open(learning=True);self.page.get_by_role('tab',name='AI 对话',exact=True).click()
        self.button=self.page.get_by_role('button',name='清空上下文',exact=True);self.field=self.page.get_by_role('textbox',name='向 AI 提问',exact=True)
    def accept(self):
        self.page.once('dialog',lambda d:d.accept());self.button.click()
    def test_confirmation_preserves_history_draft_reload_and_geometry(self):
        self.field.fill('尚未发送的草稿');self.page.once('dialog',lambda d:d.dismiss());self.button.click();self.assertEqual(self.calls,[])
        self.accept();expect(self.page.get_by_text('上下文已清空',exact=True)).to_be_visible();expect(self.button).to_be_disabled();expect(self.field).to_have_value('尚未发送的草稿')
        self.assertEqual(self.calls,[{'resource':self.h.f.resource,'expected_last_message_id':'m1','confirm':True}]);expect(self.page.locator('.ai-chat-answer')).to_contain_text('旧回答');expect(self.page.locator('.ai-chat-answer .katex')).to_have_count(1)
        for theme in ('dark','light'):
            self.page.evaluate('(x)=>document.documentElement.dataset.theme=x',theme)
            for width in (1440,768,390,280):
                self.page.set_viewport_size({'width':width,'height':1000});self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=innerWidth'));expect(self.button).to_be_visible()
        self.page.reload();self.page.get_by_role('tab',name='AI 对话',exact=True).click()
        expect(self.page.get_by_text('上下文已清空',exact=True)).to_be_visible();expect(self.field).to_have_value('尚未发送的草稿')
        import os
        from pathlib import Path
        out=Path(os.environ['VIDEO_PARSER_TEST_OUTPUT']);out.mkdir(parents=True,exist_ok=True)
        self.page.locator('.study-sidebar').screenshot(path=str(out/'cleared-history-fixture-280.png'))
        self.page.set_viewport_size({'width':1440,'height':1000})
        self.page.locator('.study-sidebar').screenshot(path=str(out/'cleared-history-fixture-1440.png'))
    def test_failure_keeps_history_draft_and_reenables_button(self):
        self.mode='error';self.field.fill('草稿');self.accept();expect(self.page.locator('.ai-chat-failure')).to_contain_text('对话已有新消息');expect(self.button).to_be_enabled();expect(self.field).to_have_value('草稿')
        expect(self.page.get_by_text('上下文已清空',exact=True)).to_have_count(0);expect(self.page.locator('.ai-chat-answer')).to_contain_text('旧回答')
    def test_inflight_clear_blocks_submit_and_late_response_keeps_selected_session(self):
        self.mode='hold';self.field.fill('第一份草稿');self.accept();expect(self.button).to_be_disabled();expect(self.page.get_by_role('button',name='提问',exact=True)).to_be_disabled();self.assertEqual(len(self.calls),1)
        self.page.get_by_role('button',name='选择或新建对话',exact=True).click();self.page.locator('.conversation-list button').filter(has_text='第二份对话').click()
        self.first['context_after']='m1';self.held.fulfill(json={'conversation':self.first});expect(self.field).to_be_enabled();expect(self.button).to_be_disabled();expect(self.page.locator('.ai-chat-answer')).to_have_count(0)
        self.field.fill('第二份草稿');self.page.get_by_role('button',name='选择或新建对话',exact=True).click();self.page.locator('.conversation-list button').filter(has_text='第一份对话').click()
        expect(self.field).to_have_value('第一份草稿');expect(self.page.get_by_text('上下文已清空',exact=True)).to_be_visible()
    def test_empty_session_disables_clear_and_new_reply_reenables_it(self):
        self.page.get_by_role('button',name='选择或新建对话',exact=True).click();self.page.locator('.conversation-list button').filter(has_text='第二份对话').click();expect(self.button).to_be_disabled();self.assertEqual(self.calls,[])
        self.first['context_after']='m1';self.first['messages'].append({'id':'m2','question':'新问题','answer':'新回答','position':0,'created_at':''})
        self.h.open(learning=True);self.page.get_by_role('tab',name='AI 对话',exact=True).click();self.page.get_by_role('button',name='选择或新建对话',exact=True).click();self.page.locator('.conversation-list button').filter(has_text='第一份对话').click()
        expect(self.button).to_be_enabled();expect(self.page.get_by_text('上下文已清空',exact=True)).to_be_visible();expect(self.page.locator('.ai-chat-answer')).to_have_count(2)
