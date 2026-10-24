import json
import tempfile
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from video_parser.web.app import app
from video_parser.services import storage,workflows
from video_parser.web import task_routes


class TaskAPITests(unittest.TestCase):
    def setUp(self):self.client=TestClient(app,base_url='http://127.0.0.1:15001',client=('127.0.0.1',1234))
    def test_cross_origin_new_task_mutations_rejected(self):
        with patch.object(storage,'preview') as preview:
            self.assertEqual(self.client.post('/api/workspace/cache/preview',json={},headers={'Origin':'https://evil.example'}).status_code,403)
            preview.assert_not_called()
        self.assertEqual(self.client.post('/api/workspace/tasks/video/'+'0'*32+'/cancel',json={},headers={'Origin':'https://evil.example'}).status_code,403)
    def test_cleanup_requires_literal_boolean_confirmation(self):
        with patch.object(storage,'clean') as clean:
            for value in (False,1,'true',None):
                result=self.client.post('/api/workspace/cache/clean',json={'plan_id':'0'*32,'confirm':value})
                self.assertEqual(result.status_code,422,value)
            clean.assert_not_called()
    def test_cleanup_plan_token_cannot_be_a_path(self):
        with patch.object(storage,'clean') as clean:
            self.assertEqual(self.client.post('/api/workspace/cache/clean',json={'plan_id':'../../library','confirm':True}).status_code,422)
            clean.assert_not_called()
    def test_async_analysis_needs_explicit_consent(self):
        with patch.object(workflows,'start') as start:
            for consent in (False,1,'true',None):
                result=self.client.post('/api/workspace/videos/missing/analyze-task',json={'consent':consent})
                self.assertEqual(result.status_code,422)
            start.assert_not_called()
    def test_clear_removes_only_failed_cancelled_and_interrupted_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);states={('%032x'%index):state for index,state in enumerate(['completed','failed','cancelled','interrupted','running','empty'],1)}
            for identifier in states:(root/(identifier+'.json')).write_text(json.dumps({'version':1}),encoding='utf-8')
            def get(identifier):
                if not (root/(identifier+'.json')).exists():raise KeyError(identifier)
                return SimpleNamespace(state=states[identifier])
            service=SimpleNamespace(jobs=dict.fromkeys(states),lock=Lock(),get=get)
            with patch.object(task_routes,'catalog',return_value={'transcriptions':(service,root)}):
                for value in (False,1,'true',None):
                    self.assertEqual(self.client.post('/api/workspace/tasks/clear',json={'confirm':value}).status_code,422)
                self.assertEqual(len(list(root.glob('*.json'))),6)
                result=self.client.post('/api/workspace/tasks/clear',json={'confirm':True})
            self.assertEqual(result.json(),{'removed':3})
            left=sorted(states[path.stem] for path in root.glob('*.json'))
            self.assertEqual(left,['completed','empty','running']);self.assertEqual(sorted(states[key] for key in service.jobs),left)
    def test_task_rows_show_current_project_title_and_part(self):
        project={'id':'a'*32,'title':'改过的课程名','part':4,'resources':{'videos/old.mp4':{'kind':'video','storage_path':'videos/1.2 新主题.mp4'}}}
        job=SimpleNamespace(id='b'*32,kind='video',project_id=project['id'])
        service=SimpleNamespace(jobs={job.id:job},lock=Lock(),get=lambda identifier:job,
            view=lambda item:{'id':item.id,'state':'completed','message':'','title':'平台旧标题','created':1})
        with patch.object(task_routes,'catalog',return_value={'workflows':(service,Path('missing'))}),\
             patch.object(task_routes.task_runtime,'recent_ids',return_value=[]),\
             patch.object(task_routes.library,'get',side_effect=lambda identifier:project if identifier==project['id'] else (_ for _ in ()).throw(KeyError(identifier))):
            row=self.client.get('/api/workspace/tasks').json()['jobs'][0]
        self.assertEqual(row['file_names'], ['1.2 新主题.mp4'])
        self.assertEqual(row['video_names'], ['1.2 新主题.mp4'])
        self.assertEqual(row['subjects'], [{'project_id': project['id'], 'part': 4, 'title': ''}])
        self.assertEqual(row['file_details'][0]['role'], 'video')
        self.assertEqual((row['title'],row['project_title'],row['part']),('平台旧标题','改过的课程名',4))
    def test_request_id_and_history_headers(self):
        result=self.client.get('/api/workspace/tasks/'+'0'*32)
        self.assertEqual(result.status_code,404);self.assertRegex(result.headers['X-Request-ID'],'^[a-f0-9]{32}$')
        self.assertEqual(result.headers['Cache-Control'],'no-store')

if __name__=='__main__':unittest.main()
