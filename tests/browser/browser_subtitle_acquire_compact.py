"""All submit/login endpoints are mocked; never launch real jobs."""
import re, unittest
from urllib.parse import urlsplit
from playwright.sync_api import expect
from tests.browser import browser_workspace_flow as flow

class CompactAcquireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): flow.SubtitleFunctionTests.setUpClass()
    @classmethod
    def tearDownClass(cls): flow.SubtitleFunctionTests.tearDownClass()
    def setUp(self):
        self.h=flow.SubtitleFunctionTests('test_function_labels_acquisition_actions_and_no_implicit_work'); self.h.setUp(); self.addCleanup(self.h.tearDown)
        self.page=self.h.page;self.card=self.h.card;self.calls=[];self.auth=True;self.login_state='waiting';self.local_running=None
        self.page.context.route('**/api/workspace/subtitles**',self.route)
        self.page.context.route('**/api/workspace/bili-login**',self.route)
        self.page.context.route('**/api/workspace/transcriptions**',self.route)
    def route(self,route):
        req=route.request;p=urlsplit(req.url).path.removeprefix('/api/workspace');body=req.post_data_json if req.method=='POST' else None
        if p=='/transcriptions/sources':return self.h.h.route(route)
        self.calls.append((req.method,p,body))
        if p=='/subtitles/inventory':return route.fulfill(json={'total':3,'archived':[1,3], 'episodes':[{'part':i,'title':f'P{i}','subtitles':i!=2} for i in (1,2,3)]})
        if p=='/bili-login/status':return route.fulfill(json={'authenticated':self.auth})
        if p=='/bili-login':return route.fulfill(json={'id':'qr-test','image':'data:image/png;base64,','state':'waiting','expires_in':180})
        if p.endswith('/poll'):return route.fulfill(json={'state':self.login_state})
        if p.endswith('/cancel'):return route.fulfill(json={})
        if p.startswith('/subtitles/') or p=='/subtitles':return route.fulfill(json={'id':'a'*32,'state':'failed' if req.method=='GET' else 'completed','title':'fixture','message':'OLD HISTORICAL FAILURE DO NOT SHOW','results':[],'skipped':[1,3],'downloaded':1,'existing':0,'failed':0})
        if p.startswith('/transcriptions/') and self.local_running:return route.fulfill(json=self.local_running)
        if p=='/transcriptions':
            if self.local_running is not None:
                self.local_running=self.h.h.translation_job();self.local_running.update(operation='transcription',state='running',text='',files=[],source_project_id=body['project_id'],source_resource=body['resource'])
                return route.fulfill(status=202,json=self.local_running)
            return route.fulfill(status=503,json={'detail':'本次模拟服务暂不可用'})
        raise AssertionError((req.method,p))
    def submissions(self):return [(p,b) for m,p,b in self.calls if m=='POST' and p in ('/subtitles','/transcriptions')]
    def platform(self):
        self.card.get_by_role('button',name='平台下载字幕',exact=True).click();self.card.get_by_role('button',name='重新下载字幕',exact=True).click()
        return self.card.get_by_role('group',name='平台字幕获取确认',exact=True)
    def batch(self,panel):
        panel.get_by_role('button',name='选择批量范围（可选）',exact=True).click();panel.get_by_label('下载范围',exact=True).select_option('custom');panel.get_by_label('指定集数',exact=True).fill('1-3')
    def test_compact_default_guards_history_and_requires_explicit_batch_confirmation(self):
        self.page.evaluate("localStorage.setItem('video-parser:task:subtitles','"+'b'*32+"')")
        panel=self.platform();expect(panel).to_be_visible();expect(panel.get_by_role('button',name='确认下载')).to_be_disabled()
        expect(panel.get_by_label('下载范围',exact=True)).to_have_count(0);expect(self.page.get_by_role('group',name='获取方式')).to_have_count(0)
        expect(panel).not_to_contain_text('OLD HISTORICAL');expect(panel.get_by_role('button',name=re.compile('重新读取|刷新'))).to_have_count(0)
        self.batch(panel);expect(panel.get_by_role('button',name='确认下载')).to_be_enabled();self.assertEqual(self.submissions(),[])
        panel.get_by_label('指定集数',exact=True).fill('3-1');expect(panel.get_by_role('button',name='确认下载')).to_be_disabled()
        panel.get_by_label('指定集数',exact=True).fill('1-3');panel.get_by_role('button',name='确认下载').click()
        expect(panel.get_by_role('status')).to_have_text('本次字幕获取已完成。');self.assertEqual(len(self.submissions()),1)
        payload=self.submissions()[0][1];self.assertEqual(payload['scope'],'custom');self.assertEqual(payload['episodes'],'1-3');self.assertNotIn('force',payload)
        expect(panel).not_to_contain_text('OLD HISTORICAL');expect(panel.get_by_role('link',name='查看任务中心')).to_have_attribute('href','?page=tasks')
    def test_close_scope_and_function_changes_never_submit(self):
        panel=self.platform();self.batch(panel);panel.get_by_role('button',name='收起批量范围').click()
        expect(panel.get_by_role('button',name='确认下载')).to_be_disabled();self.batch(panel)
        panel.get_by_role('button',name='取消',exact=True).click();expect(panel).to_have_count(0)
        self.card.get_by_role('button',name='重新下载字幕',exact=True).click();panel=self.card.locator('.compact-acquire')
        expect(panel.get_by_label('下载范围')).to_have_count(0);expect(panel.get_by_role('button',name='确认下载')).to_be_disabled()
        self.card.get_by_role('button',name='AI翻译字幕',exact=True).click();expect(self.card.locator('.compact-acquire')).to_have_count(0);self.assertEqual(self.submissions(),[])
    def test_login_cancel_then_switch_does_not_submit_stale_source(self):
        self.auth=False;panel=self.platform();self.batch(panel);panel.get_by_role('button',name='确认下载').click()
        dialog=self.page.get_by_role('dialog',name='B站扫码登录');expect(dialog).to_be_visible();self.assertEqual(self.submissions(),[])
        dialog.get_by_role('button',name='取消',exact=True).click();expect(dialog).to_have_count(0)
        self.h.h.choose(1);expect(self.card.locator('.compact-acquire')).to_have_count(0)
        self.login_state='authenticated';self.auth=True;self.page.wait_for_timeout(2400);self.assertEqual(self.submissions(),[])
    def test_local_controls_only_submit_after_confirmation_and_hide_old_result(self):
        self.card.get_by_role('button',name='重新生成字幕',exact=True).click();panel=self.card.get_by_role('group',name='本地字幕生成确认')
        expect(panel.get_by_label('字幕语言')).to_have_value('auto');expect(panel.get_by_label('保存到',exact=True)).to_have_value('source')
        panel.get_by_label('字幕语言').select_option('en');self.assertEqual(self.submissions(),[])
        panel.get_by_role('button',name='确认生成字幕').click();expect(panel.get_by_role('alert')).to_have_text('本次模拟服务暂不可用')
        self.assertEqual(len(self.submissions()),1);payload=self.submissions()[0][1];self.assertEqual(payload['language'],'en');self.assertEqual(payload['project_id'],self.h.h.pid)
        panel.get_by_role('button',name='关闭',exact=True).click();self.card.get_by_role('button',name='重新生成字幕',exact=True).click()
        expect(panel.get_by_role('alert')).to_have_count(0);expect(panel.get_by_label('字幕语言')).to_have_value('auto');self.assertEqual(len(self.submissions()),1)
    def test_compact_geometry_both_themes_and_mobile(self):
        for theme in ('dark','light'):
            self.page.evaluate('(x)=>document.documentElement.dataset.theme=x',theme)
            for width in (1440,390,280):
                self.page.set_viewport_size({'width':width,'height':1000});panel=self.platform()
                for batch in (False,True):
                    if batch:self.batch(panel)
                    self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                    self.assertLess(panel.bounding_box()['y'],self.card.locator('.subtitle-reader').bounding_box()['y'])
                panel.get_by_role('button',name='取消',exact=True).click()
                self.card.get_by_role('button',name='本地生成字幕',exact=True).click();self.card.get_by_role('button',name='重新生成字幕',exact=True).click()
                self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=innerWidth'));self.card.locator('.compact-acquire').get_by_role('button',name='取消',exact=True).click()
        self.assertEqual(self.submissions(),[])

    def test_all_scope_needs_explicit_confirmation_and_login_preserves_captured_scope(self):
        self.auth=False;panel=self.platform();self.batch(panel);panel.get_by_label('下载范围',exact=True).select_option('all')
        self.assertEqual(self.submissions(),[]);panel.get_by_role('button',name='确认下载').click()
        expect(self.page.get_by_role('dialog',name='B站扫码登录')).to_be_visible();expect(panel.get_by_label('下载范围',exact=True)).to_be_disabled()
        self.assertEqual(self.submissions(),[]);self.auth=True;self.login_state='authenticated'
        expect(panel.locator(':scope > [role=status]')).to_have_text('本次字幕获取已完成。',timeout=8000)
        self.assertEqual(len(self.submissions()),1);payload=self.submissions()[0][1];self.assertEqual(payload['scope'],'all');self.assertIn('BV',payload['text'])
    def test_switch_video_during_generation_does_not_cancel_backend_job(self):
        self.local_running={};self.card.get_by_role('button',name='重新生成字幕',exact=True).click();panel=self.card.locator('.compact-acquire')
        panel.get_by_role('button',name='确认生成字幕').click();expect(panel.get_by_role('status')).to_contain_text('本次生成正在处理')
        self.h.h.choose(1);expect(self.page.get_by_text('其他视频的转写仍在后台运行，切换不会取消任务。可在任务中心查看。',exact=True)).to_be_visible()
        self.assertEqual(len(self.submissions()),1);self.assertFalse(any(p.endswith('/cancel') for _,p,_ in self.calls));expect(self.card.locator('.compact-acquire')).to_have_count(0)

