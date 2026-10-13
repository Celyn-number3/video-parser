import os
import re
import json
import random
import time
from video_parser.platforms.web_fetcher import UrlParser
from video_parser.platforms.downloaders.base_downloader import BaseDownloader
from video_parser.core.settings import USER_AGENT_PC
from video_parser.core.logging import logger


class KuaishouDownloader(BaseDownloader):
    def __init__(self, real_url):
        super().__init__(real_url)
        timestamp = int(time.time() * 1000)
        self.headers = {
            "content-type": "application/json; charset=UTF-8",
            'User-Agent': random.choice(USER_AGENT_PC),
            'referer': 'https://www.kuaishou.com/',
            'cookie': os.getenv('KUAISHOU_COOKIE', ''),
        }
        self.data = self.fetch_html_data()
        self.video_id = UrlParser.get_video_id(self.real_url)

    def fetch_html_data(self):
        self.html_content = self.fetch_html_content()
        pattern = re.compile(r'window\.__APOLLO_STATE__\s*=\s*(\{.*\};)', re.DOTALL)
        json_data = BaseDownloader.parse_html_data(self.html_content, pattern)
        return json_data

    def get_real_video_url(self):
        try:
            data_dict = json.loads(self.data)
            video_url = data_dict['defaultClient']['VisionVideoSetRepresentation:1']['url']
            video_addr = video_url.replace("\u002F", "/")
            return video_addr
        except (KeyError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to parse video URL: {e}")

    def get_title_content(self):
        try:
            data_dict = json.loads(self.data)
            title_content = data_dict['defaultClient'][f'VisionVideoDetailPhoto:{self.video_id}']['caption']
            return title_content
        except (KeyError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to parse title content: {e}")

    def get_cover_photo_url(self):
        try:
            data_dict = json.loads(self.data)
            cover_url = data_dict['defaultClient'][f'VisionVideoDetailPhoto:{self.video_id}']['coverUrl']
            return cover_url
        except (KeyError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to parse cover URL: {e}")


if __name__ == '__main__':
    real_url = 'https://www.kuaishou.com/short-video/3xwyjn4ipdhss5c?authorId=3xasa85baf6ipp4&streamSource=find&area=homexxbrilliant'
    ks_dl = KuaishouDownloader(real_url)
    print(ks_dl.get_title_content())
    print(ks_dl.get_cover_photo_url())
    print(ks_dl.get_real_video_url())
