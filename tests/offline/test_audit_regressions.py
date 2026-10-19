"""Offline regression tests for the full-project audit; no real DNS, network or user outputs."""
import concurrent.futures
import os
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from video_parser.platforms.web_fetcher import WebFetcher
from video_parser.services import folders, translations


class SubtitleBlockTests(unittest.TestCase):
    def test_vtt_keyword_prefix_identifiers_are_not_metadata(self):
        identifiers = ['NOTEworthy', 'STYLE1', 'REGION_name', 'WEBVTT-extra']
        text = 'WEBVTT\n\n' + '\n\n'.join(
            f'{name}\n00:0{i}.000 --> 00:0{i+1}.000\nCue {i}' for i, name in enumerate(identifiers))
        items, timed = translations.segments(text, '.vtt')
        self.assertTrue(timed)
        self.assertEqual([item['text'] for item in items], [f'Cue {i}' for i in range(4)])

    def test_vtt_actual_metadata_and_cue_settings(self):
        text = ('WEBVTT fixture\n\nNOTE explanation\nignore me\n\nSTYLE\n::cue { color: red; }\n\n'
                'REGION\nid:example\n\ncue\n00:01.100 --> 00:02.200 align:start\nFirst\nline\n\n'
                'NOTE\nignore too\n\ncue2\n00:03.000 --> 00:04.000\nSecond')
        items, _ = translations.segments(text, '.vtt')
        self.assertEqual([item['text'] for item in items], ['First\nline', 'Second'])
        self.assertEqual(items[0]['time'], '00:00:01,100 --> 00:00:02,200')

    def test_srt_identifier_is_never_treated_as_vtt_metadata(self):
        items, _ = translations.segments('NOTEworthy\n00:00:01,000 --> 00:00:02,000\nHello', '.srt')
        self.assertEqual(items[0]['text'], 'Hello')


class PublishFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.destination = self.root / 'picked'
        self.destination.mkdir()
        self.source = self.root / 'original.srt'
        self.source.write_bytes(b'complete original subtitle')
        self.check = patch.object(folders, 'check', return_value=self.destination)
        self.check.start()
        self.addCleanup(self.check.stop)

    def test_failed_copy_leaves_no_final_or_temporary_file_and_retry_reuses_name(self):
        def fail(reader, writer):
            writer.write(reader.read(8))
            raise OSError('simulated full disk')
        with patch.object(folders.shutil, 'copyfileobj', side_effect=fail):
            with self.assertRaises(OSError):
                folders.publish(str(self.destination), self.source, 'subtitle.srt')
        self.assertEqual(list(self.destination.iterdir()), [])
        self.assertEqual(self.source.read_bytes(), b'complete original subtitle')
        self.assertEqual(folders.publish(str(self.destination), self.source, 'subtitle.srt').name, 'subtitle.srt')

    def test_fsync_failure_does_not_publish(self):
        with patch('os.fsync', side_effect=OSError('simulated flush failure')):
            with self.assertRaises(OSError):
                folders.publish(str(self.destination), self.source, 'subtitle.srt')
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_final_name_is_invisible_until_copy_is_complete(self):
        original_copy = folders.shutil.copyfileobj
        def copy(reader, writer):
            self.assertFalse((self.destination / 'subtitle.srt').exists())
            original_copy(reader, writer)
        with patch.object(folders.shutil, 'copyfileobj', side_effect=copy):
            target = folders.publish(str(self.destination), self.source, 'subtitle.srt')
        self.assertEqual(target.read_bytes(), self.source.read_bytes())
        self.assertEqual(list(self.destination.iterdir()), [target])

    def test_failure_preserves_existing_file(self):
        existing = self.destination / 'subtitle.srt'
        existing.write_bytes(b'existing')
        with patch.object(folders.shutil, 'copyfileobj', side_effect=OSError('simulated read failure')):
            with self.assertRaises(OSError):
                folders.publish(str(self.destination), self.source, 'subtitle.srt')
        self.assertEqual(existing.read_bytes(), b'existing')
        self.assertEqual(list(self.destination.iterdir()), [existing])

    def test_missing_source_leaves_no_temporary_file(self):
        with self.assertRaises(FileNotFoundError):
            folders.publish(str(self.destination), self.root / 'missing', 'subtitle.srt')
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_interruption_cleans_only_this_publish(self):
        with patch.object(folders.shutil, 'copyfileobj', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                folders.publish(str(self.destination), self.source, 'subtitle.srt')
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_commit_race_never_overwrites_existing_file(self):
        commit = os.rename if os.name == 'nt' else os.link
        def race(source, target):
            if Path(target).name == 'subtitle.srt':
                Path(target).write_bytes(b'other writer')
                raise FileExistsError('collision at commit')
            return commit(source, target)
        with patch('os.rename' if os.name == 'nt' else 'os.link', side_effect=race):
            target = folders.publish(str(self.destination), self.source, 'subtitle.srt')
        self.assertEqual((self.destination / 'subtitle.srt').read_bytes(), b'other writer')
        self.assertEqual(target.name, 'subtitle (2).srt')
        self.assertEqual(target.read_bytes(), self.source.read_bytes())
        self.assertEqual(len(list(self.destination.iterdir())), 2)

    def test_concurrent_publish_produces_complete_distinct_files(self):
        other = self.root / 'other.srt'
        other.write_bytes(b'other complete text')
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(folders.publish, str(self.destination), p, 'subtitle.srt') for p in [self.source, other]]
            targets = [future.result(timeout=10) for future in futures]
        self.assertEqual(len(set(targets)), 2)
        self.assertEqual({p.read_bytes() for p in targets}, {self.source.read_bytes(), other.read_bytes()})
        self.assertEqual(len(list(self.destination.iterdir())), 2)


class RedirectBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.dns = patch('socket.getaddrinfo', return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))])
        self.dns.start()
        self.addCleanup(self.dns.stop)
        self.request = patch('video_parser.platforms.web_fetcher.requests.get')
        self.get = self.request.start()
        self.addCleanup(self.request.stop)

    @staticmethod
    def response(location=None, status=302):
        return SimpleNamespace(status_code=status, headers={'location': location} if location else {}, raise_for_status=lambda: None)

    def test_unsafe_initial_urls_are_rejected_without_request(self):
        for url in ['http://b23.tv/a', 'https://evil.example/a', 'https://127.0.0.1/a',
                    'https://u:p@b23.tv/a', 'https://b23.tv:8888/a', 'https://b23.tv\\@evil.example/a']:
            with self.subTest(url=url):
                self.get.reset_mock()
                self.assertIsNone(WebFetcher.fetch_redirect_url(url))
                self.get.assert_not_called()

    def test_unsafe_locations_never_get_a_second_request(self):
        for location in ['http://127.0.0.1:8888/v1/models', 'https://10.0.0.1/a', 'https://[::1]/a',
                         'https://evil.example/a', 'file:///private', 'javascript:alert(1)',
                         '//www.bilibili.com.evil.example/a', 'https://u:p@www.bilibili.com/a',
                         'https://www.bilibili.com:8443/a', 'http://www.bilibili.com/a']:
            with self.subTest(location=location):
                self.get.reset_mock()
                self.get.return_value = self.response(location)
                self.assertIsNone(WebFetcher.fetch_redirect_url('https://b23.tv/a'))
                self.assertEqual(self.get.call_count, 1)

    def test_private_or_mixed_dns_is_rejected_before_request(self):
        for addresses in [['127.0.0.1'], ['10.0.0.1'], ['::1'], ['93.184.216.34', '192.168.1.1']]:
            with self.subTest(addresses=addresses), patch('socket.getaddrinfo', return_value=[
                    (socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443)) for ip in addresses]):
                self.get.reset_mock()
                self.get.return_value = self.response('https://www.bilibili.com/video/BV123')
                self.assertIsNone(WebFetcher.fetch_redirect_url('https://b23.tv/a'))
                self.get.assert_not_called()

    def test_dns_failure_is_fail_closed(self):
        with patch('socket.getaddrinfo', side_effect=socket.gaierror('fixture')):
            self.assertIsNone(WebFetcher.fetch_redirect_url('https://b23.tv/a'))
        self.get.assert_not_called()

    def test_relative_and_known_shortlink_chain_preserves_query(self):
        self.get.side_effect = [self.response('/next'), self.response('https://v.douyin.com/id'),
                               self.response('https://www.douyin.com/video/123?share=1')]
        self.assertEqual(WebFetcher.fetch_redirect_url('https://b23.tv/a', preserve_query=True),
                         'https://www.douyin.com/video/123?share=1')
        self.assertEqual([call.args[0] for call in self.get.call_args_list],
                         ['https://b23.tv/a', 'https://b23.tv/next', 'https://v.douyin.com/id'])
        for call in self.get.call_args_list:
            self.assertIs(call.kwargs['allow_redirects'], False)

    def test_official_destination_is_validated_and_returned_without_fetching(self):
        self.get.return_value = self.response('https://www.bilibili.com/video/BV123?p=2')
        self.assertEqual(WebFetcher.fetch_redirect_url('https://b23.tv/a', preserve_query=True),
                         'https://www.bilibili.com/video/BV123?p=2')
        self.assertEqual(self.get.call_count, 1)

    def test_redirect_exhaustion_or_missing_location_returns_none(self):
        self.get.return_value = self.response('/loop')
        self.assertIsNone(WebFetcher.fetch_redirect_url('https://b23.tv/a', max_redirects=2))
        self.assertEqual(self.get.call_count, 2)
        self.get.reset_mock()
        self.get.return_value = self.response(status=302)
        self.assertIsNone(WebFetcher.fetch_redirect_url('https://b23.tv/a'))


if __name__ == '__main__':
    unittest.main()
