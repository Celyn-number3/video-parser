import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from video_parser.web.app import app
from video_parser.services import storage,workflows


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
    def test_request_id_and_history_headers(self):
        result=self.client.get('/api/workspace/tasks/'+'0'*32)
        self.assertEqual(result.status_code,404);self.assertRegex(result.headers['X-Request-ID'],'^[a-f0-9]{32}$')
        self.assertEqual(result.headers['Cache-Control'],'no-store')

if __name__=='__main__':unittest.main()
