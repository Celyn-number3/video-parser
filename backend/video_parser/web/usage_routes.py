"""Aggregated model usage for the local workspace; read-only and local to this machine."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from video_parser.services import usage_report
from video_parser.web.security import local_request

router = APIRouter(prefix='/api/workspace', dependencies=[Depends(local_request)])


@router.get('/usage')
def usage(days: Annotated[int, Query(ge=0, le=3650)] = 30):
    """0 means all time. Only usage already saved with archived records is counted."""
    try:
        return usage_report.collect(days)
    except (OSError, ValueError, KeyError):
        raise HTTPException(503, '无法读取归档中的用量记录，请检查磁盘与目录权限。') from None
