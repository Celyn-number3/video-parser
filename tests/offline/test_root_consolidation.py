"""No-inference checks for path migration and native session identity."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from video_parser.core.paths import ROOT
from video_parser.services import model_calls


class ConsolidatedWorkspaceIdentityTests(unittest.TestCase):
    def test_moved_project_keeps_legacy_native_workspace_key(self):
        relative = Path('fixture') / 'project'
        legacy_key = hashlib.sha256(str(ROOT / 'library' / relative).encode('utf-8')).hexdigest()[:24]
        with tempfile.TemporaryDirectory() as directory:
            native = Path(directory) / 'native'
            with patch.object(model_calls, 'WORKSPACE_ROOT', native):
                result = model_calls.workspace(ROOT / 'outputs' / relative, 'a' * 32)
            self.assertEqual(result, (native / legacy_key / ('a' * 32)).resolve())
        self.assertFalse((ROOT / 'library').exists())

    def test_external_project_identity_does_not_change(self):
        with tempfile.TemporaryDirectory() as directory:
            external = Path(directory) / 'external'
            native = Path(directory) / 'native'
            key = hashlib.sha256(str(external.resolve()).encode('utf-8')).hexdigest()[:24]
            with patch.object(model_calls, 'WORKSPACE_ROOT', native):
                result = model_calls.workspace(external, 'b' * 32)
            self.assertEqual(result, (native / key / ('b' * 32)).resolve())
