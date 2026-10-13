"""Douyin URL forms and platform-response errors; all network boundaries are offline fixtures."""
import json
import unittest
from unittest.mock import patch

from video_parser.services import videos as cli
from video_parser.platforms.web_fetcher import UrlParser, WebFetcher
from video_parser.platforms.downloaders.douyin_downloader import DouyinDownloader

ID='7617880126232085627'
CANONICAL='https://www.douyin.com/video/'+ID
ADDRESS='https://www.douyin.com/user/self?from_tab_name=main&modal_id='+ID+'&showSubTab=video&showTab=favorite_collection'
SHARE='7.43 Bgb:/ :5pm 04/01 D@U.lC VibeCoding开发前9个步骤和开发中5个关键点 https://v.douyin.com/FjyP0wPvpis/ 复制此链接，打开Dou音搜索，直接观看视频！'


class DouyinTests(unittest.TestCase):
    def test_modal_address_and_tracking_normalize_to_video(self):
        for text in [ADDRESS, '“'+ADDRESS+'”', ADDRESS.replace('&','&amp;')]:
            self.assertEqual(cli.resolve_url(text),(CANONICAL,'抖音'))
        self.assertEqual(UrlParser.extract_video_address(ADDRESS),CANONICAL)
        self.assertEqual(UrlParser.get_video_id(ADDRESS),ID)

    def test_short_share_and_direct_share_have_same_identity(self):
        redirected='https://www.iesdouyin.com/share/video/'+ID+'/?region=CN&from=web_code_link'
        with patch.object(WebFetcher,'fetch_redirect_url',return_value=redirected):
            self.assertEqual(cli.resolve_url(SHARE),(CANONICAL,'抖音'))
        self.assertEqual(cli.resolve_url(redirected),(CANONICAL,'抖音'))
        self.assertEqual(cli.resolve_url(CANONICAL+'?previous_page=web_code_link'),(CANONICAL,'抖音'))

    def test_profile_or_non_numeric_id_does_not_call_downloader(self):
        for text in ['https://www.douyin.com/user/self','https://www.douyin.com/user/self?modal_id=bad','https://www.douyin.com/video/not-a-video']:
            with patch('video_parser.platforms.factory.DownloaderFactory.create_downloader') as create:
                with self.assertRaises(ValueError):cli.parse_link(text)
                create.assert_not_called()

    def test_notes_remain_notes_and_untrusted_redirect_rejected(self):
        url='https://www.douyin.com/note/'+ID
        self.assertEqual(cli.resolve_url(url),(url,'抖音'))
        for redirected in ['http://127.0.0.1/video/'+ID,'https://www.douyin.com:8888/video/'+ID,'https://user:password@www.douyin.com/video/'+ID]:
            with patch.object(WebFetcher,'fetch_redirect_url',return_value=redirected):
                with self.assertRaises(ValueError):cli.resolve_url(SHARE)

    def test_non_json_or_missing_video_has_actionable_error(self):
        response=type('Response',(),{'text':'<html>login needed</html>','status_code':200,
            'raise_for_status':lambda self:None,'json':lambda self:(_ for _ in ()).throw(ValueError('raw JSON error'))})()
        downloader=DouyinDownloader.__new__(DouyinDownloader)
        downloader.aweme_id=ID
        downloader.ms_token='fixture';downloader.ttwid='fixture';downloader.webid='fixture'
        downloader.headers={'User-Agent':'fixture'}
        downloader.common_utils=type('Common',(),{'user_agent':'fixture','get_abogus':lambda *args:'fixture'})()
        with patch('video_parser.platforms.downloaders.douyin_downloader.requests.get',return_value=response):
            with self.assertRaisesRegex(RuntimeError,'抖音.*(?:登录|验证|限制)'):
                downloader.fetch_html_data()

    def test_api_response_checks_identity_and_keeps_successful_payload(self):
        downloader=DouyinDownloader.__new__(DouyinDownloader)
        downloader.aweme_id=ID;downloader.ms_token='fixture';downloader.ttwid='fixture';downloader.webid='fixture'
        downloader.headers={'User-Agent':'fixture'}
        downloader.common_utils=type('Common',(),{'user_agent':'fixture','get_abogus':lambda *args:'fixture'})()
        for payload in [None, {}, {'aweme_detail':None}, {'aweme_detail':{'desc':'missing ID'}}, {'aweme_detail':{'aweme_id':'999'}}]:
            response=type('Response',(),{'raise_for_status':lambda self:None,'json':lambda self:payload})()
            with patch('video_parser.platforms.downloaders.douyin_downloader.requests.get',return_value=response):
                with self.assertRaises(RuntimeError):downloader.fetch_html_data()
        payload={'aweme_detail':{'aweme_id':ID,'desc':'正常标题','video':{'play_addr':{'url_list':['https://cdn.example/video']}}}}
        response=type('Response',(),{'raise_for_status':lambda self:None,'json':lambda self:payload})()
        with patch('video_parser.platforms.downloaders.douyin_downloader.requests.get',return_value=response):
            downloader.data=downloader.fetch_html_data()
        self.assertEqual(downloader.get_title_content(),'正常标题')
        self.assertEqual(downloader.get_real_video_url(),'https://cdn.example/video')

    def test_missing_details_accessors_return_none_without_attribute_error(self):
        downloader=DouyinDownloader.__new__(DouyinDownloader);downloader.data=None
        self.assertIsNone(downloader.get_real_video_url())
        self.assertIsNone(downloader.get_cover_photo_url())


if __name__=='__main__':unittest.main()
