"""All credentials here are fictional, no real cookie contents are read or transmitted."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock
from requests import Request
from video_parser.services import videos as cli
from video_parser.platforms.downloaders.bilibili_downloader import BilibiliDownloader
from video_parser.platforms import bilibili_session as session


class BilibiliCookieTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.addCleanup(patch.stopall)
        patch.dict('os.environ',{'BILI_SUBTITLE_ROOT':str(self.root)}).start()
        self.path=self.root/'b站_cookies.json'
        self.cookies=[{'name':'SESSDATA','value':'fictional-private-token','domain':'.bilibili.com','path':'/','expires':time.time()+3600,'secure':True}]

    def save(self,cookies=None):
        self.path.write_text(json.dumps(self.cookies if cookies is None else cookies),encoding='utf-8')

    def test_missing_corrupt_expired_and_no_cookie_content_exposed(self):
        self.assertEqual(session.load_cookies()[1],'missing')
        self.path.write_text('broken')
        self.assertEqual(session.load_cookies()[1],'invalid')
        self.save([{**self.cookies[0],'expires':time.time()-60}])
        jar,status=session.load_cookies()
        self.assertEqual(status,'expired')
        self.assertEqual(len(jar),0)
        self.assertNotIn('fictional-private-token',status)

    def test_cookie_domain_scope_header_safety_and_read_only(self):
        self.save(self.cookies+[
            {'name':'other','value':'do-not-send','domain':'.example.com','path':'/'},
            {'name':'bad\r\n','value':'header','domain':'.bilibili.com','path':'/'},
            {'name':'unsafe','value':'x\r\ny','domain':'.bilibili.com','path':'/'},
        ])
        before=self.path.read_bytes()
        jar,status=session.load_cookies()
        self.assertEqual(status,'reused_unverified')
        bili=Request('GET','https://www.bilibili.com/video/BV1TaqYBcEJc',cookies=jar).prepare()
        self.assertIn('SESSDATA=fictional-private-token',bili.headers['Cookie'])
        for url in ['https://cdn.example/video','https://api.bilibili.com/x','http://www.bilibili.com/video/x','https://www.bilibili.com.evil.example/video/x']:
            self.assertNotIn('Cookie',Request('GET',url,cookies=jar).prepare().headers)
        self.assertEqual(self.path.read_bytes(),before)

    def test_only_bilibili_https_pages_and_redirects_receive_session(self):
        self.save()
        client=MagicMock()
        client.__enter__.return_value=client
        response=MagicMock();response.status_code=302;response.headers={'Location':'https://evil.example/collect'}
        client.get.return_value=response
        with patch.object(session.requests,'Session',return_value=client):
            with self.assertRaises(RuntimeError):session.fetch_page('https://www.bilibili.com/video/BV1TaqYBcEJc',{})
        self.assertEqual(client.get.call_count,1)
        self.assertFalse(client.get.call_args.kwargs['allow_redirects'])
        with patch.object(session.requests,'Session') as request:
            with self.assertRaises(ValueError):session.fetch_page('https://www.bilibili.com.evil.example/video/x',{})
            request.assert_not_called()

    def test_refreshing_saved_login_is_seen_on_the_next_parse(self):
        self.save([{**self.cookies[0],'expires':time.time()-60}])
        self.assertEqual(session.load_cookies()[1],'expired')
        self.save()
        self.assertEqual(session.load_cookies()[1],'reused_unverified')
        before=self.path.read_bytes()
        session.load_cookies()
        self.assertEqual(before,self.path.read_bytes())

    def test_request_errors_do_not_echo_cookie_or_url_secrets(self):
        self.save()
        client=MagicMock();client.__enter__.return_value=client
        client.get.side_effect=RuntimeError('fictional-private-token?private-signature')
        with patch.object(session.requests,'Session',return_value=client):
            with self.assertRaises(RuntimeError) as failure:session.fetch_page('https://www.bilibili.com/video/BV1TaqYBcEJc',{})
        self.assertNotIn('fictional-private-token',str(failure.exception))
        self.assertNotIn('private-signature',str(failure.exception))

    def test_authenticated_metadata_adds_available_quality_without_leaking_media_headers(self):
        self.save();before=self.path.read_bytes()
        low={'height':480,'width':852,'id':32,'codecs':'avc1','baseUrl':'https://cdn.example/480'}
        high={'height':1080,'width':1920,'id':80,'codecs':'avc1','baseUrl':'https://cdn.example/1080'}
        client=MagicMock();client.__enter__.return_value=client
        def get(url,**kwargs):
            logged=any(cookie.name=='SESSDATA' for cookie in kwargs['cookies'])
            play={'data':{'dash':{'duration':2,'video':[low,high] if logged else [low], 'audio':[{'baseUrl':'https://cdn.example/audio'}]}}}
            initial={'videoData':{'title':'本地测试','pic':'https://cdn.example/cover','bvid':'BV1TaqYBcEJc'}}
            response=MagicMock();response.status_code=200
            response.text='<script>window.__playinfo__='+json.dumps(play)+'</script><script>window.__INITIAL_STATE__='+json.dumps(initial)+';</script>'
            return response
        client.get.side_effect=get
        with patch.object(session.requests,'Session',return_value=client):
            parsed=cli.parse_link('https://www.bilibili.com/video/BV1TaqYBcEJc')
            self.assertEqual([q['height'] for q in cli.quality_options(parsed)],[1080,480])
            self.assertEqual(parsed.metadata['bilibili_cookie_status'],'reused_unverified')
            self.assertNotIn('Cookie',parsed.headers)
            self.assertNotIn('fictional-private-token',json.dumps(parsed.metadata))
            self.path.unlink()
            anonymous=cli.parse_link('https://www.bilibili.com/video/BV1TaqYBcEJc')
            self.assertEqual([q['height'] for q in cli.quality_options(anonymous)],[480])
        self.save()
        self.assertEqual(before,self.path.read_bytes())


if __name__=='__main__':unittest.main()
