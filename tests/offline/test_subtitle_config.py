"""External subtitle checker configuration, without personal files or network."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from video_parser.services import subtitles


class SubtitleConfigTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / 'home'
        self.tool = self.root / 'tool'
        self.repository_checker = self.tool / 'skills/bili-subtitle-download/scripts/check_subtitles.py'
        self.legacy_checker = self.home / '.codex/skills/bili-subtitle-download/scripts/check_subtitles.py'
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {}, clear=True).start()
        patch.object(Path, 'home', return_value=self.home).start()

    def touch(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# fixture', encoding='utf-8')

    def test_explicit_checker_wins(self):
        explicit = self.root / 'custom checker.py'
        self.touch(explicit)
        self.touch(self.repository_checker)
        with patch.dict(os.environ, {'BILI_SUBTITLE_CHECKER': str(explicit)}):
            self.assertEqual(subtitles.resolve_checker_path(self.tool), explicit)

    def test_invalid_explicit_path_does_not_fall_back(self):
        self.touch(self.repository_checker)
        explicit = self.root / 'missing.py'
        with patch.dict(os.environ, {'BILI_SUBTITLE_CHECKER': str(explicit)}):
            self.assertEqual(subtitles.resolve_checker_path(self.tool), explicit)
            with patch.object(subtitles, 'TOOL_ROOT', self.tool), patch.object(subtitles, 'CHECKER_PATH', explicit):
                self.touch(self.tool / 'b站.py')
                self.assertFalse(subtitles.available())

    def test_repository_checker_preferred_over_personal_skill(self):
        self.touch(self.repository_checker)
        self.touch(self.legacy_checker)
        self.assertEqual(subtitles.resolve_checker_path(self.tool), self.repository_checker)

    def test_legacy_path_kept_when_no_repository_checker(self):
        self.assertEqual(subtitles.resolve_checker_path(self.tool), self.legacy_checker)

    def test_tilde_in_explicit_checker_is_expanded(self):
        with patch.dict(os.environ, {'BILI_SUBTITLE_CHECKER': '~/checker.py', 'HOME': str(self.home), 'USERPROFILE': str(self.home)}):
            self.assertEqual(subtitles.resolve_checker_path(self.tool), self.home/'checker.py')


if __name__ == '__main__':
    unittest.main()
