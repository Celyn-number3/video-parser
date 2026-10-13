import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Event
import time
import unittest
from unittest.mock import patch
from uuid import uuid4
from video_parser.services import task_runtime as runtime,workflows,storage,library,library_index,subtitles,transcription


def wait(job):
    deadline=time.monotonic()+10
    while runtime.active_id(job.id) and time.monotonic()<deadline:time.sleep(.01)
    if runtime.active_id(job.id):raise AssertionError('Task failed to settle')


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.lane='test-'+uuid4().hex;self.created=[]
    def tearDown(self):
        for job in self.created:runtime.cancel(job.id);wait(job)
        self.temp.cleanup()
    def job(self):
        job=workflows.Job(uuid4().hex,self.lane,'a'*32,'fixture');self.created.append(job);return job
    def submit(self,job,worker,**kw):runtime.submit(self.lane,job,worker,lambda:runtime.save(self.root,job),**kw)
    def test_bounded_fifo_queued_cancel_and_cleanup(self):
        entered=Event();release=Event();cleaned=Event();order=[]
        def worker(job):
            entered.set();release.wait(3);order.append(job.id);job.state='completed'
        first,second,third=self.job(),self.job(),self.job()
        self.submit(first,worker,capacity=1);self.assertTrue(entered.wait(2))
        self.submit(second,worker,capacity=1,cleanup=cleaned.set)
        with self.assertRaises(BlockingIOError):self.submit(third,worker,capacity=1)
        self.assertEqual(runtime.metadata(second)['queue_position'],1)
        runtime.cancel(second.id);release.set();wait(first);wait(second)
        self.assertEqual(order,[first.id]);self.assertEqual(second.state,'cancelled');self.assertTrue(cleaned.is_set())
    def test_actual_process_cancel_preserves_unrelated_process(self):
        launched=Event();owned=[]
        canary=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        def worker(job):
            with subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) as process:
                owned.append(process);launched.set();runtime.communicate(process,90)
            job.state='completed'
        try:
            job=self.job();self.submit(job,worker);self.assertTrue(launched.wait(3));runtime.cancel(job.id);wait(job)
            self.assertEqual(job.state,'cancelled');self.assertIsNotNone(owned[0].poll());self.assertIsNone(canary.poll())
        finally:runtime.stop_process(canary)
    def test_interrupted_restore_never_persists_sensitive_payload(self):
        job=self.job();job.payload={'headers':{'Cookie':'secret-cookie'},'url':'private-signed-url'};runtime.save(self.root,job)
        text=(self.root/(job.id+'.json')).read_text(encoding='utf-8')
        self.assertNotIn('secret-cookie',text);self.assertNotIn('private-signed-url',text)
        restored=runtime.restore(self.root,job.id,workflows.Job)
        self.assertEqual(restored.state,'interrupted');self.assertEqual(restored.payload,{})
        self.assertEqual(json.loads((self.root/(job.id+'.json')).read_text(encoding='utf-8'))['job']['state'],'interrupted')
    def test_disk_full_is_classified_and_sanitized(self):
        def worker(job):raise OSError(errno.ENOSPC,'private-cookie-and-path')
        job=self.job()
        with self.assertLogs('video_parser.services.task_runtime',level='WARNING') as logs:
            self.submit(job,worker);wait(job)
        self.assertEqual(job.error_code,'disk_full');self.assertNotIn('private-cookie',job.message)
        self.assertNotIn('private-cookie',' '.join(logs.output));self.assertIn(job.id,' '.join(logs.output))
    def test_completed_only_after_terminal_journal(self):
        ready=Event();release=Event();job=self.job()
        def persist():
            if job.state=='completed':ready.set();release.wait(3)
            runtime.save(self.root,job)
        def worker(job):runtime.progress('validating','检查');job.state='completed'
        runtime.submit(self.lane,job,worker,persist)
        self.assertTrue(ready.wait(2));self.assertEqual(runtime.public_state(job),'running')
        release.set();wait(job);self.assertEqual(runtime.public_state(job),'completed')
        self.assertIn('validating',job.stage_timings)
    def test_atomic_journal_failure_keeps_previous_record(self):
        job=self.job();runtime.save(self.root,job);path=self.root/(job.id+'.json');before=path.read_bytes()
        job.message='new'
        with patch.object(runtime.os,'replace',side_effect=OSError(errno.ENOSPC,'full')):
            with self.assertRaises(OSError):runtime.save(self.root,job)
        self.assertEqual(before,path.read_bytes());self.assertFalse(list(self.root.glob('*.tmp')))
    def test_graceful_shutdown_marks_interrupted_and_rejects_new_work(self):
        entered=Event();job=self.job()
        def worker(job):
            entered.set()
            while True:runtime.checkpoint();time.sleep(.01)
        try:
            self.submit(job,worker);self.assertTrue(entered.wait(2));self.assertTrue(runtime.shutdown(timeout=3))
            self.assertEqual(job.state,'interrupted');self.assertEqual(job.error_code,'interrupted')
            with self.assertRaises(BlockingIOError):self.submit(self.job(),worker)
        finally:runtime.startup()

    def test_terminal_object_cache_is_bounded_without_removing_journals(self):
        jobs={}
        for index in range(120):
            job=workflows.Job(uuid4().hex,self.lane,'a'*32,'fixture',state='completed',created=index)
            jobs[job.id]=job
        keep=next(iter(jobs));runtime.save(self.root,jobs[keep]);runtime.trim_memory(jobs,keep=keep)
        self.assertEqual(len(jobs),100);self.assertIn(keep,jobs);self.assertTrue((self.root/(keep+'.json')).is_file())

    def test_unknown_or_malformed_records_not_restored(self):
        with self.assertRaises(KeyError):runtime.restore(self.root,'../secret',workflows.Job)
        identifier=uuid4().hex;(self.root/(identifier+'.json')).write_text('{broken')
        with self.assertRaises(KeyError):runtime.restore(self.root,identifier,workflows.Job)
    def test_queued_cancel_does_not_delete_original_input(self):
        original=self.root/'original.wav';original.write_bytes(b'original')
        job=transcription.Job(uuid4().hex,original,'fixture','auto',owned_input=True)
        with patch.object(transcription,'UPLOAD_ROOT',self.root/'uploads'):transcription.cleanup_input(job)
        self.assertEqual(original.read_bytes(),b'original')


class StorageAndIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.cache=self.root/'cache';self.cache.mkdir()
        self.patches=[patch.object(storage,'roots',return_value={'workflow_scratch':self.cache}),
                      patch.object(subtitles,'download_root',return_value=self.root/'reuse'),patch.object(library,'LIBRARY_ROOT',self.root/'library')]
        for item in self.patches:item.start()
    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.temp.cleanup()
    def scratch(self):
        identifier=uuid4().hex;path=self.cache/identifier;runtime.own_directory(path,identifier)
        runtime.atomic(path/'.task-owner.json',{'owner':'video-parser','id':identifier,'created':time.time()-2*86400})
        (path/'scratch.txt').write_text('derived');return path
    def test_preview_then_confirm_only_owned_old_scratch(self):
        path=self.scratch();unknown=self.cache/'unknown';unknown.mkdir();(unknown/'original').write_text('keep')
        model=self.root/'models';model.mkdir();(model/'model.bin').write_text('keep')
        preview=storage.preview();self.assertTrue(path.exists());self.assertEqual(len(preview['entries']),1)
        self.assertEqual(storage.clean(preview['plan_id'])['removed'],[path.name])
        self.assertTrue((model/'model.bin').exists());self.assertTrue((unknown/'original').exists())
        with self.assertRaises(ValueError):storage.clean(preview['plan_id'])
    def test_changed_cache_skipped_and_new_cache_retained(self):
        path=self.scratch();fresh=self.cache/uuid4().hex;runtime.own_directory(fresh,fresh.name)
        preview=storage.preview();(path/'scratch.txt').write_text('changed')
        self.assertEqual(storage.clean(preview['plan_id'])['skipped'],[path.name]);self.assertTrue(fresh.exists())
    def test_active_task_blocks_cleanup(self):
        self.scratch();preview=storage.preview()
        with patch.object(runtime,'_controls',{'fixture':{}}):
            with self.assertRaises(BlockingIOError):storage.clean(preview['plan_id'])
    def test_index_rebuild_and_warm_lookup(self):
        projects=[library.ensure({'platform':'local','video_id':'fixture'+str(i),'title':'fixture'+str(i)}) for i in range(12)]
        identifier=projects[8]['id'];library.get(identifier)
        with patch.object(library,'load',wraps=library.load) as loader:
            self.assertEqual(library.get(identifier)['id'],identifier);self.assertEqual(loader.call_count,1)
        index=library.LIBRARY_ROOT/'.project-index.json';index.write_text('broken');library_index.invalidate(library.LIBRARY_ROOT)
        self.assertEqual(library.get(identifier)['id'],identifier)
    def test_same_size_same_mtime_tampering_is_still_detected(self):
        project=library.ensure({'platform':'local','video_id':'fixture','title':'fixture'})
        source=self.root/'source.txt';source.write_text('original');relative=library.import_file(project['id'],source,'transcriptions/fixture.txt','transcription')
        path=library.resource(project['id'],relative);stat=path.stat();path.write_text('tampered');os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        with self.assertRaises(ValueError):library.resource(project['id'],relative)
    def test_structured_target_requires_matching_identity(self):
        job=subtitles.Job(uuid4().hex,'https://www.bilibili.com/video/BV1rH4y1N7BW',[1],self.cache/'job')
        events={'events':[{'event':'target','title':'fixture','bvid':'BV1rH4y1N7BW','total':3,'single':False}]}
        self.assertEqual(subtitles.targets(job,events)[2:4],(3,[1]))
        events['events'][0]['bvid']='BV1Ju4y1o7q8'
        with self.assertRaises(RuntimeError):subtitles.targets(job,events)
    def test_retry_only_uncompleted_selected_episodes(self):
        job=subtitles.Job(uuid4().hex,'https://www.bilibili.com/video/BV1rH4y1N7BW',[1,2,3],self.cache/'job',state='partial')
        job.results=[{'episode':1,'status':'existing'},{'episode':2,'status':'failed'}]
        with patch.object(subtitles,'get',return_value=job),patch.object(subtitles,'start',return_value={'id':'next'}) as start:
            subtitles.retry_failed(job.id);start.assert_called_once_with(job.url,'custom','2,3')

if __name__=='__main__':unittest.main()
