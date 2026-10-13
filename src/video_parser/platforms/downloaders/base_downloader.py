"""Platform parsing helpers; CLI and library_store own media saving."""
import requests
from bs4 import BeautifulSoup
from video_parser.core.logging import logger


class BaseDownloader:
    def __init__(self, real_url):
        self.real_url = real_url
        self.headers = None
        self.html_content = None

    def get_real_video_url(self):
        raise NotImplementedError

    def get_title_content(self):
        raise NotImplementedError

    def get_cover_photo_url(self):
        raise NotImplementedError

    def fetch_html_content(self):
        try:
            resp = requests.get(self.real_url, headers=self.headers, timeout=5)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            logger.error(f"Failed to get the page: {e}")
        except Exception as e:
            logger.error(f"An error occurred: {e}")

    @staticmethod
    def parse_html_data(html_content, pattern):
        page_obj = BeautifulSoup(html_content, 'lxml')
        script_tags = page_obj.find_all('script')
        for script in script_tags:
            if script.string:
                match = pattern.search(script.string)
                if match:
                    json_data = match.group(1)
                    json_data = json_data.rstrip(';')  # 部分需要去除分号
                    json_data = json_data.replace('undefined', 'null')  # 小红书需要这步骤
                    return json_data
        logger.error("Video object not found")
