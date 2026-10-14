"""Offline regressions: single-video identity, real measurements, safe hooks and cancellation."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from video_parser.platforms.youtube_links import canonical_url
from video_parser.platforms.downloaders.youtube_downloader import YoutubeDownloader, YoutubeAccessError
from video_parser.platforms import youtube
from video_parser.services import library, videos, task_runtime as runtime, workflows
from video_parser.services.download_progress import TransferProgress

ID = 'eRsGyueVLvQ'
URL = 'https://www.youtube.com/watch?v=' + ID


class YoutubeIdentityTests(unittest.TestCase):
    def test_variants_share_canonical_identity(self):
        for url in [URL+'&list=ignore&t=20', 'https://youtu.be/'+ID+'?si=ignore',
                    'https://m.youtube.com/shorts/'+ID, 'https://youtube.com/embed/'+ID,
                    'https://www.youtube.com/live/'+ID]:
            with self.subTest(url=url):
                self.assertEqual(videos.resolve_url(url), (URL, 'YouTube'))
                self.assertEqual(canonical_url(url), URL)
                self.assertEqual(library.identity({'platform':'YouTube','video_id':ID,'source_url':url})['key'], 'youtube:'+ID)
                self.assertEqual(library.identity({'platform':'YouTube','video_id':ID,'source_url':url})['source_url'], URL)
    def test_playlists_spoofed_hosts_auth_and_ports_rejected(self):
        for url in ['https://www.youtube.com/playlist?list=x','https://www.youtube.com/watch',
                    'https://www.youtube.com/watch?v='+ID+'&v=other123456',
                    'https://www.youtube.com.evil.example/watch?v='+ID,
                    'https://user:password@www.youtube.com/watch?v='+ID,
                    'https://www.youtube.com:8123/watch?v='+ID]:
            with self.subTest(url=url), self.assertRaises(ValueError):canonical_url(url)
    def test_mismatched_archive_id_rejected(self):
        with self.assertRaises(ValueError):library.identity({'platform':'YouTube','video_id':'aqz-KE-bpKQ','source_url':URL})
    def test_projects_are_distinct_and_resume_source_retains_id(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(library,'LIBRARY_ROOT',Path(temp)):
            a=library.ensure({'platform':'YouTube','video_id':ID,'source_url':URL,'title':'one'})
            b=library.ensure({'platform':'YouTube','video_id':'aqz-KE-bpKQ','source_url':'https://youtu.be/aqz-KE-bpKQ','title':'two'})
            self.assertNotEqual(a['id'],b['id'])
            self.assertEqual(library.get(a['id'])['source_url'],URL)
    def test_metadata_queried_once_without_signed_urls(self):
        data={'id':ID,'title':'Sintel','duration':888,'thumbnail':'https://example.test/cover.jpg','url':'secret-signed-url'}
        with patch('subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(data))) as run:
            downloader=YoutubeDownloader(URL)
            self.assertEqual(downloader.get_title_content(),'Sintel')
            self.assertEqual(downloader.get_cover_photo_url(),data['thumbnail'])
            self.assertEqual(downloader.metadata()['duration'],888)
            self.assertNotIn('url',downloader.metadata())
            self.assertEqual(run.call_count,1)
            self.assertIn('--ignore-config',run.call_args.args[0])
    def test_metadata_failure_is_sanitized(self):
        with patch('subprocess.run',return_value=SimpleNamespace(returncode=1,stdout='secret-cookie signed-url')):
            with self.assertRaises(YoutubeAccessError) as raised:YoutubeDownloader(URL).metadata()
            self.assertNotIn('secret',str(raised.exception))


class ProgressTests(unittest.TestCase):
    def test_speed_uses_current_transfer_not_task_elapsed(self):
        with patch('video_parser.services.download_progress.time.monotonic',side_effect=[100,102]), patch.object(runtime,'progress') as progress:
            TransferProgress(2,2).report(200,1000)
            values=progress.call_args.kwargs
            self.assertEqual(values['speed_bytes_per_second'],100)
            self.assertEqual(values['eta_seconds'],8)
            self.assertEqual((values['track'],values['tracks']),(2,2))
    def test_unknown_size_no_eta(self):
        with patch('video_parser.services.download_progress.time.monotonic',side_effect=[0,2]), patch.object(runtime,'progress') as progress:
            TransferProgress().report(200)
            self.assertNotIn('eta_seconds',progress.call_args.kwargs)
            self.assertEqual(progress.call_args.kwargs['total_bytes'],0)
    def test_early_sample_no_misleading_rate(self):
        with patch('video_parser.services.download_progress.time.monotonic',side_effect=[0,.1]), patch.object(runtime,'progress') as progress:
            TransferProgress().report(200,1000)
            self.assertNotIn('speed_bytes_per_second',progress.call_args.kwargs)
    def test_finished_transfer_forces_emit_without_eta(self):
        with patch('video_parser.services.download_progress.time.monotonic',side_effect=[0,2]), patch.object(runtime,'progress') as progress:
            TransferProgress().report(200,200,finished=True)
            self.assertTrue(progress.call_args.kwargs['force'])
            self.assertNotIn('eta_seconds',progress.call_args.kwargs)
    def test_runtime_filters_nonfinite_and_clears_phase_metrics(self):
        from threading import Event
        job=workflows.Job('a'*32,'video','b'*32,'fixture')
        control={'job':job,'cancel':Event(),'phase_start':0,'persist':lambda:None}
        token=runtime._context.set(control)
        try:
            runtime.progress('downloading',bytes=100,total_bytes=1000,speed_bytes_per_second=50,eta_seconds=18,secret_url='secret',bad=float('inf'))
            self.assertEqual(job.progress['eta_seconds'],18)
            runtime.progress('downloading',bytes=200,total_bytes=float('nan'),speed_bytes_per_second=-1)
            self.assertEqual(job.progress,{'bytes':200})
            runtime.progress('merging','merge')
            self.assertEqual(job.progress,{})
        finally:runtime._context.reset(token)
    def test_cancelled_transfer_does_not_try_backup(self):
        response=SimpleNamespace(headers={'Content-Length':'4'},raise_for_status=lambda:None,iter_content=lambda **kw:iter([b'data']))
        class Context:
            def __enter__(self):return response
            def __exit__(self,*args):pass
        with tempfile.TemporaryDirectory() as temp, patch('requests.get',return_value=Context()) as get, patch.object(runtime,'progress',side_effect=runtime.Cancelled('cancel')):
            with self.assertRaises(runtime.Cancelled):videos.download_resource(['https://one','https://two'],Path(temp)/'file',{})
            self.assertEqual(get.call_count,1)
    def test_hook_tracks_estimate_and_merge_phase(self):
        options={}; events=[]
        class FakeYDL:
            def __init__(self,opts):options.update(opts)
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def download(self,urls):
                hook=options['progress_hooks'][0]
                hook({'status':'downloading','filename':'v','downloaded_bytes':100,'total_bytes_estimate':1000,'speed':50,'eta':18})
                hook({'status':'finished','filename':'v','downloaded_bytes':1000,'total_bytes':1000})
                hook({'status':'downloading','filename':'a','downloaded_bytes':70000,'total_bytes':100000,'speed':5000,'eta':6,'elapsed':2})
                options['postprocessor_hooks'][0]({'status':'started'})
                Path(options['outtmpl']).write_bytes(b'fixture')
        with tempfile.TemporaryDirectory() as temp, patch('yt_dlp.YoutubeDL',FakeYDL), patch.object(runtime,'progress') as phases:
            youtube.download_youtube(URL,Path(temp)/'output.mp4',lambda done,total,**values:events.append((done,total,values)))
            self.assertEqual(events[0][2]['estimated_total'],1)
            self.assertNotIn('eta_seconds',events[0][2])
            self.assertNotIn('speed_bytes_per_second',events[0][2])
            self.assertEqual(events[2][2]['track'],2)
            self.assertEqual(events[2][2]['speed_bytes_per_second'],5000)
            self.assertEqual(events[2][2]['eta_seconds'],6)
            self.assertTrue(events[1][2]['finished'])
            self.assertIn('merging',[call.args[0] for call in phases.call_args_list])
    def test_youtube_errors_do_not_expose_signed_urls(self):
        from yt_dlp.utils import DownloadError
        with tempfile.TemporaryDirectory() as temp, patch('yt_dlp.YoutubeDL',side_effect=DownloadError('secret_signed_url')):
            with self.assertRaises(RuntimeError) as raised:youtube.download_youtube(URL,Path(temp)/'output.mp4')
            self.assertNotIn('secret',str(raised.exception))


if __name__ == '__main__':unittest.main()
