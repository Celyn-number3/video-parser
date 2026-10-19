import re
import json
from video_parser.platforms.downloaders.base_downloader import BaseDownloader
from video_parser.core.logging import logger


class XiaohongshuDownloader(BaseDownloader):
    def __init__(self, real_url):
        super().__init__(real_url)
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
            'Referer': 'https://www.xiaohongshu.com/',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'Sec-Ch-Ua': '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1'
        }
        from video_parser.services import accounts
        cookie = accounts.cookie_header('xiaohongshu')
        if cookie:
            self.headers['Cookie'] = cookie
        self.data = self.fetch_html_data()

    def fetch_html_data(self):
        self.html_content = self.fetch_html_content()
        pattern = re.compile(r'window\.__INITIAL_STATE__\s*=\s*(\{.*\})', re.DOTALL)
        json_data = BaseDownloader.parse_html_data(self.html_content, pattern)
        return json_data

    def _note(self):
        data_dict = json.loads(self.data)
        first_note_id = data_dict['note']['firstNoteId']
        return data_dict['note']['noteDetailMap'][first_note_id]['note']

    def streams(self):
        """Current (2026) page data: per-codec stream lists plus a separate AAC track.

        EF4 is H.264 with audio inside; EF5 is H.265 video only (up to 4K) and needs the
        separate audio from mediaV2.audio_stream. Returns {'videos', 'audio_urls', 'duration'}.
        """
        try:
            video = self._note().get('video') or {}
        except (KeyError, TypeError, ValueError):
            return {'videos': [], 'audio_urls': [], 'duration': None}
        media = video.get('media') or {}
        codecs = {'EF4': 'H.264', 'EF5': 'H.265'}
        videos = []
        for key, items in (media.get('stream') or {}).items():
            if key not in codecs:
                continue  # Unknown codecs (EF6/EF7) are skipped rather than guessed.
            for item in items or []:
                urls = [url for url in [item.get('masterUrl'), *(item.get('backupUrls') or [])] if isinstance(url, str) and url.startswith('http')]
                if urls and item.get('height') and item.get('width'):
                    videos.append({'codec': codecs[key], 'width': item['width'], 'height': item['height'],
                                   'bitrate': item.get('avgBitrate') or 0, 'size': item.get('size'),
                                   'has_audio': key == 'EF4', 'urls': urls})
        audio_urls = []
        try:
            extra = video.get('mediaV2')
            extra = json.loads(extra) if isinstance(extra, str) else (extra or {})
            tracks = [track for tracks in (extra.get('audio_stream') or {}).values() for track in tracks or []]
            if tracks:
                best = max(tracks, key=lambda track: track.get('avg_bitrate') or track.get('audio_bitrate') or 0)
                audio_urls = [url for url in [best.get('master_url'), *(best.get('backup_urls') or [])] if isinstance(url, str) and url.startswith('http')]
        except (ValueError, TypeError, AttributeError):
            audio_urls = []
        duration = (media.get('video') or {}).get('duration')
        return {'videos': videos, 'audio_urls': audio_urls, 'duration': duration if isinstance(duration, (int, float)) and duration > 0 else None}

    def get_real_video_url(self):
        try:
            origin_video_key = ((self._note().get('video') or {}).get('consumer') or {}).get('originVideoKey')
            if origin_video_key:  # Older page data.
                return "http://sns-video-bd.xhscdn.com/" + origin_video_key.replace("\\u002F", "/")
        except (KeyError, TypeError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to parse video URL: {e}")
            return None
        # A single file with sound first (H.264), else the largest stream.
        streams = sorted(self.streams()['videos'], key=lambda item: (item['has_audio'], item['height'], item['bitrate']), reverse=True)
        return streams[0]['urls'][0] if streams else None

    def get_title_content(self):
        try:
            data_dict = json.loads(self.data)
            first_note_id = data_dict['note']['firstNoteId']
            title_content = data_dict['note']['noteDetailMap'][first_note_id]['note']['title']
            desc_content = data_dict['note']['noteDetailMap'][first_note_id]['note']['desc']
            return title_content + desc_content
        except (KeyError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to parse title content: {e}")

    def get_cover_photo_url(self):
        try:
            data_dict = json.loads(self.data)
            first_note_id = data_dict['note']['firstNoteId']
            cover_url = data_dict['note']['noteDetailMap'][first_note_id]['note']['imageList'][0]['urlDefault']
            cover_url = cover_url.replace("\\u002F", "/")
            return cover_url
        except (KeyError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to parse cover URL: {e}")


if __name__ == '__main__':
    real_url = 'https://www.xiaohongshu.com/explore/66265ead000000000d030c3f?xsec_token=ABClLfS3dCR8EaYcL9WW7xzrqPoYH4oOildl5Xg1vGjMo=&xsec_source=pc_search'
    xhs_dl = XiaohongshuDownloader(real_url)
    print(xhs_dl.get_title_content())
    print(xhs_dl.get_cover_photo_url())
    print(xhs_dl.get_real_video_url())
