import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_parser.core import desktop


class OpenFolderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.folder = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_folder_is_an_error(self):
        with self.assertRaises(FileNotFoundError): desktop.open_folder(self.folder / 'missing')

    def test_reuses_window_that_already_shows_the_folder(self):
        with patch.object(desktop.sys, 'platform', 'win32'), patch.object(desktop, '_find_window', return_value=42), \
             patch.object(desktop.os, 'startfile', create=True) as startfile, patch.object(desktop, 'bring_to_front', return_value=True) as front:
            self.assertTrue(desktop.open_folder(self.folder))
        startfile.assert_not_called(); front.assert_called_once_with(42)

    def test_opens_new_window_and_activates_it(self):
        windows = iter([[1], [1], [1, 7]])
        with patch.object(desktop.sys, 'platform', 'win32'), patch.object(desktop, '_find_window', return_value=0), \
             patch.object(desktop, '_explorer_windows', side_effect=lambda: next(windows)), patch.object(desktop.time, 'sleep'), \
             patch.object(desktop.os, 'startfile', create=True) as startfile, patch.object(desktop, 'bring_to_front', return_value=False) as front:
            self.assertFalse(desktop.open_folder(self.folder))
        startfile.assert_called_once_with(str(self.folder)); front.assert_called_once_with(7)

    def test_activation_failure_still_opens_the_folder(self):
        with patch.object(desktop.sys, 'platform', 'win32'), patch.object(desktop, '_find_window', side_effect=RuntimeError('no COM')), \
             patch.object(desktop.os, 'startfile', create=True) as startfile:
            self.assertFalse(desktop.open_folder(self.folder))
        startfile.assert_called_once_with(str(self.folder))

    @unittest.skipIf(sys.platform == 'win32', 'non-Windows branch')
    def test_other_platforms_use_the_desktop_opener(self):
        with patch.object(desktop.subprocess, 'Popen') as popen: self.assertTrue(desktop.open_folder(self.folder))
        popen.assert_called_once()


if __name__ == '__main__':
    unittest.main()
