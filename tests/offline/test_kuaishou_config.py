"""Kuaishou credentials must come from local configuration, never source literals."""
import os
import unittest
from unittest.mock import patch
from video_parser.platforms.downloaders.kuaishou_downloader import KuaishouDownloader

class KuaishouConfigTests(unittest.TestCase):
    def headers(self):
        with patch.object(KuaishouDownloader, 'fetch_html_data', return_value={}), patch('video_parser.platforms.downloaders.kuaishou_downloader.UrlParser.get_video_id', return_value='fixture'):
            return KuaishouDownloader('https://www.kuaishou.com/short-video/fixture').headers

    def test_cookie_is_read_from_local_environment(self):
        with patch.dict(os.environ, {'KUAISHOU_COOKIE': 'fixture_cookie=test-value'}):
            self.assertEqual(self.headers()['cookie'], 'fixture_cookie=test-value')

    def test_missing_cookie_does_not_use_embedded_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.headers()['cookie'], '')
