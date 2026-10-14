from video_parser.platforms.downloaders.xiaohongshu_downloader import XiaohongshuDownloader
from video_parser.platforms.downloaders.douyin_downloader import DouyinDownloader
from video_parser.platforms.downloaders.bilibili_downloader import BilibiliDownloader
from video_parser.platforms.downloaders.youtube_downloader import YoutubeDownloader


class DownloaderFactory:
    platform_to_downloader = {
        "小红书": XiaohongshuDownloader,
        "抖音": DouyinDownloader,
        "哔哩哔哩": BilibiliDownloader,
        "YouTube": YoutubeDownloader
    }

    @staticmethod
    def create_downloader(platform, real_url):
        downloader_class = DownloaderFactory.platform_to_downloader.get(platform)
        if downloader_class is None:
            raise ValueError('该平台暂不支持。')

        return downloader_class(real_url)
