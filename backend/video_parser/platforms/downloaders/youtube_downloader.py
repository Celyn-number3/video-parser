"""Bounded, cached YouTube metadata lookup; no credentials or signed URLs exposed."""
import json
import subprocess
import sys
from video_parser.platforms.downloaders.base_downloader import BaseDownloader
from video_parser.platforms.youtube_formats import renditions


class YoutubeAccessError(RuntimeError):
    """Safe user-facing error; never include cookies or extractor response bodies."""


class YoutubeDownloader(BaseDownloader):
    def __init__(self, real_url):
        super().__init__(real_url)
        self.headers = {}
        self._metadata = None
        self._dump = None

    def _data(self):
        if self._dump is None:
            command = [sys.executable, '-X', 'utf8', '-m', 'yt_dlp', '--ignore-config',
                       '--dump-single-json', '--skip-download', '--no-playlist', '--no-warnings',
                       '--quiet', '--socket-timeout', '15', '--retries', '1', '--extractor-retries', '1',
                       '--', self.real_url]
            try:
                result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=60)
                if result.returncode:
                    raise YoutubeAccessError('无法解析该 YouTube 视频；请检查网络或地区限制；年龄限制、会员专属视频不支持。')
                data = json.loads(result.stdout)
                if data.get('_type') in {'playlist', 'multi_video'} or not data.get('id'):
                    raise ValueError('Expected one video')
                self._dump = data
            except subprocess.TimeoutExpired:
                raise YoutubeAccessError('YouTube 解析超时，请稍后重试。') from None
            except (ValueError, TypeError, AttributeError):
                raise YoutubeAccessError('YouTube 返回的信息无效，请重新解析。') from None
        return self._dump

    def metadata(self):
        if self._metadata is None:
            data = self._data()
            self._metadata = {key: data.get(key) for key in ('id', 'title', 'thumbnail', 'duration')}
        return self._metadata

    def qualities(self):
        """Every downloadable rendition, without signed URLs or extractor internals."""
        return renditions(self._data().get('formats'))

    def get_title_content(self):
        return self.metadata().get('title') or 'YouTube video'

    def get_cover_photo_url(self):
        return self.metadata().get('thumbnail')

    def get_real_video_url(self):
        return self.real_url
