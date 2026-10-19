import re
import ipaddress
import socket
from html import unescape
import requests
import random
from urllib.parse import urlparse, parse_qs, urljoin, urlunparse
from video_parser.core.logging import logger
from video_parser.core.settings import USER_AGENT_PC, DOMAIN_TO_NAME


class WebFetcher:
    headers = {
        "content-type": "application/json; charset=UTF-8",
        "User-Agent": random.choice(USER_AGENT_PC)
    }

    SHORT_HOSTS = {'b23.tv', 'v.douyin.com', 'xhslink.com', 'www.xhslink.com'}

    @staticmethod
    def _validated_url(url):
        if not isinstance(url, str) or any(ord(char) <= 32 for char in url) or '\\' in url:
            raise ValueError('Invalid short-link URL')
        parsed = urlparse(url)
        host = (parsed.hostname or '').lower()
        aliases = {name[4:]: name for name in DOMAIN_TO_NAME if name.startswith('www.')}
        aliases['m.bilibili.com'] = 'www.bilibili.com'
        host = aliases.get(host, host)
        if (parsed.scheme != 'https' or parsed.username is not None or parsed.password is not None or
                parsed.port not in (None, 443) or host not in WebFetcher.SHORT_HOSTS | set(DOMAIN_TO_NAME)):
            raise ValueError('Untrusted short-link destination')
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
            raise ValueError('Non-public short-link address')
        return urlunparse(('https', host, parsed.path, parsed.params, parsed.query, ''))

    @staticmethod
    def fetch_redirect_url(url, max_redirects=5, preserve_query=False):
        try:
            current_url = WebFetcher._validated_url(url)
            for _ in range(max_redirects):
                if urlparse(current_url).hostname in DOMAIN_TO_NAME:
                    return current_url if preserve_query else UrlParser.extract_video_address(current_url)
                resp = requests.get(current_url, headers=WebFetcher.headers, allow_redirects=False, timeout=5)
                resp.raise_for_status()
                location = resp.headers.get('location') if resp.status_code in (301, 302, 303, 307, 308) else None
                if not location:
                    return None
                # Validate every hop before another request or returning a platform URL.
                current_url = WebFetcher._validated_url(urljoin(current_url, location))
                if urlparse(current_url).hostname in DOMAIN_TO_NAME:
                    return current_url if preserve_query else UrlParser.extract_video_address(current_url)
            return None
        except Exception as error:
            # Exceptions can embed signed URLs; do not log response URLs or free-text errors.
            logger.warning('Short-link resolution failed (%s)', type(error).__name__)
            return None



class UrlParser:
    @staticmethod
    def convert_to_https(url):
        if url is None:
            return None
        if url.startswith('http://'):
            return 'https://' + url[7:]
        return url

    @staticmethod
    def get_url(text):
        url_pattern = re.compile(r'\bhttps?:\/\/(?:www\.|[-a-zA-Z0-9.@:%_+~#=]{1,256}\.[a-zA-Z0-9()]{1,6})\b(?:[-a-zA-Z0-9()@:%_+.~#?&//=]*)?')
        match = url_pattern.search(unescape(text))
        if match:
            return match.group()
        else:
            return None

    @staticmethod
    def get_domain(url):
        parsed_url = urlparse(url)
        domain = parsed_url.netloc
        return domain

    @staticmethod
    def douyin_video_address(url):
        parsed = urlparse(url)
        match = re.fullmatch(r'/(?:share/)?(video|note)/(\d{1,25})/?', parsed.path)
        if match:
            kind, identifier = match.groups()
        else:
            identifier = parse_qs(parsed.query).get('modal_id', [''])[0]
            if not re.fullmatch(r'\d{1,25}', identifier):
                raise ValueError('抖音链接中没有有效的视频编号，请复制具体视频的分享链接。')
            kind = 'video'
        return f'https://www.douyin.com/{kind}/{identifier}'

    @staticmethod
    def extract_video_address(url):
        parsed_url = urlparse(url)
        domain = parsed_url.netloc
        platform = DOMAIN_TO_NAME.get(domain)
        if platform == '抖音':
            return UrlParser.douyin_video_address(url)
        address = f"{parsed_url.scheme}://{domain}{parsed_url.path}"
        if address.endswith('/'):
            address = address[:-1]
        if platform == "小红书":
            query_params = parse_qs(parsed_url.query)
            xsec_token = query_params.get('xsec_token', [None])[0]
            xsec_source = query_params.get('xsec_source', [None])[0]
            params = []
            if xsec_token:
                params.append(f"xsec_token={xsec_token}")
            if xsec_source:
                params.append(f"xsec_source={xsec_source}")
            if params:
                address = f"{address}?{'&'.join(params)}"
        return address

    @staticmethod
    def get_video_id(url):
        try:
            parsed_url = urlparse(url)
            if (parsed_url.hostname or '').lower() in {'www.douyin.com', 'douyin.com', 'www.iesdouyin.com', 'iesdouyin.com'}:
                return urlparse(UrlParser.douyin_video_address(url)).path.rsplit('/', 1)[-1]
            query_params = parse_qs(parsed_url.query)
            # 尝试从查询参数中获取视频ID
            params_vid = query_params.get('vid', [None])[0]
            if params_vid:
                return params_vid
            params_id = query_params.get('id', [None])[0]
            if params_id:
                return params_id
            # 尝试从URL路径中获取视频ID
            path_segments = parsed_url.path.strip('/').split('/')
            if path_segments:
                video_id = path_segments[-1]
                return video_id
            logger.warning(f'Unable to retrieve video ID from URL: {url}')
            return None
        except Exception as e:
            logger.error(f"An error occurred while extracting video ID: {e}")
            return None

    @staticmethod
    def generate_video_url(platform, video_id):
        # 定义映射表
        url_map = {
            '哔哩哔哩': 'https://www.bilibili.com/video/',
            '抖音': 'https://www.iesdouyin.com/share/video/',
        }
        # 检查platform是否在映射表中
        if platform not in url_map:
            return "Error: 不支持的平台"
        # 拼接URL
        base_url = url_map[platform]
        full_url = base_url + video_id
        return full_url


if __name__ == '__main__':
    # share_url = UrlParser.get_url('0.74 复制打开抖音，看看【珊珊的甜甜圈之小圈的作品】虽然桌拍我已经没问题了，这个月也可以保级了，我也不... https://v.douyin.com/ir94AJyD/ l@c.At qEh:/ 01/19 ')
    # redirect_url = WebFetcher.fetch_redirect_url(share_url)
    # if redirect_url:
    #     print(f'重定向后的链接：{redirect_url}')
    # else:
    #     print('未能获取重定向后的链接')
    video_id1 = UrlParser.get_video_id('https://www.bilibili.com/video/BV1kKWA6uEyr')
    print(video_id1)
