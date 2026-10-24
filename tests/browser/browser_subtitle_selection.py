"""Bidirectional source/workbench selection with intercepted APIs and no model/library writes."""
import re
import unittest
from urllib.parse import urlsplit, parse_qs
from playwright.sync_api import expect
from tests.browser import browser_workspace_picker as picker_tests
from tests.browser.project_picker import select_project

FIRST=picker_tests.FIRST
SECOND=picker_tests.SECOND
THIRD=f'{5:032x}'
JOB='f'*32

def fixture_type():
    class Fixture(picker_tests.fixture_type()):
        def setUp(self):
            super().setUp();self.job_source=SECOND;self.job_state='completed';self.job_reads=0;self.extra_quality=False
        def parsed_for(self, identifier, resource=None):
            result=super().parsed_for(identifier)
            if identifier==THIRD:
                result['project'].update(part=3,episode_title='第三讲')
            if resource:
                result['media']={**result['media'],'resource':resource}
                result['qualities']=[{**result['qualities'][0],'media':result['media']}]
            return result
        def sources(self):
            rows=[]
            for pid in (FIRST,SECOND,THIRD):
                parsed=self.parsed_for(pid);p=parsed['project']
                rows.append({'project_id':pid,'resource':parsed['media']['resource'],'title':p['episode_title'],
                    'part':p['part'],'platform':'哔哩哔哩','source_url':parsed['source_url'],'quality':'720p',
                    'duration_seconds':1,'size_bytes':len(self.audio),'archived_at':'','has_subtitles':True,'subtitle_count':1})
            if self.extra_quality:rows.append({**rows[0],'resource':'video/alternate.wav','title':'第一讲 另一画质','quality':'480p'})
            if getattr(self,'many',False):rows.extend([{**rows[0],'resource':f'video/additional-{n}.wav','title':f'额外素材{n}'} for n in range(4)])
            return rows
        def route(self, route):
            req=route.request;url=urlsplit(req.url);path=url.path.removeprefix('/api/workspace')
            if url.hostname=='127.0.0.1' and url.port==self.server.server_port:
                if path=='/transcriptions/sources':
                    self.requests.append((req.method,path,None));return route.fulfill(json={'sources':self.sources()})
                if path=='/projects':
                    return route.fulfill(json={'projects':[{**self.parsed_for(pid)['project'],'archived':True} for pid in (FIRST,SECOND,THIRD)]})
                if path.endswith('/subtitles'):
                    self.requests.append((req.method,path,None));pid=path.split('/')[2]
                    resource=parse_qs(url.query).get('video_resource',[''])[0]
                    selected={'resource':'subtitles/original.srt','filename':'original.srt','kind':'subtitle','language':'zh','url':'/fixture'}
                    return route.fulfill(json={'project_id':pid,'has_subtitles':True,'files':[selected],'selected':selected,
                        'text':self.parsed_for(pid)['project']['episode_title']+' 字幕 '+resource,'translations':[]})
                if path=='/transcriptions/'+JOB:
                    self.job_reads+=1;self.requests.append((req.method,path,None))
                    return route.fulfill(json={'id':JOB,'state':self.job_state,'kind':'transcriptions','operation':'transcription',
                        'source_project_id':self.job_source,'source_resource':self.parsed_for(self.job_source)['media']['resource'],
                        'project_id':self.job_source,'message':'合成后台任务','text':'后台任务正文','language':'zh',
                        'requested_language':'auto','files':[],'progress':{},'created':1})
                if path.endswith('/resume') and not self.hold_resume and not self.fail_resume:
                    self.requests.append((req.method,path,None));pid=path.split('/')[2]
                    resource=parse_qs(url.query).get('quality_id',[''])[0]
                    return route.fulfill(json=self.parsed_for(pid,resource or None))
            return super().route(route)
    return Fixture

class SubtitleSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):picker_tests.WorkspacePickerTests.setUpClass()
    @classmethod
    def tearDownClass(cls):picker_tests.WorkspacePickerTests.tearDownClass()
    def setUp(self):
        self.f=fixture_type()('test_settings_cross_tab_updates');self.f.setUp();self.page=self.f.page
    def tearDown(self):self.f.tearDown()
    def picker(self):return self.page.get_by_role('combobox',name='已归档视频',exact=True)
    def row(self,title):return self.page.locator('.source-option').filter(has=self.page.locator('.source-title',has_text=title))
    def radio(self,index):return self.page.get_by_role('radiogroup',name='选择视频',exact=True).get_by_role('radio').nth(index)
    def open(self):
        self.page.goto(self.f.url+'/?project='+FIRST+'&page=transcription')
        expect(self.picker()).to_have_attribute('data-value',FIRST)
        self.page.get_by_role('button',name=re.compile('^已归档视频')).click()
        expect(self.radio(0)).to_be_checked()
    def aligned(self,pid,index):
        expect(self.picker()).to_have_attribute('data-value',pid);expect(self.picker()).to_be_enabled()
        expect(self.radio(index)).to_be_checked()
        expect(self.page.get_by_role('textbox',name='字幕原文',exact=True)).to_have_value(re.compile(re.escape(self.f.parsed_for(pid)['project']['episode_title'])))
        expect(self.page.get_by_role('tab',name='字幕与转写',exact=True)).to_have_attribute('aria-selected','true')
    def test_both_selectors_follow_each_other_and_preserve_draft_filter_and_context(self):
        self.f.many=True;self.open();self.page.get_by_role('tab',name='AI 分析',exact=True).click();self.page.locator('#prompt').fill('保留草稿')
        self.page.get_by_role('tab',name='字幕与转写',exact=True).click()
        self.page.get_by_role('searchbox',name='搜索归档视频',exact=True).fill('讲')
        self.radio(1).click();self.aligned(SECOND,1)
        select_project(self.picker(),FIRST);self.aligned(FIRST,0)
        self.page.get_by_role('tab',name='AI 分析',exact=True).click();expect(self.page.locator('#prompt')).to_have_value('保留草稿')
        expect(self.page.locator('.video-context-heading strong')).to_have_text('第一讲')
        self.page.get_by_role('tab',name='字幕与转写',exact=True).click();self.radio(1).click();self.aligned(SECOND,1)
        expect(self.page.get_by_role('searchbox',name='搜索归档视频',exact=True)).to_have_value('讲')
        self.page.get_by_role('button',name='学习视图',exact=True).click()
        expect(self.page.get_by_role('combobox',name='学习项目',exact=True)).to_have_attribute('data-value',SECOND)
        self.assertEqual([(m,p) for m,p,_ in self.f.requests if m=='POST' and not p.endswith('/conversations/migrate') and p!='/subtitles/inventory'],[])
    def test_failed_restore_does_not_change_either_selection_or_subtitle(self):
        self.open();self.f.fail_resume=True;self.radio(1).click()
        expect(self.page.get_by_role('alert').filter(has_text='模拟归档读取失败')).to_be_visible();self.aligned(FIRST,0)
        self.f.fail_resume=False;self.radio(1).click();self.aligned(SECOND,1)
    def test_latest_left_click_wins_over_delayed_old_restore(self):
        self.open();self.f.hold_resume=True;self.radio(1).click()
        expect(self.picker()).to_be_disabled();self.assertIsNotNone(self.f.held_resume)
        old=self.f.held_resume;self.f.hold_resume=False;self.radio(2).click();self.aligned(THIRD,2)
        old.fulfill(json=self.f.parsed_for(SECOND));self.aligned(THIRD,2)
    def test_same_project_different_video_resource_is_preserved(self):
        self.f.extra_quality=True;self.open();self.radio(3).click()
        expect(self.radio(3)).to_be_checked();expect(self.picker()).to_be_enabled()
        expect(self.picker()).to_have_attribute('data-value',FIRST)
        expect(self.page.get_by_role('textbox',name='字幕原文',exact=True)).to_have_value(re.compile('video/alternate.wav'))
        self.page.evaluate("window.dispatchEvent(new Event('video-parser:subtitles-changed'))")
        expect(self.radio(3)).to_be_checked()
        self.radio(1).click();self.aligned(SECOND,1)
    def test_running_task_never_cancels_or_pulls_selection_back_when_completed(self):
        self.f.job_source=FIRST;self.f.job_state='running'
        self.page.add_init_script(f"localStorage.setItem('video-parser:task:transcriptions','{JOB}')")
        self.open();self.radio(1).click();self.aligned(SECOND,1)
        expect(self.page.get_by_text('其他视频的转写仍在后台运行，切换不会取消任务。可在任务中心查看。',exact=True)).to_be_visible()
        self.f.job_state='completed'
        with self.page.expect_response(lambda response: urlsplit(response.url).path=='/api/workspace/transcriptions/'+JOB):
            self.page.wait_for_timeout(10)
        self.aligned(SECOND,1)
        self.assertFalse(any(m=='POST' and p.endswith('/cancel') for m,p,_ in self.f.requests))
    def test_hidden_remembered_task_does_not_hijack_project_but_explicit_restore_syncs(self):
        self.page.add_init_script(f"localStorage.setItem('video-parser:task:transcriptions','{JOB}')")
        self.page.goto(self.f.url+'/?project='+FIRST)
        expect(self.picker()).to_have_attribute('data-value',FIRST);expect(self.picker()).to_be_enabled()
        expect(self.page.locator('.info-title')).to_have_text('第一讲')
        self.assertGreater(self.f.job_reads,0)
        self.assertFalse(any(p=='/projects/'+SECOND+'/resume' for _,p,_ in self.f.requests))
        self.page.evaluate("id=>window.dispatchEvent(new CustomEvent('video-parser:restore-task',{detail:{kind:'transcriptions',id}}))",JOB)
        self.aligned(SECOND,1)
