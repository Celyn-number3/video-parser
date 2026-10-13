"""Local-only HTTP request boundary; kept independent of business operations."""
from urllib.parse import urlsplit
from fastapi import HTTPException, Request, Response

FILE_HEADERS = {'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
                'Referrer-Policy': 'no-referrer'}


def local_request(request: Request, response: Response):
    """Loopback binding alone does not stop a hostile page or DNS rebinding."""
    try:
        host = urlsplit('//' + request.headers.get('host', ''))
        valid_host = host.hostname in {'127.0.0.1', 'localhost', '::1'} and not host.username and not host.password
        host.port  # Validate malformed ports before comparing origins.
    except ValueError:
        valid_host = False
    origin = request.headers.get('origin')
    expected = 'http://' + request.headers.get('host', '')
    if (not request.client or request.client.host not in {'127.0.0.1', '::1'} or not valid_host
            or (origin and origin != expected) or request.headers.get('sec-fetch-site') == 'cross-site'):
        raise HTTPException(403, '工作台接口仅允许本机同源访问。')
    expected_type = 'application/octet-stream' if request.url.path == '/api/workspace/transcriptions/upload' else 'application/json'
    if request.method == 'POST' and request.headers.get('content-type', '').split(';')[0] != expected_type:
        raise HTTPException(415, '上传音视频请使用二进制请求，其他接口请使用 JSON 请求。')
    response.headers.update(FILE_HEADERS)
