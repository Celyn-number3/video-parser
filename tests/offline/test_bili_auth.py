import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import requests
from fastapi.testclient import TestClient
from video_parser.services import bili_auth as auth, subtitles
from video_parser.web.app import app

QR = {'url': 'https://passport.bilibili.com/h5-app/passport/login/scan?qrcode_key=' + 'a'*32, 'qrcode_key': 'a'*32}


class BiliAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'cookies.json'
        self.path_patch = patch.object(auth, 'cookie_path', return_value=self.path)
        self.path_patch.start()
        self.client = TestClient(app, base_url='http://127.0.0.1:15001', client=('127.0.0.1', 50000))

    def tearDown(self):
        for identifier in list(auth.sessions): auth.discard(identifier)
        self.path_patch.stop()
        self.temp.cleanup()

    def create(self):
        with patch.object(auth, 'api', return_value=QR): return auth.create()

    def test_missing_cookie_does_not_call_network(self):
        with patch.object(auth, 'api') as api:
            self.assertEqual(auth.status(), {'authenticated': False});api.assert_not_called()

    def test_malformed_cookie_is_unauthenticated(self):
        self.path.write_text('broken')
        self.assertFalse(auth.status()['authenticated'])

    def test_generation_exposes_only_local_id_and_image(self):
        q=self.create()
        self.assertEqual(set(q), {'id','state','expires_in','image'})
        self.assertNotEqual(q['id'], QR['qrcode_key'])
        self.assertTrue(q['image'].startswith('data:image/svg+xml;base64,'))

    def test_current_account_domain_supported(self):
        with patch.object(auth, 'api', return_value={**QR,'url':'https://account.bilibili.com/h5/account-h5/auth/scan-web'}):
            self.assertEqual(auth.create()['state'],'waiting')

    def test_reject_untrusted_qr_url(self):
        with patch.object(auth, 'api', return_value={**QR,'url':'https://evil.invalid/'}):
            with self.assertRaises(RuntimeError):auth.create()
        self.assertFalse(auth.sessions)

    def test_waiting_scanned_expired(self):
        q=self.create();identifier=q['id']
        for code,state in [(86101,'waiting'),(86090,'scanned'),(86038,'expired')]:
            auth.sessions[identifier]['last_poll']=-float('inf')
            with patch.object(auth,'api',return_value={'code':code}): self.assertEqual(auth.poll(identifier),{'state':state})
        self.assertNotIn(identifier,auth.sessions)

    def test_local_expiry_no_network(self):
        q=self.create();auth.sessions[q['id']]['expires']=0
        with patch.object(auth,'api') as api:
            self.assertEqual(auth.poll(q['id']),{'state':'expired'});api.assert_not_called()

    def test_poll_rate_limit(self):
        q=self.create()
        with patch.object(auth,'api',return_value={'code':86101}) as api:
            auth.poll(q['id']);auth.poll(q['id']);self.assertEqual(api.call_count,1)

    def test_cancel_does_not_remove_existing_cookie(self):
        self.path.write_text('unchanged')
        q=self.create();auth.discard(q['id'])
        self.assertEqual(auth.poll(q['id']),{'state':'expired'})
        self.assertEqual(self.path.read_text(),'unchanged')

    def test_session_limit(self):
        for _ in range(4): self.create()
        with self.assertRaises(RuntimeError):self.create()

    def test_success_persists_playwright_cookies_not_api_secrets(self):
        q=self.create();s=auth.sessions[q['id']]['client']
        s.cookies.set('SESSDATA','test-fixture-only',domain='.bilibili.com',path='/')
        s.cookies.set('untrusted','not-for-storage',domain='evil.invalid')
        with patch.object(auth,'api',side_effect=[{'code':0,'refresh_token':'must-not-expose','url':'must-not-follow'},{'isLogin':True}]):
            result=auth.poll(q['id'])
        self.assertEqual(result,{'state':'authenticated'})
        data=json.loads(self.path.read_text());self.assertEqual(len(data),1)
        self.assertEqual(data[0]['name'],'SESSDATA');self.assertEqual(data[0]['sameSite'],'Lax')
        self.assertEqual(list(self.path.parent.iterdir()),[self.path])
        self.assertEqual(auth.sessions[q['id']]['key'],'')

    def test_incomplete_credentials_do_not_overwrite_existing(self):
        self.path.write_text('preserve-original')
        with requests.Session() as s:
            with self.assertRaises(RuntimeError):auth.persist(s)
        self.assertEqual(self.path.read_text(),'preserve-original')

    def test_unverified_credentials_do_not_overwrite_existing(self):
        self.path.write_text('preserve-original')
        with requests.Session() as s:
            s.cookies.set('SESSDATA','fixture',domain='.bilibili.com')
            with patch.object(auth,'api',return_value={'isLogin':False}):
                with self.assertRaises(RuntimeError):auth.persist(s)
        self.assertEqual(self.path.read_text(),'preserve-original')

    def test_expired_nav_is_unauthenticated_not_network_error(self):
        s=Mock();s.get.return_value.status_code=200;s.get.return_value.content=b'{}'
        s.get.return_value.json.return_value={'code':-101,'data':{'isLogin':False}}
        self.assertEqual(auth.api(s,auth.NAV),{'isLogin':False})

    def test_api_failure_does_not_expose_raw_response(self):
        s=Mock();s.get.side_effect=requests.ConnectionError('secret-token')
        with self.assertRaises(RuntimeError) as error:auth.api(s,auth.BASE+'poll')
        self.assertNotIn('secret-token',str(error.exception))

    def test_cross_origin_login_rejected(self):
        with patch.object(auth,'create') as create:
            r=self.client.post('/api/workspace/bili-login',json={},headers={'Origin':'https://evil.invalid'})
            self.assertEqual(r.status_code,403);create.assert_not_called()

    def test_login_routes_no_store_and_no_secret_error(self):
        with patch.object(auth,'create',side_effect=RuntimeError('secret-cookie')):
            r=self.client.post('/api/workspace/bili-login',json={})
        self.assertEqual(r.status_code,502);self.assertNotIn('secret-cookie',r.text)
        with patch.object(auth,'status',return_value={'authenticated':False}):
            r=self.client.get('/api/workspace/bili-login/status')
        self.assertIn('no-store',r.headers['cache-control'])

    def test_no_login_never_launches_browser(self):
        with patch.object(auth,'status',return_value={'authenticated':False}),patch.object(subtitles.subprocess,'Popen') as popen:
            code,log=subtitles.run_cli('https://www.bilibili.com/video/BV1TaqYBcEJc',[1])
        self.assertEqual(code,1);self.assertIn('缺少登录 Cookie',log);popen.assert_not_called()

    def test_bridge_forces_headless(self):
        process=Mock();process.communicate.return_value=('fixture',None);process.returncode=0
        with patch.object(auth,'status',return_value={'authenticated':True}),patch.object(subtitles.subprocess,'Popen') as popen:
            popen.return_value.__enter__.return_value=process
            self.assertEqual(subtitles.run_cli('fixture',[1]),(0,{'events':[]}))
            self.assertEqual(popen.call_args.kwargs['env']['BILI_HEADLESS'],'1')


if __name__=='__main__':unittest.main()
