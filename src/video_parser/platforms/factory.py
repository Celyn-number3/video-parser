from video_parser.platforms.downloaders.xiaohongshu_downloader import XiaohongshuDownloader
from video_parser.platforms.downloaders.douyin_downloader import DouyinDownloader
from video_parser.platforms.downloaders.kuaishou_downloader import KuaishouDownloader
from video_parser.platforms.downloaders.bilibili_downloader import BilibiliDownloader
from video_parser.platforms.downloaders.haokan_downloader import HaokanDownloader
from video_parser.platforms.downloaders.weishi_downloader import WeishiDownloader
from video_parser.platforms.downloaders.lishipin_downloader import LishipinDownloader
from video_parser.platforms.downloaders.pipigaoxiao_downloader import PipigaoxiaoDownloader


class DownloaderFactory:
    platform_to_downloader = {
        "小红书": XiaohongshuDownloader,
        "抖音": DouyinDownloader,
        "快手": KuaishouDownloader,
        "哔哩哔哩": BilibiliDownloader,
        "好看视频": HaokanDownloader,
        "微视": WeishiDownloader,
        "梨视频": LishipinDownloader,
        "皮皮搞笑": PipigaoxiaoDownloader
    }

    @staticmethod
    def create_downloader(platform, real_url):
        downloader_class = DownloaderFactory.platform_to_downloader.get(platform)

        return downloader_class(real_url)
