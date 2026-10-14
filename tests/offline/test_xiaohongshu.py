"""Offline: 小红书 page data (2026 layout) -> qualities with a separate AAC track. No network."""
import json
import unittest
from unittest.mock import patch

from video_parser.platforms.downloaders.xiaohongshu_downloader import XiaohongshuDownloader
from video_parser.services import videos


def stream(codec, width, height, bitrate, url):
    return {'videoCodec': codec, 'width': width, 'height': height, 'avgBitrate': bitrate,
            'masterUrl': url, 'backupUrls': [url + '?bak']}


def page(with_audio=True):
    media_v2 = {'audio_stream': {'AAC': [{'avg_bitrate': 193598, 'master_url': 'http://cdn.test/a.m4a', 'backup_urls': []}]}} if with_audio else {}
    note = {'title': '标题', 'desc': '', 'imageList': [{'urlDefault': 'http://cdn.test/c.jpg'}], 'video': {
        'media': {'video': {'duration': 399}, 'stream': {
            'EF4': [stream('EF4', 1280, 720, 841622, 'http://cdn.test/h264-720.mp4')],
            'EF5': [stream('EF5', 1280, 720, 582652, 'http://cdn.test/h265-720.mp4'),
                    stream('EF5', 3840, 2160, 2975351, 'http://cdn.test/h265-2160.mp4')],
            'EF7': [stream('EF7', 1920, 1080, 1, 'http://cdn.test/unknown.mp4')]}},
        'mediaV2': json.dumps(media_v2)}}
    return json.dumps({'note': {'firstNoteId': 'n1', 'noteDetailMap': {'n1': {'note': note}}}})


def downloader(data):
    item = XiaohongshuDownloader.__new__(XiaohongshuDownloader)
    item.real_url, item.headers, item.data = 'https://www.xiaohongshu.com/explore/n1', {'Cookie': 'web_session=x', 'Referer': 'r'}, data
    return item


class XiaohongshuTests(unittest.TestCase):
    def test_streams_and_default_url(self):
        item = downloader(page())
        found = item.streams()
        self.assertEqual(found['audio_urls'], ['http://cdn.test/a.m4a'])
        self.assertEqual(found['duration'], 399)
        self.assertEqual(sorted((v['codec'], v['height']) for v in found['videos']), [('H.264', 720), ('H.265', 720), ('H.265', 2160)])
        self.assertEqual(item.get_real_video_url(), 'http://cdn.test/h264-720.mp4')  # Sound inside first.

    def parse(self, data):
        with patch('video_parser.platforms.factory.DownloaderFactory.create_downloader', return_value=downloader(data)):
            return videos.parse_link('https://www.xiaohongshu.com/explore/n1')

    def test_qualities_prefer_h264_and_merge_audio(self):
        parsed = self.parse(page())
        self.assertEqual([q['label'] for q in parsed.metadata['qualities']], ['2160p · H.265', '720p'])
        self.assertEqual(parsed.video_urls[0], 'http://cdn.test/h265-2160.mp4')
        self.assertEqual(parsed.audio_urls, ['http://cdn.test/a.m4a'])
        self.assertNotIn('Cookie', parsed.headers)
        self.assertEqual(videos.select_quality(parsed, '720p').video_urls[0], 'http://cdn.test/h264-720.mp4')

    def test_without_separate_audio_only_h264(self):
        parsed = self.parse(page(with_audio=False))
        self.assertEqual([q['id'] for q in parsed.metadata['qualities']], ['720p'])
        self.assertEqual(parsed.audio_urls, [])


if __name__ == '__main__':
    unittest.main()
