import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from core.live_errors import is_aborted, error_text
from actions import file_controller
from configure_drive_access import authorize


class ReportedErrorTests(unittest.TestCase):
    def test_nested_live_abort_is_recognized(self):
        error = ExceptionGroup('TaskGroup failed', [ExceptionGroup('inner', [RuntimeError('1008 None. The operation was aborted.')])])
        self.assertTrue(is_aborted(error))
        self.assertIn('1008', error_text(error))
        self.assertNotIn('TaskGroup failed', error_text(error))

    def test_quota_is_not_misreported_as_abort(self):
        error = ExceptionGroup('TaskGroup failed', [RuntimeError('429 RESOURCE_EXHAUSTED')])
        self.assertFalse(is_aborted(error))
        self.assertFalse(is_aborted(RuntimeError('1008 policy violation: RESOURCE_EXHAUSTED')))
        self.assertIn('429', error_text(error))

    def test_external_drive_root_is_read_only_and_preserves_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            home = folder / 'home'
            drive = folder / 'drive'
            home.mkdir(); drive.mkdir()
            file = drive / 'notes.txt'
            file.write_text('work note')
            config = folder / 'config.json'
            config.write_text(json.dumps({'os_system': 'windows', 'existing_setting': True}))
            authorize(str(drive), config)
            settings = json.loads(config.read_text())
            self.assertTrue(settings['existing_setting'])
            with patch.object(file_controller, '_SAFE_ROOTS', [home]), patch('memory.config_manager.load_api_keys', return_value=settings):
                self.assertTrue(file_controller._is_safe_path(file, read_only=True))
                self.assertFalse(file_controller._is_safe_path(file))
                self.assertIn('work note', file_controller.read_file(str(file)))
                self.assertIn('Access denied', file_controller.write_file(str(file), content='changed'))
            self.assertEqual(file.read_text(), 'work note')

    def test_read_root_does_not_allow_symlink_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            drive = folder / 'drive'; drive.mkdir()
            outside = folder / 'outside.txt'; outside.write_text('private')
            link = drive / 'link.txt'
            try:
                link.symlink_to(outside)
            except OSError:
                self.skipTest('Symlinks unavailable')
            with patch.object(file_controller, '_SAFE_ROOTS', []), patch('memory.config_manager.load_api_keys', return_value={'file_read_roots': [str(drive)]}):
                self.assertFalse(file_controller._is_safe_path(link, read_only=True))
