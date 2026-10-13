from pathlib import Path
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest

CHECKER = Path(__file__).resolve().parents[2] / 'src/video_parser/integrations/bilibili/checker.py'
spec = importlib.util.spec_from_file_location('subtitle_checker', CHECKER)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class SubtitleCheckerTests(unittest.TestCase):
    def test_cli_validates_triplet_without_modifying_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / '_json/P01.json', root / '_srt/P01.srt', root / '_md/P01.md']
            content = [json.dumps({'body': [{'from': 0, 'to': 1, 'content': 'fixture'}]}),
                       '1\n00:00:00,000 --> 00:00:01,000\nfixture\n', 'fixture\n']
            for p, text in zip(paths, content):
                p.parent.mkdir()
                p.write_text(text, encoding='utf-8')
            before = [p.read_bytes() for p in paths]
            result = subprocess.run([sys.executable, str(CHECKER), str(paths[0])],
                                    capture_output=True, text=True, check=True)
            self.assertTrue(json.loads(result.stdout)['ok'])
            self.assertEqual([p.read_bytes() for p in paths], before)
            paths[1].unlink()
            self.assertFalse(checker.check(paths[0])['ok'])
            result = subprocess.run([sys.executable, str(CHECKER), str(paths[0])],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)

    def test_invalid_json_missing_path_and_arguments_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / '_json/P01.json'
            p.parent.mkdir()
            for text in ['{', '{"body": []}', '{"body": [{"from": -1, "to": 2, "content": "fixture"}]}']:
                p.write_text(text, encoding='utf-8')
                self.assertFalse(checker.check(p)['ok'])
            self.assertFalse(checker.check(p.parent / 'missing.json')['ok'])
            result = subprocess.run([sys.executable, str(CHECKER)], capture_output=True)
            self.assertEqual(result.returncode, 2)


if __name__ == '__main__':
    unittest.main()
