"""Browser payload and page-identity regressions; isolated Chromium never visits a platform."""
from pathlib import Path
import unittest
from unittest.mock import patch

from playwright.sync_api import sync_playwright
from video_parser.platforms import douyin_browser as browser

ID='7617880126232085627'


class BrowserPayloadTests(unittest.TestCase):
    def payload(self):
        return {'id':ID,'title':'目标视频','duration_ms':538611,'width':1080,'height':1920,
                'video_urls':['https://v26-weba.douyinvod.com/video.mp4?sign=fixture'],
                'cover_urls':['https://p3.douyinpic.com/cover.jpg'],'user_agent':'fixture'}

    def test_normalize_exact_video_and_urls(self):
        data=browser.normalize(self.payload(),ID)
        self.assertEqual(data['aweme_detail']['aweme_id'],ID)
        self.assertEqual(data['aweme_detail']['desc'],'目标视频')
        self.assertEqual(data['aweme_detail']['video']['play_addr']['url_list'],self.payload()['video_urls'])

    def test_wrong_video_private_urls_and_missing_fields_rejected(self):
        for changes in [{'id':'999'},{'video_urls':['http://127.0.0.1/private']},
                        {'video_urls':['https://douyinvod.com.evil.example/video']},
                        {'video_urls':['https://user:secret@v26-weba.douyinvod.com/video']},
                        {'video_urls':['https://v26-weba.douyinvod.com:8888/video']},
                        {'title':''},{'duration_ms':0},{'video_urls':[]}]:
            with self.subTest(changes=changes),self.assertRaises(browser.BrowserParseError):
                browser.normalize({**self.payload(),**changes},ID)

    def test_react_page_extraction_matches_only_requested_id(self):
        with sync_playwright() as p:
            if not Path(p.chromium.executable_path).is_file():
                self.skipTest('Playwright Chromium engine is not installed; browser integration not verified')
            instance=p.chromium.launch(headless=True)
            page=instance.new_page()
            page.set_content('<div id="target"><video></video></div>')
            detail={'awemeId':ID,'desc':'目标视频','video':{'width':1080,'height':1920,'duration':538611,
                'playAddr':[{'src':'https://v26-weba.douyinvod.com/video.mp4'}],
                'originCoverUrlList':['https://p3.douyinpic.com/cover.jpg']}}
            page.evaluate('(detail)=>{document.querySelector("#target").__reactFiber$fixture={memoizedProps:{awemeInfo:detail},return:null}}',detail)
            found=page.evaluate(browser.extraction_script(ID))
            self.assertEqual(found['id'],ID)
            self.assertEqual(found['video_urls'][0],detail['video']['playAddr'][0]['src'])
            self.assertIsNone(page.evaluate(browser.extraction_script('999')))
            instance.close()

    def test_downloader_falls_back_without_changing_legacy_success(self):
        from video_parser.platforms.downloaders.douyin_downloader import DouyinDownloader,DouyinAccessError
        result=browser.normalize(self.payload(),ID)
        common=type('Common',(),{'user_agent':'fixture','get_ms_token':lambda self:'fixture'})
        with patch('video_parser.platforms.downloaders.douyin_downloader.CommonUtils',common),patch.object(DouyinDownloader,'fetch_html_content'), \
             patch.object(DouyinDownloader,'fetch_html_data',side_effect=DouyinAccessError()), \
             patch('video_parser.platforms.downloaders.douyin_downloader.resolve_in_browser',return_value=result) as fallback:
            downloader=DouyinDownloader('https://www.douyin.com/video/'+ID)
        self.assertEqual(downloader.get_title_content(),'目标视频')
        self.assertEqual(downloader.get_real_video_url(),self.payload()['video_urls'][0])
        fallback.assert_called_once()
        with patch('video_parser.platforms.downloaders.douyin_downloader.CommonUtils',common),patch.object(DouyinDownloader,'fetch_html_content'), \
             patch.object(DouyinDownloader,'fetch_html_data',return_value=result), \
             patch('video_parser.platforms.downloaders.douyin_downloader.resolve_in_browser') as fallback:
            self.assertEqual(DouyinDownloader('https://www.douyin.com/video/'+ID).get_title_content(),'目标视频')
        fallback.assert_not_called()


if __name__=='__main__':unittest.main()
