"""Compatibility ASGI entrypoint; implementation lives in video_parser.web.app."""
from video_parser.web.app import app

if __name__ == '__main__':
    import uvicorn
    uvicorn.run('video_parser.web.app:app', host='127.0.0.1', port=15001, proxy_headers=False)
