"""Read-only archive audit endpoints. There is deliberately no cleanup action here."""
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from video_parser.services import archive_health
from video_parser.web.security import local_request

router = APIRouter(prefix='/api/workspace', dependencies=[Depends(local_request)])


def report():
    try:
        return archive_health.inspect()
    except OSError:
        raise HTTPException(503, '无法读取归档目录，请检查磁盘与目录权限。') from None


@router.get('/archive/health')
def health():
    return report()


@router.get('/archive/health/export')
def export_health(format: Literal['md'] = 'md'):
    content, name = archive_health.export_markdown(report())
    return Response(content.encode('utf-8'), media_type='text/markdown; charset=utf-8', headers={
        'Content-Disposition': f"attachment; filename=\"archive-health.{format}\"; filename*=UTF-8''{quote(name + '.' + format)}",
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
