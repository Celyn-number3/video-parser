"""Parser configuration must not activate removed server/database behavior."""
import importlib
import os
import unittest
from unittest.mock import patch

from video_parser.core import settings as constants


class ParserConfigurationTests(unittest.TestCase):
    def test_database_environment_is_irrelevant_to_new_parser_configuration(self):
        with patch.dict(os.environ, {'DB_PORT': 'not-a-database-port'}):
            configuration = importlib.reload(constants)
        self.assertTrue(configuration.DOMAIN_TO_NAME)
        self.assertEqual(len(configuration.PLATFORM_MAP), 8)
        for name in ('DATABASE_CONFIG', 'WECHAT_APP_ID', 'WECHAT_APP_SECRET', 'AUDIT_MODE',
                     'MINI_PROGRAM_LEGAL_DOMAIN', 'SAVE_VIDEO_PATH', 'SAVE_IMAGE_PATH'):
            self.assertFalse(hasattr(configuration, name), name)

    def test_import_does_not_create_static_media_directories(self):
        with patch('os.makedirs') as create_directory:
            importlib.reload(constants)
        create_directory.assert_not_called()


if __name__ == '__main__':
    unittest.main()
