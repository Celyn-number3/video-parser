"""Proofread copies: synthetic subtitles only; the source file must never be rewritten."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from video_parser.services import library, subtitle_edits, subtitle_versions, translations
from video_parser.web.app import app

SRT = ('1\n00:00:02,000 --> 00:00:04,500\n<i>Transformer</i> 架构\n\n'
       '2\n00:01:00,000 --> 00:01:05,000\n注意力机制 attention\n')
VTT = ('WEBVTT\n\nNOTE 这是说明，不是字幕\n\n'
       '00:01.000 --> 00:03.500\n梯度下降 gradient descent\n\n'
       '00:05.000 --> 00:06.000\n学习率 learning rate\n')


class CorrectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.addCleanup(patch.stopall)
        patch.object(library, 'LIBRARY_ROOT', self.root / 'library').start()
        self.project = library.ensure({'platform': 'bilibili', 'video_id': 'BV1TaqYBcEJc', 'title': '合成课程',
                                       'source_url': 'https://www.bilibili.com/video/BV1TaqYBcEJc?p=1'})
        self.pid = self.project['id']
        self.client = TestClient(app, base_url='http://127.0.0.1:15001', client=('127.0.0.1', 12345))

    def add(self, text, kind='subtitle', relative='subtitles/fixture.srt', **details):
        source = self.root / ('fixture' + Path(relative).suffix)
        source.write_text(text, encoding='utf-8')
        return library.import_file(self.pid, source, relative, kind, details)

    def test_save_publishes_readable_copy_and_leaves_source_untouched(self):
        source = self.add(SRT, language='zh')
        before = library.resource(self.pid, source).read_bytes()
        saved = subtitle_edits.save(self.pid, source, [{'time': 2, 'text': 'Transformer 架构（编码器）'}])
        self.assertEqual(saved['filename'], '合成课程-中文-校对.srt')
        self.assertEqual(saved['resource'], 'subtitles/合成课程-中文-校对.srt')
        self.assertEqual((saved['edited'], saved['cues']), (1, 2))
        self.assertEqual(library.resource(self.pid, source).read_bytes(), before)
        copy = library.resource(self.pid, saved['resource']).read_text(encoding='utf-8')
        # Only the edited cue changes: timings, numbering and untouched text stay verbatim.
        self.assertEqual(copy, '1\n00:00:02,000 --> 00:00:04,500\nTransformer 架构（编码器）\n\n'
                               '2\n00:01:00,000 --> 00:01:05,000\n注意力机制 attention\n')
        info = library.get(self.pid)['resources'][saved['resource']]
        self.assertEqual((info['kind'], info['language'], info['source_resource']), ('correction', 'zh', source))
        self.assertEqual(info['source_sha256'], library.get(self.pid)['resources'][source]['sha256'])
        self.assertEqual(info['download_name'], '合成课程-中文-校对.srt')
        record = next(row for row in library.subtitle_records(library.get(self.pid)) if row['resource'] == saved['resource'])
        self.assertEqual(record['origin'], 'corrected')

    def test_untouched_tagged_cues_are_not_renormalized(self):
        source = self.add(SRT, language='zh')
        saved = subtitle_edits.save(self.pid, source, [{'time': 60, 'text': '注意力机制 Attention'}])
        copy = library.resource(self.pid, saved['resource']).read_text(encoding='utf-8')
        self.assertIn('<i>Transformer</i> 架构', copy)
        self.assertIn('注意力机制 Attention', copy)

    def test_second_save_creates_another_version_instead_of_overwriting(self):
        source = self.add(SRT, language='zh')
        first = subtitle_edits.save(self.pid, source, [{'time': 2, 'text': 'Transformer 架构 A'}])
        first_bytes = library.resource(self.pid, first['resource']).read_bytes()
        second = subtitle_edits.save(self.pid, source, [{'time': 2, 'text': 'Transformer 架构 B'}])
        self.assertNotEqual(first['resource'], second['resource'])
        self.assertEqual(library.resource(self.pid, first['resource']).read_bytes(), first_bytes)
        self.assertIn('架构 B', library.resource(self.pid, second['resource']).read_text(encoding='utf-8'))
        self.assertEqual(second['filename'], '合成课程-中文-校对.srt')
        project = library.get(self.pid)
        rows = subtitle_versions.annotate(project, library.subtitle_records(project) + library.translation_records(project))
        self.assertEqual(len({row['version_id'] for row in rows if row['kind'] == 'correction'}), 2)

    def test_correction_is_not_counted_as_archived_platform_subtitle(self):
        self.add(SRT, kind='transcription', language='zh')
        self.assertEqual(library.subtitle_inventory('BV1TaqYBcEJc')['archived'], [])
        source = 'subtitles/fixture.srt'
        subtitle_edits.save(self.pid, source, [{'time': 2, 'text': 'Transformer 架构（编码器）'}])
        self.assertEqual(library.subtitle_inventory('BV1TaqYBcEJc')['archived'], [])

    def test_webvtt_source_is_published_as_srt_without_metadata_blocks(self):
        source = self.add(VTT, language='en', relative='subtitles/fixture.vtt')
        saved = subtitle_edits.save(self.pid, source, [{'time': 1, 'text': '梯度下降 Gradient Descent'}])
        copy = library.resource(self.pid, saved['resource']).read_text(encoding='utf-8')
        self.assertEqual(copy, '1\n00:00:01,000 --> 00:00:03,500\n梯度下降 Gradient Descent\n\n'
                               '2\n00:00:05,000 --> 00:00:06,000\n学习率 learning rate\n')
        self.assertEqual(saved['filename'], '合成课程-英文-校对.srt')

    def test_invalid_edits_are_rejected_without_publishing(self):
        source = self.add(SRT, language='zh')
        cases = [
            [{'time': 99, 'text': 'x'}],                        # cue that is not in this file
            [{'time': 2, 'text': '   '}],                        # empty cue
            [{'time': 2, 'text': 'a --> b'}],                    # injected time line
            [{'time': 2, 'text': 'x'}, {'time': 2, 'text': 'y'}],  # duplicate target
            [{'time': 2, 'text': '<i>Transformer</i> 架构'}],    # identical to the source
            [{'time': float('nan'), 'text': 'x'}],
        ]
        for edits in cases:
            with self.assertRaises(ValueError, msg=str(edits)):
                subtitle_edits.save(self.pid, source, edits)
        with self.assertRaises(ValueError):
            subtitle_edits.save(self.pid, 'subtitles/missing.srt', [{'time': 2, 'text': 'x'}])
        video = self.add('fake', kind='video', relative='videos/fixture.mp4')
        with self.assertRaises(ValueError):
            subtitle_edits.save(self.pid, video, [{'time': 2, 'text': 'x'}])
        self.assertEqual(sorted(library.get(self.pid)['resources']), sorted([source, video]))

    def test_corrected_copy_is_usable_as_translation_source(self):
        source = self.add(SRT, language='zh')
        saved = subtitle_edits.save(self.pid, source, [{'time': 2, 'text': 'Transformer 架构（编码器）'}])
        _, text = translations.read_input({'project_id': self.pid, 'resource': saved['resource']})
        self.assertIn('Transformer 架构（编码器）', text)
        translated = self.add('1\n00:00:02,000 --> 00:00:04,500\nTransformer architecture\n', kind='translation',
                              relative='subtitles/fixture-en.srt', language='en',
                              source_resource=saved['resource'], source_sha256=library.get(self.pid)['resources'][saved['resource']]['sha256'])
        row = next(item for item in library.translation_records(library.get(self.pid)) if item['resource'] == translated)
        self.assertEqual(row['source_origin'], 'corrected')

    def test_http_contract_and_error_mapping(self):
        source = self.add(SRT, language='zh')
        url = f'/api/workspace/projects/{self.pid}/subtitle-edits'
        ok = self.client.post(url, json={'resource': source, 'edits': [{'time': 2, 'text': 'Transformer 架构（编码器）'}]})
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(ok.json()['filename'], '合成课程-中文-校对.srt')
        self.assertEqual(self.client.post(url, json={'resource': source, 'edits': []}).status_code, 422)
        self.assertEqual(self.client.post(url, json={'resource': source, 'edits': [{'time': 2, 'text': ''}]}).status_code, 422)
        self.assertEqual(self.client.post(url, json={'resource': source, 'edits': [{'time': 99, 'text': 'x'}]}).status_code, 400)
        self.assertEqual(self.client.post(url, json={'resource': '../../secret', 'edits': [{'time': 2, 'text': 'x'}]}).status_code, 400)
        self.assertEqual(self.client.post('/api/workspace/projects/' + '0' * 32 + '/subtitle-edits',
                                          json={'resource': source, 'edits': [{'time': 2, 'text': 'x'}]}).status_code, 404)
        cues = self.client.get(f'/api/workspace/projects/{self.pid}/subtitle-cues',
                               params={'resource': ok.json()['resource']})
        self.assertEqual(cues.status_code, 200, cues.text)
        self.assertEqual(cues.json()['cues'][0]['text'], 'Transformer 架构（编码器）')
        self.assertIn('人工校对', next(row['label'] for row in cues.json()['sources'] if row['resource'] == ok.json()['resource']))


if __name__ == '__main__': unittest.main()
