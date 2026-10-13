import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,Mock
from video_parser.integrations.whisper import session
from video_parser.services import transcription,whisper_pool


class WhisperBatchTests(unittest.TestCase):
    def test_session_loads_one_model_and_isolates_failed_file(self):
        lines=''.join(json.dumps({'id':str(i),'arguments':['transcribe','fixture.wav']})+'\n' for i in range(3))
        output=io.StringIO();model=object()
        with patch.object(session.sys,'stdin',io.StringIO(lines)),patch.object(session.sys,'stdout',output),\
             patch.object(session.cli,'plan_outputs'),patch.object(session.cli,'load_model',return_value=model) as load,\
             patch.object(session.cli,'main',side_effect=[0,RuntimeError('bad fixture'),0]) as main:
            self.assertEqual(session.serve(1),0)
        records=[json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([row['returncode'] for row in records],[0,1,0]);load.assert_called_once()
        self.assertTrue(all(call.kwargs['model'] is model for call in main.call_args_list))
        self.assertEqual([records[0]['model_reused'],records[2]['model_reused']],[False,True])
        self.assertEqual(records[2]['model_load_count'],1)
    def test_batch_skips_missing_file_and_always_releases_worker(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            def transcribe(source,*args,**kwargs):
                if source=='missing.wav':raise FileNotFoundError('private path')
                self.assertTrue(kwargs['reuse_model']);return {'text':'fixture','files':{},'worker':{'model_load_count':1}}
            with patch.object(transcription,'transcribe',side_effect=transcribe) as call,patch.object(whisper_pool,'close') as close:
                result=transcription.transcribe_batch(['one.wav','missing.wav','two.wav'],output_dir=root)
            self.assertEqual(result['state'],'partial');self.assertEqual(result['completed'],2);self.assertEqual(result['failed'],1)
            self.assertEqual(call.call_count,3);close.assert_called_once()
            self.assertEqual(len(list(root.glob('batch-*.json'))),1)
    def test_batch_never_overwrites_existing_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);sentinel=root/'batch-old.json';sentinel.write_text('original')
            with patch.object(transcription,'transcribe',return_value={'text':'ok'}),patch.object(whisper_pool,'close'):
                transcription.transcribe_batch(['file.wav'],output_dir=root)
            self.assertEqual(sentinel.read_text(),'original');self.assertEqual(len(list(root.glob('batch-*.json'))),2)

if __name__=='__main__':unittest.main()
