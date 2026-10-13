"""Synthetic lookup/verification baseline. Never reads the user's library or media."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import statistics
import tempfile
import time
from unittest.mock import patch
from video_parser.services import library,library_index


def timed(action,repeats):
    values=[]
    for _ in range(repeats):
        started=time.perf_counter();action();values.append((time.perf_counter()-started)*1000)
    return {'median_ms':round(statistics.median(values),3),'min_ms':round(min(values),3),'max_ms':round(max(values),3)}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--projects',type=int,default=300);parser.add_argument('--repeats',type=int,default=7)
    args=parser.parse_args()
    if not 10<=args.projects<=5000 or not 3<=args.repeats<=30:raise ValueError('Fixture limits')
    with tempfile.TemporaryDirectory(prefix='video-parser-index-benchmark-') as temporary:
        root=Path(temporary)/'library';ids=[]
        for number in range(args.projects):
            identifier=hashlib.sha256(str(number).encode()).hexdigest()[:32];ids.append(identifier)
            path=root/'local'/f'fixture-{number:05d}'/'project.json';path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'schema_version':1,'id':identifier,'resources':{},'title':'synthetic'}))
        target=ids[args.projects//2]
        with patch.object(library,'LIBRARY_ROOT',root):
            def baseline():
                for path in library.manifests():
                    record=library.load(path)
                    if record['id']==target:return record
                raise KeyError(target)
            baseline();before=timed(baseline,args.repeats)
            library_index.invalidate(root);cold=timed(lambda:library.get(target),1)
            after=timed(lambda:library.get(target),args.repeats)
            sample=Path(temporary)/'synthetic.bin';sample.write_bytes(b'x'*(16*1024*1024))
            verify=timed(lambda:library.digest(sample),args.repeats)
    print(json.dumps({'timestamp':datetime.now(timezone.utc).isoformat(),'synthetic_projects':args.projects,'repeats':args.repeats,
        'target':'middle project in sorted fixture','old_manifest_scan':before,'index_cold_rebuild':cold,'index_warm_lookup':after,
        'lookup_speedup':round(before['median_ms']/max(after['median_ms'],.001),2),'full_sha256_16MiB':verify,
        'scope':'Synthetic directory lookup only, not end-to-end download/transcription speed. Full resource SHA-256 remains enabled; size/mtime are not treated as integrity proof.'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