class EmptyAcquireTests(unittest.TestCase):
    setUpClass = classmethod(lambda cls: flow.SubtitleFunctionTests.setUpClass())
    tearDownClass = classmethod(lambda cls: flow.SubtitleFunctionTests.tearDownClass())
    submissions = CompactAcquireTests.submissions
    def setUp(self):
        self.failed=False
        CompactAcquireTests.setUp(self)
        self.source_rows=self.h.h.sources()
        self.source_rows[0]['title']='已有字幕的很长视频标题，应保留省略而不挤压状态标识'
        self.source_rows[1]['title']='尚无字幕的很长视频标题，应保留省略而不挤压状态标识'
        self.source_rows[1]['source_url']='https://www.bilibili.com/video/BV1TaqYBcEJc?p=2'
        self.h.h.sources=lambda:self.source_rows
        self.h.h.open();self.h.h.choose(1)
        self.panel=self.page.get_by_role('region',name='字幕与转写',exact=True)
    def route(self,route):
        p=urlsplit(route.request.url).path.removeprefix('/api/workspace')
        if self.failed and p=='/subtitles' and route.request.method=='POST':
            self.calls.append(('POST',p,route.request.post_data_json))
            return route.fulfill(json={'id':'a'*32,'state':'failed','title':'fixture','message':'DETAILED FAILURE BELONGS IN TASK CENTER','results':[],'skipped':[],'downloaded':0,'existing':0,'failed':1})
        return CompactAcquireTests.route(self,route)
    def platform(self):
        self.panel.get_by_role('button',name='平台下载字幕',exact=True).click()
        return self.panel.get_by_role('group',name='平台字幕获取确认',exact=True)
    def test_initial_platform_is_compact_history_hidden_and_explicit_submission(self):
        self.page.evaluate("localStorage.setItem('video-parser:task:subtitles','"+'b'*32+"')")
        self.h.h.open();self.h.h.choose(1);panel=self.platform()
        expect(panel.get_by_role('button',name='确认下载')).to_be_enabled()
        expect(panel.get_by_label('下载范围',exact=True)).to_have_count(0)
        expect(panel.get_by_role('button',name='取消',exact=True)).to_have_count(0)
        expect(self.panel).not_to_contain_text('OLD HISTORICAL')
        expect(self.panel.get_by_role('button',name='刷新字幕任务状态')).to_have_count(0)
        self.assertEqual(self.submissions(),[])
        panel.get_by_role('button',name='确认下载').click()
        expect(panel.get_by_role('status')).to_have_text('本次字幕获取已完成。')
        self.assertEqual(len(self.submissions()),1);payload=self.submissions()[0][1]
        self.assertEqual(payload['scope'],'current');self.assertTrue(payload['text'].endswith('?p=2'))
    def test_initial_failure_is_current_only_and_function_switch_does_not_submit(self):
        self.failed=True;panel=self.platform();panel.get_by_role('button',name='确认下载').click()
        expect(panel.get_by_role('status')).to_contain_text('请到任务中心查看原因')
        expect(self.panel).not_to_contain_text('DETAILED FAILURE');expect(self.panel.get_by_role('button',name=re.compile('刷新字幕|重新读取字幕'))).to_have_count(0)
        self.panel.get_by_role('button',name='本地生成字幕',exact=True).click()
        expect(self.panel.get_by_role('group',name='本地字幕生成确认')).to_be_visible()
        panel=self.platform();expect(panel.locator(':scope > [role=status]')).to_have_count(0)
        self.assertEqual(len(self.submissions()),1)
    def test_initial_local_preserves_language_destination_and_explicit_confirmation(self):
        self.panel.get_by_role('button',name='本地生成字幕',exact=True).click();panel=self.panel.get_by_role('group',name='本地字幕生成确认')
        expect(panel.get_by_label('保存到',exact=True)).to_have_value('source')
        panel.get_by_label('字幕语言').select_option('en');self.assertEqual(self.submissions(),[])
        panel.get_by_role('button',name='确认生成字幕').click();expect(panel.get_by_role('alert')).to_have_text('本次模拟服务暂不可用')
        payload=self.submissions()[0][1];self.assertEqual(payload['language'],'en');self.assertEqual(payload['project_id'],self.source_rows[1]['project_id']);self.assertEqual(payload['resource'],self.source_rows[1]['resource'])
    def test_both_badges_remain_horizontal_without_overflow_in_both_themes(self):
        for theme in ('light','dark'):
            self.page.evaluate('(x)=>document.documentElement.dataset.theme=x',theme)
            for width in (1440,1308,768,390,280):
                self.page.set_viewport_size({'width':width,'height':1000});panel=self.platform()
                expect(self.panel.locator('.source-subtitle-status')).to_have_text(['有字幕','无字幕'])
                for badge in self.panel.locator('.source-subtitle-status').all():
                    expect(badge).to_have_css('white-space','nowrap');expect(badge).to_have_css('flex-shrink','0')
                    box=badge.bounding_box();self.assertLess(box['height'],28);self.assertGreater(box['width'],40)
                    self.assertTrue(badge.evaluate('(e)=>{const b=e.getBoundingClientRect(),p=e.closest("label").getBoundingClientRect();return b.right<=p.right&&b.left>=p.left}'))
                self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
        self.assertEqual(self.submissions(),[])
    def test_badge_updates_on_inventory_event_and_unknown_is_not_missing(self):
        self.source_rows[1].pop('has_subtitles');self.page.evaluate("window.dispatchEvent(new Event('video-parser:subtitles-changed'))")
        expect(self.panel.locator('.source-subtitle-status')).to_have_text(['有字幕'])
        self.source_rows[1]['has_subtitles']=True;self.page.evaluate("window.dispatchEvent(new Event('video-parser:subtitles-changed'))")
        expect(self.panel.locator('.source-subtitle-status')).to_have_text(['有字幕','有字幕'])
        self.assertEqual(self.submissions(),[])
