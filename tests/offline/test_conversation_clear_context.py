"""Reset history boundaries in isolated archives; never real models or user data."""
import hashlib,json
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from tests.offline import test_conversations as fixtures
from video_parser.services import conversations,library,model_calls,local_agents,ai_analysis,workflows
from video_parser.services.local_agents.types import Result

class ConversationClearContextTests(unittest.TestCase):
    def setUp(self):
        fixtures.ConversationTests.setUp(self)
        patch.object(workflows,'jobs',{}).start()
        patch.object(model_calls,'WORKSPACE_ROOT',self.root/'agent-workspaces').start()
    def seed(self,engine='api'):
        c=conversations.create(self.pid,self.video,{'engine':engine})
        library.save_text(self.pid,'conversation-message','旧回答一',{'conversation':c['id'],'question':'old-question-one','sequence':1})
        library.save_text(self.pid,'conversation-message','旧回答二',{'conversation':c['id'],'question':'old-question-two','sequence':2})
        library.update_details(self.pid,f"conversations/{c['id']}.json",{'title_generated':True})
        c=conversations.get(self.pid,c['id']);self.url=f"/api/workspace/projects/{self.pid}/conversations/{c['id']}/clear-context"
        self.body={'resource':self.video,'confirm':True,'expected_last_message_id':c['messages'][-1]['id']}
        return c
    def test_clear_keeps_all_messages_other_sessions_and_resources(self):
        c=self.seed();other=conversations.create(self.pid,self.video)
        project=library.get(self.pid);original={n:hashlib.sha256(library.resource(self.pid,n).read_bytes()).hexdigest() for n in project['resources']}
        with patch.object(model_calls,'call') as model,patch.object(ai_analysis,'extract_frames') as frames:
            r=self.client.post(self.url,json=self.body)
        self.assertEqual(r.status_code,200,r.text);model.assert_not_called();frames.assert_not_called()
        value=r.json()['conversation'];self.assertEqual(value['messages'],c['messages']);self.assertEqual(conversations._history(value),[])
        self.assertEqual(value['context_after'],self.body['expected_last_message_id']);self.assertEqual(conversations.get(self.pid,other['id']),other)
        self.assertEqual(original,{n:hashlib.sha256(library.resource(self.pid,n).read_bytes()).hexdigest() for n in original})
    def test_new_api_turn_omits_old_qa_but_keeps_video_material(self):
        c=self.seed();self.assertEqual(self.client.post(self.url,json=self.body).status_code,200)
        with patch.object(ai_analysis,'call_model',side_effect=[('{"frame_times":[],"subtitle_ranges":[]}',{}),('fresh-answer',{})]) as model:
            value=conversations.ask(self.pid,c['id'],'fresh-question',self.video,24,self.work)
        for call in model.call_args_list:
            text=json.dumps(call.args[0],ensure_ascii=False);self.assertNotIn('old-question',text);self.assertIn('完整字幕',text);self.assertIn('参考资料',text)
        self.assertEqual(len(value['messages']),3);self.assertEqual(conversations._history(value),[{'role':'user','content':'fresh-question'},{'role':'assistant','content':'fresh-answer'}])
    def test_native_engines_cannot_resume_old_session_after_clear(self):
        for engine in ('codex','claude','opencode'):
            with self.subTest(engine=engine):
                c=self.seed(engine);directory=model_calls.workspace(library.get(self.pid)['directory'],c['id']);history=conversations._history(c)
                model_calls.bind_session(directory,engine,history,'old-session')
                library.update_details(self.pid,f"conversations/{c['id']}.json",{'native_session_id':'old-session'})
                with patch.object(local_agents,'complete') as no_model:self.assertEqual(self.client.post(self.url,json=self.body).status_code,200)
                no_model.assert_not_called();self.assertIsNone(model_calls.bound_session(directory,engine,history,'old-session'))
                with patch.object(local_agents,'complete',side_effect=[Result('{"frame_times":[],"subtitle_ranges":[]}'),Result('fresh-native-answer','fresh-session')]) as model:
                    conversations.ask(self.pid,c['id'],'fresh-native-question',self.video,24,self.work,{'engine':engine})
                self.assertIsNone(model.call_args_list[1].kwargs['session_id'])
                self.assertNotIn('old-question',json.dumps(model.call_args_list[1].kwargs['rebuild_messages']))
                self.assertEqual(len(conversations.get(self.pid,c['id'])['messages']),3)
    def test_confirmation_identity_and_stale_last_message_are_guarded(self):
        c=self.seed()
        for v in (False,1,'true'):
            self.assertEqual(self.client.post(self.url,json={**self.body,'confirm':v}).status_code,422)
        self.assertEqual(self.client.post(self.url,json={k:v for k,v in self.body.items() if k!='confirm'}).status_code,422)
        self.assertEqual(self.client.post(self.url,json={**self.body,'resource':'video/another.mp4'}).status_code,400)
        self.assertEqual(self.client.post(self.url,json={**self.body,'expected_last_message_id':'stale'}).status_code,409)
        self.assertEqual(self.client.post(self.url.replace(c['id'],'0'*32),json=self.body).status_code,404)
        self.assertEqual(conversations.get(self.pid,c['id']),c)
    def test_active_jobs_reject_and_transaction_holds_submission_lock(self):
        c=self.seed()
        for state in ('queued','running','cancelling'):
            with patch.dict(workflows.jobs,{'test':SimpleNamespace(project_id=self.pid,kind='analysis',state=state)}):
                self.assertEqual(self.client.post(self.url,json=self.body).status_code,409)
        original=conversations.clear_context
        def checked(*args):
            self.assertTrue(workflows.lock.locked());return original(*args)
        with patch.object(conversations,'clear_context',side_effect=checked):self.assertEqual(self.client.post(self.url,json=self.body).status_code,200)
    def test_repeated_clear_is_idempotent_and_late_new_message_is_not_cleared(self):
        c=self.seed();self.assertEqual(self.client.post(self.url,json=self.body).status_code,200)
        manifest=library.get(self.pid)['directory']/'project.json';stamp=(manifest.stat().st_mtime_ns,manifest.read_bytes())
        self.assertEqual(self.client.post(self.url,json=self.body).status_code,200);self.assertEqual((manifest.stat().st_mtime_ns,manifest.read_bytes()),stamp)
        library.save_text(self.pid,'conversation-message','new-answer',{'conversation':c['id'],'question':'new-question','sequence':3})
        self.assertEqual(self.client.post(self.url,json=self.body).status_code,409)
        self.assertIn('new-question',json.dumps(conversations._history(conversations.get(self.pid,c['id']))))
    def test_failed_metadata_write_keeps_visible_history_and_forces_safe_rebuild(self):
        c=self.seed('codex');directory=model_calls.workspace(library.get(self.pid)['directory'],c['id']);history=conversations._history(c)
        library.update_details(self.pid,f"conversations/{c['id']}.json",{'native_session_id':'old-session'});model_calls.bind_session(directory,'codex',history,'old-session')
        with patch.object(library,'update_details',side_effect=OSError('fixture write error')):
            self.assertEqual(self.client.post(self.url,json=self.body).status_code,507)
        self.assertEqual(conversations.get(self.pid,c['id']),c);self.assertIsNone(model_calls.bound_session(directory,'codex',history,'old-session'))
    def test_empty_session_clear_needs_no_models_or_new_files(self):
        c=conversations.create(self.pid,self.video);url=f"/api/workspace/projects/{self.pid}/conversations/{c['id']}/clear-context"
        with patch.object(model_calls,'workspace') as workspace,patch.object(model_calls,'call') as model:
            r=self.client.post(url,json={'resource':self.video,'expected_last_message_id':None,'confirm':True})
        self.assertEqual(r.status_code,200);self.assertEqual(r.json()['conversation'],c);workspace.assert_not_called();model.assert_not_called()
