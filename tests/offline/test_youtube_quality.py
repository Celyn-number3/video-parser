"""YouTube renditions: the quality menu must mirror yt-dlp instead of a 1080p cap."""
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from video_parser.platforms import youtube
from video_parser.platforms.downloaders.youtube_downloader import YoutubeDownloader
from video_parser.platforms.youtube_formats import renditions
from video_parser.services import library, videos

ID = 'eRsGyueVLvQ'
URL = 'https://www.youtube.com/watch?v=' + ID

FORMATS = [
    {'format_id': 'sb0', 'ext': 'mhtml', 'vcodec': 'none', 'width': 48, 'height': 27},
    {'format_id': '139', 'ext': 'm4a', 'vcodec': 'none', 'acodec': 'mp4a.40.5'},
    {'format_id': '160', 'ext': 'mp4', 'vcodec': 'avc1.4d400c', 'acodec': 'none', 'width': 256, 'height': 144, 'fps': 30, 'tbr': 100},
    {'format_id': '133', 'ext': 'mp4', 'vcodec': 'avc1.4d4015', 'acodec': 'none', 'width': 426, 'height': 240, 'fps': 30, 'tbr': 300},
    {'format_id': '134', 'ext': 'mp4', 'vcodec': 'avc1.4d401e', 'acodec': 'none', 'width': 640, 'height': 360, 'fps': 30, 'tbr': 600},
    {'format_id': '135', 'ext': 'mp4', 'vcodec': 'avc1.4d401f', 'acodec': 'none', 'width': 854, 'height': 480, 'fps': 30, 'tbr': 1000},
    {'format_id': '136', 'ext': 'mp4', 'vcodec': 'avc1.4d401f', 'acodec': 'none', 'width': 1280, 'height': 720, 'fps': 30, 'tbr': 2000},
    {'format_id': '247', 'ext': 'webm', 'vcodec': 'vp9', 'acodec': 'none', 'width': 1280, 'height': 720, 'fps': 30, 'tbr': 2100},
    {'format_id': '137', 'ext': 'mp4', 'vcodec': 'avc1.640028', 'acodec': 'none', 'width': 1920, 'height': 1080, 'fps': 30, 'tbr': 4000},
    {'format_id': '248', 'ext': 'webm', 'vcodec': 'vp9', 'acodec': 'none', 'width': 1920, 'height': 1080, 'fps': 30, 'tbr': 4200},
    {'format_id': '299', 'ext': 'mp4', 'vcodec': 'avc1.64002a', 'acodec': 'none', 'width': 1920, 'height': 1080, 'fps': 60, 'tbr': 6000},
    {'format_id': '271', 'ext': 'webm', 'vcodec': 'vp9', 'acodec': 'none', 'width': 2560, 'height': 1440, 'fps': 30, 'tbr': 9000},
    {'format_id': '313', 'ext': 'webm', 'vcodec': 'vp9', 'acodec': 'none', 'width': 3840, 'height': 2160, 'fps': 30, 'tbr': 18000},
    {'format_id': '401', 'ext': 'mp4', 'vcodec': 'av01.0.13M.08', 'acodec': 'none', 'width': 3840, 'height': 2160, 'fps': 30, 'tbr': 16000},
    {'format_id': '337', 'ext': 'webm', 'vcodec': 'vp09.02.51.10', 'acodec': 'none', 'width': 3840, 'height': 2160,
     'fps': 30, 'dynamic_range': 'HDR', 'tbr': 20000},
    {'format_id': '999', 'ext': 'mp4', 'vcodec': 'avc1.640028', 'acodec': 'none', 'width': 1920, 'height': 1080,
     'fps': 30, 'format_note': 'Premium', 'tbr': 8000},
    {'format_id': '22', 'ext': 'mp4', 'vcodec': 'avc1.64001f', 'acodec': 'mp4a.40.2', 'width': 1280, 'height': 720,
     'fps': 30, 'tbr': 2200},
]


def fake_downloader(formats=None):
    class Fake:
        headers = {}
        def __init__(self, url):
            self.real_url = url
        def metadata(self):
            return {'id': ID, 'title': 'Sintel', 'thumbnail': 'https://example.test/cover.jpg', 'duration': 888}
        def qualities(self):
            return renditions(FORMATS if formats is None else formats)
        def get_title_content(self):
            return self.metadata()['title']
        def get_real_video_url(self):
            return self.real_url
        def get_cover_photo_url(self):
            return self.metadata()['thumbnail']
    return Fake


class RenditionTests(unittest.TestCase):
    def test_every_resolution_is_listed_without_urls(self):
        options = renditions(FORMATS)
        self.assertEqual([item['id'] for item in options],
                         ['2160p', '1440p', '1080p60', '1080p', '720p', '480p', '360p', '240p', '144p'])
        self.assertNotIn('https://', json.dumps(options))
        self.assertNotIn('url', json.dumps(options))

    def test_compatible_codec_wins_and_codec_is_labelled(self):
        by_id = {item['id']: item for item in renditions(FORMATS)}
        self.assertEqual(by_id['1080p']['codec'], 'H.264')       # 137 beats VP9 248
        self.assertEqual(by_id['1080p60']['format_id'], '299')
        self.assertEqual(by_id['2160p']['codec'], 'VP9')         # HDR and AV1 are not preferred
        self.assertEqual(by_id['2160p']['label'], '2160p · VP9')
        self.assertEqual(by_id['720p']['format_id'], '136')      # muxed 22 is not preferred over DASH
        self.assertFalse(by_id['1080p']['has_audio'])

    def test_premium_hdr_and_audio_only_are_skipped(self):
        ids = {item['format_id'] for item in renditions(FORMATS)}
        self.assertNotIn('999', ids)
        self.assertNotIn('337', ids)
        self.assertNotIn('139', ids)
        self.assertNotIn('sb0', ids)

    def test_missing_formats_yield_no_options(self):
        self.assertEqual(renditions(None), [])
        self.assertEqual(renditions([{'format_id': 'x'}, 'junk']), [])


class YoutubeQualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(); self.addCleanup(patch.stopall)
        patch.object(library, 'LIBRARY_ROOT', self.root / 'library').start()
        patch('video_parser.platforms.factory.DownloaderFactory.create_downloader',
              side_effect=lambda platform, url: fake_downloader()(url)).start()

    def parsed(self):
        return videos.parse_link(URL)

    def test_parse_lists_real_renditions_and_keeps_page_url(self):
        parsed = self.parsed()
        self.assertEqual([item['id'] for item in videos.quality_options(parsed)],
                         ['2160p', '1440p', '1080p60', '1080p', '720p', '480p', '360p', '240p', '144p'])
        self.assertEqual(parsed.video_urls, [URL])
        self.assertNotIn('https://', json.dumps(videos.quality_options(parsed)))

    def test_selection_pins_format_without_losing_source_url(self):
        parsed = videos.select_quality(self.parsed(), '2160p')
        self.assertEqual(parsed.metadata['selected_quality']['format_id'], '313')
        self.assertEqual(parsed.metadata['height'], 2160)
        self.assertEqual(parsed.video_urls, [URL])
        self.assertEqual(parsed.metadata['video_url'], URL)
        numeric = videos.select_quality(self.parsed(), '1080')
        self.assertEqual(numeric.metadata['quality_id'], '1080p')

    def test_unknown_resolution_is_rejected(self):
        with self.assertRaises(ValueError):
            videos.select_quality(self.parsed(), '4320p')

    def test_download_uses_selected_rendition(self):
        parsed = videos.select_quality(self.parsed(), '1440p')
        target = self.root / 'out.mp4'
        media = {'format': {'duration': 888}, 'streams': [
            {'codec_type': 'video', 'width': 2560, 'height': 1440, 'codec_name': 'vp9'},
            {'codec_type': 'audio', 'codec_name': 'aac'}]}
        seen = {}

        def download(url, staged, progress, format_id=None, has_audio=None):
            seen.update(url=url, format_id=format_id, has_audio=has_audio)
            Path(staged).write_bytes(b'video')

        with patch('video_parser.platforms.youtube.download_youtube', side_effect=download), \
                patch.object(videos, 'require_tools'), patch.object(videos, 'probe', return_value=media):
            result = videos.download_video(parsed, target)
        self.assertEqual(seen, {'url': URL, 'format_id': '271', 'has_audio': False})
        self.assertEqual(result['size_bytes'], 5)

    def test_archived_quality_is_reused_for_legacy_1080p(self):
        parsed = self.parsed()
        project = library.ensure(parsed.metadata)
        legacy_media = {'format': {'duration': 888}, 'streams': [
            {'codec_type': 'video', 'width': 1920, 'height': 1080, 'codec_name': 'h264'},
            {'codec_type': 'audio', 'codec_name': 'aac'}]}
        source = self.root / 'legacy.mp4'; source.write_bytes(b'legacy')
        library.import_file(project['id'], source, 'videos/default.mp4', 'video',
                            {'media': legacy_media,
                             'selected_quality': {'id': 'default', 'label': '最高 1080p · MP4',
                                                  'width': None, 'height': None, 'codec': None}})
        with patch.object(videos, 'download_video') as download:
            result = videos.archive_video(videos.select_quality(parsed, '1080p'))
        download.assert_not_called()
        self.assertEqual(Path(result['path']).read_bytes(), b'legacy')


class DownloadSelectorTests(unittest.TestCase):
    def test_selected_format_merges_best_aac_audio(self):
        self.assertEqual(youtube.format_selector('271', False), '271+ba[ext=m4a]/271+ba[acodec^=mp4a]/271')
        self.assertEqual(youtube.format_selector('22', True), '22')
        self.assertEqual(youtube.format_selector(None), youtube.DEFAULT_FORMAT)

    def test_options_carry_the_selected_format(self):
        captured = {}

        class FakeYDL:
            def __init__(self, options): captured.update(options)
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def download(self, urls): Path(captured['outtmpl']).write_bytes(b'merged')

        with tempfile.TemporaryDirectory() as temp, patch('yt_dlp.YoutubeDL', FakeYDL):
            youtube.download_youtube(URL, Path(temp) / 'out.mp4', format_id='271', has_audio=False)
        self.assertTrue(captured['format'].startswith('271+ba'))

    def test_qualities_reuse_the_single_metadata_dump(self):
        payload = {'id': ID, 'title': 'Sintel', 'duration': 888, 'formats': FORMATS, 'url': 'secret'}
        with patch('subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps(payload))) as run:
            downloader = YoutubeDownloader(URL)
            downloader.metadata()
            options = downloader.qualities()
            self.assertEqual(run.call_count, 1)
            self.assertEqual(len(options), 9)
            self.assertNotIn('secret', json.dumps(options))


if __name__ == '__main__':
    unittest.main()
