"""Versioned JSONL events, separate from human-readable tool output."""
import json
import os
from pathlib import Path


def emit(event, **values):
    location=os.getenv('VIDEO_PARSER_EVENT_FILE')
    if not location:return
    with Path(location).open('a',encoding='utf-8') as stream:
        stream.write(json.dumps({'version':1,'event':event,**values},ensure_ascii=False)+'\n')
        stream.flush()
