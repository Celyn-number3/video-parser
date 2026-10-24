import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from video_parser.integrations.whisper import cli


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "中文 audio.wav"
        self.source.write_bytes(b"fake audio")
        self.out = self.root / "out"
        self.segments = [SimpleNamespace(start=1.2, end=4.5, text=" 你好，世界。 ")]
        self.model = SimpleNamespace(transcribe=lambda *a, **k: (iter(self.segments), SimpleNamespace(language="zh", duration=5.0)))

    def run_cli(self, *args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return cli.main(list(args))

    def test_memory_diagnostics_include_stack_and_do_not_guess_cuda(self):
        from video_parser.services.transcription import whisper_failure
        cases = [(MemoryError(), 'system_memory'), (RuntimeError('CUDA out of memory'), 'gpu_memory'),
                 (RuntimeError('out of memory'), 'memory_allocation'), (ValueError('invalid audio'), 'operation_failed')]
        for error, code in cases:
            with self.subTest(code=code):
                stream = io.StringIO()
                with contextlib.redirect_stderr(stream):
                    try: raise error
                    except Exception as failure: cli.report_failure(failure)
                log = stream.getvalue()
                self.assertIn('WHISPER_ERROR=' + code, log)
                self.assertIn('Traceback', log)
                self.assertEqual(whisper_failure(log).code, code)
        self.assertEqual(whisper_failure('MemoryError').code, 'system_memory')
        self.assertEqual(whisper_failure('std::bad_alloc').code, 'system_memory')
        self.assertEqual(whisper_failure('CUDA model loaded\nRuntimeError: out of memory').code, 'memory_allocation')
        self.assertEqual(whisper_failure('WHISPER_ERROR=system_memory\nMemoryError\nWHISPER_ERROR=operation_failed\nValueError: invalid audio').code, 'operation_failed')
        from video_parser.services import task_runtime
        failure = whisper_failure('WHISPER_ERROR=system_memory')
        self.assertEqual(task_runtime.classify(failure), ('system_memory', failure.user_message))

    def test_memory_error_does_not_publish_outputs_and_batch_continues(self):
        second = self.root / 'next.wav'; second.write_bytes(b'fake')
        model = SimpleNamespace(transcribe=lambda *a, **k: None)
        with patch.object(model, 'transcribe', side_effect=[MemoryError(), (iter(self.segments), SimpleNamespace(language='zh', duration=5.0))]), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as log:
            code = cli.main(['transcribe', str(self.source), str(second), '--output-dir', str(self.out)], model=model)
        self.assertEqual(code, 1)
        self.assertIn('WHISPER_ERROR=system_memory', log.getvalue())
        self.assertFalse((self.out / '中文 audio.txt').exists())
        self.assertTrue((self.out / 'next.txt').exists())

    def test_render(self):
        text, srt = cli.render(self.segments, True)
        self.assertIn("[00:00:01.200 --> 00:00:04.500] 你好，世界。", text)
        self.assertEqual(srt, "1\n00:00:01,200 --> 00:00:04,500\n你好，世界。")
        self.assertEqual(cli.timestamp(3661.234), "01:01:01,234")
        self.assertEqual(cli.timestamp(59.9996), "00:01:00,000")
        self.assertEqual(cli.render([]), ("", ""))

    @patch("video_parser.integrations.whisper.cli.load_model")
    def test_outputs_and_overwrite(self, load):
        load.return_value = self.model
        args = ["transcribe", str(self.source), "--output-dir", str(self.out), "--format", "txt,srt,json", "--timestamps"]
        self.assertEqual(self.run_cli(*args), 0)
        record = json.loads((self.out / "中文 audio.json").read_text(encoding="utf-8"))
        self.assertEqual(record["segments"][0]["start"], 1.2)
        self.assertEqual(record["text"], "你好，世界。")
        self.assertIn("00:00:01.200", (self.out / "中文 audio.txt").read_text(encoding="utf-8"))
        self.assertEqual(self.run_cli(*args), 1)
        self.assertEqual(load.call_count, 1)
        self.assertEqual(self.run_cli(*args, "--overwrite"), 0)

    @patch("video_parser.integrations.whisper.cli.load_model")
    def test_progress_file_reports_audio_position(self, load):
        load.return_value = self.model
        progress = self.root / "progress.json"
        self.assertEqual(self.run_cli("transcribe", str(self.source), "--output-dir", str(self.out), "--progress-file", str(progress)), 0)
        self.assertEqual(json.loads(progress.read_text(encoding="utf-8")), {"done": 5.0, "total": 5.0})
        self.assertFalse(progress.with_name("progress.json.tmp").exists())

    @patch("video_parser.integrations.whisper.cli.load_model")
    def test_missing_and_colliding_inputs(self, load):
        self.assertEqual(self.run_cli("transcribe", str(self.root / "missing.wav")), 1)
        self.assertEqual(self.run_cli("transcribe", str(self.source), str(self.source), "--output-dir", str(self.out)), 1)
        text_input = self.root / "test.txt"
        text_input.write_text("original")
        self.assertEqual(self.run_cli("transcribe", str(text_input), "--output-dir", str(self.root), "--overwrite"), 1)
        self.assertEqual(text_input.read_text(), "original")
        load.assert_not_called()

    @patch("video_parser.integrations.whisper.cli.load_model")
    def test_batch_loads_once_and_passes_options(self, load):
        second = self.root / "second.wav"
        second.write_bytes(b"fake")
        load.return_value = self.model
        with patch.object(self.model, "transcribe", wraps=self.model.transcribe) as transcribe:
            self.assertEqual(self.run_cli("transcribe", str(self.source), str(second), "--output-dir", str(self.out), "--language", "auto", "--no-vad"), 0)
            self.assertEqual(transcribe.call_count, 2)
            self.assertIsNone(transcribe.call_args.kwargs["language"])
            self.assertFalse(transcribe.call_args.kwargs["vad_filter"])
            self.assertEqual(transcribe.call_args.kwargs["language_detection_segments"], 3)
            self.assertEqual(transcribe.call_args.kwargs["language_detection_threshold"], 0.7)
        load.assert_called_once()

    @patch("video_parser.integrations.whisper.cli.load_model", side_effect=RuntimeError("model unavailable"))
    def test_model_failure(self, load):
        self.assertEqual(self.run_cli("transcribe", str(self.source), "--output-dir", str(self.out)), 1)

    def test_invalid_format(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            cli.main(["transcribe", str(self.source), "--format", "pdf"])
        self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
