"""Offline regressions for Bilibili episode extraction and parse metadata."""
import json
import unittest
from unittest.mock import patch

from video_parser.platforms.downloaders.bilibili_downloader import BilibiliDownloader
from video_parser.services import videos


class BilibiliEpisodeTests(unittest.TestCase):
    def test_pages_are_normalized_sorted_and_bounded(self):
        downloader = BilibiliDownloader.__new__(BilibiliDownloader)
        downloader.data2 = json.dumps({'videoData': {'pages': [
            {'page': 3, 'part': '  收尾  总结  ', 'duration': 125},
            {'page': 1, 'part': ' 开始 ', 'duration': 90},
            {'page': 2, 'part': '异常时长', 'duration': 10 ** 400},
            {'page': True, 'part': '布尔编号', 'duration': 30},
            {'page': 0, 'part': '零编号', 'duration': 30},
            None,
        ]}})
        self.assertEqual(downloader.get_episodes(), [
            {'part': 1, 'title': '开始', 'duration': 90},
            {'part': 2, 'title': '异常时长', 'duration': None},
            {'part': 3, 'title': '收尾 总结', 'duration': 125},
        ])
        downloader.data2 = '{malformed'
        self.assertEqual(downloader.get_episodes(), [])

    def test_parse_link_includes_episodes_without_downloading(self):
        episodes = [{'part': 1, 'title': '开场', 'duration': 75}, {'part': 2, 'title': '结尾', 'duration': None}]

        class FakeDownloader:
            cookie_status = 'available'
            headers = {}

            def get_title_content(self): return '多分集视频'
            def get_real_video_url(self): return 'https://cdn.example/video'
            def get_cover_photo_url(self): return None
            def get_episodes(self): return episodes

        source = 'https://www.bilibili.com/video/BV1TaqYBcEJc'
        with patch.object(videos, 'resolve_url', return_value=(source, '哔哩哔哩')) as resolve:
            with patch('video_parser.platforms.factory.DownloaderFactory.create_downloader', return_value=FakeDownloader()) as create:
                parsed = videos.parse_link(source, require_video=False)
        self.assertEqual(parsed.metadata['episodes'], episodes)
        self.assertEqual(parsed.metadata['platform'], '哔哩哔哩')
        resolve.assert_called_once_with(source)
        create.assert_called_once()


if __name__ == '__main__':
    unittest.main()
