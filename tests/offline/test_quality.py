"""Offline quality selection and persistent version regressions."""
from video_parser import cli as cli_entry
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from video_parser.services import videos as cli
from video_parser.services import library as library
class QualityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.addCleanup(patch.stopall)
        patch.object(library,'LIBRARY_ROOT',self.root/'library').start()
        self.video=[
            {'id':80,'width':1920,'height':1080,'codecs':'hev1','bandwidth':200,'baseUrl':'https://fixture/hevc'},
            {'id':80,'width':1920,'height':1080,'codecs':'avc1.640028','bandwidth':100,'baseUrl':'https://fixture/1080','backupUrl':['https://fixture/backup']},
            {'id':64,'width':1280,'height':720,'codecs':'avc1.64001f','bandwidth':50,'baseUrl':'https://fixture/720'},
        ]
        self.fake=type('Downloader',(),{
            'headers':{},'data':json.dumps({'data':{'dash':{'duration':2,'video':self.video,'audio':[{'bandwidth':10,'baseUrl':'https://fixture/audio'}]}}}),
            'get_title_content':lambda self:'测试','get_real_video_url':lambda self:'https://fixture/1080',
            'get_cover_photo_url':lambda self:'https://fixture/cover'})()
        patch('video_parser.platforms.factory.DownloaderFactory.create_downloader',return_value=self.fake).start()

    def parsed(self):return cli.parse_link('https://www.bilibili.com/video/BV1TaqYBcEJc')

    def test_real_options_compatible_codec_and_selection(self):
        parsed=self.parsed()
        qualities=cli.quality_options(parsed)
        self.assertEqual([item['height'] for item in qualities],[1080,720])
        self.assertEqual(parsed.video_urls,['https://fixture/1080','https://fixture/backup'])
        selected=cli.select_quality(parsed,'720p')
        self.assertEqual(selected.video_urls,['https://fixture/720'])
        self.assertEqual(selected.audio_urls,['https://fixture/audio'])
        self.assertEqual(selected.metadata['height'],720)
        self.assertNotIn('https://fixture',json.dumps(qualities))
        self.assertEqual(cli.select_quality(parsed,'best').metadata['height'],1080)
        with self.assertRaises(ValueError):cli.select_quality(parsed,'2160p')

    def test_default_platform_has_no_fake_resolution(self):
        parsed=cli.ParsedVideo({'platform':'抖音','video_id':'one','title':'测试','source_url':'https://www.douyin.com/video/1'}, {},['https://fixture/video'],[])
        self.assertEqual(cli.quality_options(parsed)[0]['label'],'平台提供的默认画质')
        self.assertIsNone(cli.quality_options(parsed)[0]['height'])
        with self.assertRaises(ValueError):cli.select_quality(parsed,'1080p')

    def test_archived_variants_reuse_and_do_not_overwrite(self):
        def download(parsed,target):
            Path(target).write_bytes(str(parsed.metadata['height']).encode())
            return {'path':str(target),'size_bytes':Path(target).stat().st_size,'media':{'format':{'duration':2},'streams':[{'codec_type':'video','height':parsed.metadata['height'],'width':parsed.metadata['width'],'codec_name':'h264'},{'codec_type':'audio'}]}}
        with patch.object(cli,'download_video',side_effect=download) as dl:
            parsed=self.parsed()
            high=cli.archive_video(cli.select_quality(parsed,'1080p'))
            low=cli.archive_video(cli.select_quality(parsed,'720p'))
            self.assertNotEqual(high['path'],low['path'])
            self.assertEqual(high['project_id'],low['project_id'])
            again=cli.archive_video(cli.select_quality(parsed,'720p'))
            self.assertEqual(low['path'],again['path'])
            self.assertEqual(dl.call_count,2)
            self.assertEqual(Path(high['path']).read_bytes(),b'1080')
            self.assertEqual(len(cli.archived_videos(high['project_id'])),2)

    def test_legacy_video_preserved_and_matching_height_reused(self):
        parsed=self.parsed();project=library.ensure(parsed.metadata)
        source=self.root/'old.mp4';source.write_bytes(b'legacy')
        media={'format':{'duration':2},'streams':[{'codec_type':'video','width':1280,'height':720,'codec_name':'h264'},{'codec_type':'audio'}]}
        library.import_file(project['id'],source,'video.mp4','video',{'media':media})
        with patch.object(cli,'download_video') as dl:
            result=cli.archive_video(cli.select_quality(parsed,'720p'))
        dl.assert_not_called()
        self.assertEqual(Path(result['path']).read_bytes(),b'legacy')
        self.assertEqual(Path(result['path']).name,'video.mp4')
        self.assertEqual(cli.archived_videos(project['id'])[0]['height'],720)

    def test_cli_explicit_output_uses_selected_track_without_moving_target(self):
        target=self.root/'my chosen name.mp4'
        def download(parsed,path):
            self.assertEqual(parsed.metadata['height'],720)
            self.assertEqual(parsed.video_urls,['https://fixture/720'])
            self.assertEqual(Path(path),target)
            target.write_bytes(b'low')
            return {'path':str(target)}
        with patch.object(cli,'download_video',side_effect=download):
            result=cli_entry.execute(cli_entry.build_parser().parse_args(['download','https://www.bilibili.com/video/BV1TaqYBcEJc','--quality','720p','--output',str(target)]))
        self.assertEqual(result['path'],str(target))
        self.assertFalse(library.LIBRARY_ROOT.exists())

    def test_wrong_resolution_is_not_published(self):
        def download(parsed,target):
            target.write_bytes(b'wrong size')
            return {'media':{'format':{'duration':2},'streams':[{'codec_type':'video','width':320,'height':180},{'codec_type':'audio'}]},'size_bytes':10}
        with patch.object(cli,'download_video',side_effect=download):
            with self.assertRaises(RuntimeError):cli.archive_video(cli.select_quality(self.parsed(),'720p'))
        project=library.ensure(self.parsed().metadata)
        self.assertEqual(project['resources'],{})

    def test_cli_quality_argument_validates_before_network(self):
        args=cli_entry.build_parser().parse_args(['download','url','--quality','720p'])
        self.assertEqual(args.quality,'720p')
        with patch.object(cli,'parse_link') as parse:
            with self.assertRaises(SystemExit):cli_entry.build_parser().parse_args(['download','url','--quality','0'])
        parse.assert_not_called()


if __name__=='__main__':unittest.main()
