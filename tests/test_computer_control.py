import io
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

from actions import computer_control as cc
from memory import config_manager as cm
from start_gemini import configure


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.gui = MagicMock()
        self.gui.size.return_value = (1920, 1080)
        self.clip = MagicMock()
        self.clipboard = 'texto anterior'
        self.clip.paste.side_effect = lambda: self.clipboard
        self.clip.copy.side_effect = lambda value: setattr(self, 'clipboard', value)
        self.patches = [patch.object(cc, '_INPUT_TARGET_BLOCKED', False), patch.object(cc, 'pyautogui', self.gui),
                        patch.object(cc, 'pyperclip', self.clip),
                        patch.object(cc, '_PYAUTOGUI', True),
                        patch.object(cc, '_PYPERCLIP', True),
                        patch.object(cc, '_get_os', return_value='windows'),
                        patch.object(cc.time, 'sleep')]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_short_portuguese_text_is_pasted_and_clipboard_restored(self):
        result = cc.computer_control({'action': 'type', 'text': 'ação'})
        self.gui.hotkey.assert_called_once_with('ctrl', 'v')
        self.gui.write.assert_not_called()
        self.assertEqual(self.clipboard, 'texto anterior')
        self.assertIn('status=unverified', result)

    def test_clipboard_failure_does_not_clear_field(self):
        self.clip.copy.side_effect = RuntimeError('clipboard busy')
        result = cc.computer_control({'action': 'smart_type', 'text': 'ação'})
        self.assertIn('status=failed', result)
        self.gui.hotkey.assert_not_called()

    def test_visual_click_routes_description_to_finder(self):
        with patch.object(cc, '_screen_find', return_value=(140, 90)) as finder:
            result = cc.computer_control({'action': 'click', 'description': 'campo Buscar'})
        finder.assert_called_once_with('campo Buscar')
        self.gui.click.assert_called_once_with(140, 90, button='left', clicks=1)
        self.assertIn('status=unverified', result)

    def test_type_in_named_field_locates_and_clicks_first(self):
        with patch.object(cc, '_screen_find', return_value=(140, 90)):
            cc.computer_control({'action': 'type', 'description': 'campo Nome', 'text': 'Hiago'})
        self.gui.click.assert_called_once_with(140, 90, button='left', clicks=1)
        self.gui.write.assert_called_once_with('Hiago', interval=0.03)
        calls = [call[0] for call in self.gui.mock_calls]
        self.assertLess(calls.index('click'), calls.index('write'))

    def test_missing_field_never_types(self):
        with patch.object(cc, '_screen_find', return_value=None):
            result = cc.computer_control({'action': 'type', 'description': 'campo Nome', 'text': 'Hiago'})
        self.gui.write.assert_not_called()
        self.gui.click.assert_not_called()
        self.assertIn('status=failed', result)

    def test_tool_schema_is_accepted_by_gemini_sdk(self):
        from google.genai import types as gtypes
        gtypes.FunctionDeclaration(**{k: v for k, v in cc.TOOL.items() if k in ('name', 'description', 'parameters')})

    def test_missing_visual_target_never_clicks(self):
        with patch.object(cc, '_screen_find', return_value=None):
            result = cc.computer_control({'action': 'screen_click', 'description': 'Enviar'})
        self.gui.click.assert_not_called()
        self.assertIn('status=failed', result)

    def test_out_of_bounds_and_partial_coordinates_never_click(self):
        for params in ({'x': 2000, 'y': 2}, {'x': 100}):
            self.assertIn('status=failed', cc.computer_control({'action': 'click', **params}))
        self.gui.click.assert_not_called()

    def test_failed_focus_stops_input(self):
        with patch.object(cc, '_focus_window', return_value='status=failed'):
            result = cc.computer_control({'action': 'type', 'title': 'Bloco de Notas', 'text': 'hello'})
        self.gui.write.assert_not_called()
        self.assertIn('status=failed', result)

    def test_windows_focus_is_verified(self):
        window = MagicMock(title='Documento - Notepad', width=800, height=600, _hWnd=10)
        window.isMinimized = True
        windows = types.SimpleNamespace(getWindowsWithTitle=lambda title: [window], getActiveWindow=lambda: window)
        with patch.dict('sys.modules', {'pygetwindow': windows}):
            self.assertIn('status=done', cc._focus_window('Notepad'))
        window.restore.assert_called_once()
        window.activate.assert_called_once()

    def test_windows_focus_refusal_does_not_report_success(self):
        window = MagicMock(title='Notepad', width=800, height=600, _hWnd=10)
        windows = types.SimpleNamespace(getWindowsWithTitle=lambda title: [window], getActiveWindow=lambda: None)
        with patch.dict('sys.modules', {'pygetwindow': windows}):
            self.assertIn('status=failed', cc._focus_window('Notepad'))

    def test_screenshot_coordinates_scale_to_input_dimensions(self):
        from core import gemini
        self.gui.screenshot.return_value.size = (3840, 2160)
        response = {'found': True, 'confidence': .95, 'box_2d': [400, 400, 600, 600]}
        with patch.object(cc, '_get_api_key', return_value='test'), patch.object(gemini, 'as_json', return_value=response):
            self.assertEqual(cc._screen_find('campo'), (960, 540))

    def test_emergency_stop_is_reported(self):
        class FailSafeException(Exception):
            pass
        self.gui.click.side_effect = FailSafeException()
        result = cc.computer_control({'action': 'click', 'x': 1, 'y': 1})
        self.assertIn('status=failed', result)
        self.assertIn('canto', result)


class GeminiStartupTests(unittest.TestCase):
    def test_restores_gemini_and_preserves_personal_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'api_keys.json'
            config.write_text(json.dumps({'gemini_api_key': 'existing', 'user_name': 'Hiago', 'providers': {'mode': 'pipeline', 'sidecar': 'openai_compat', 'creds': {'other': {'model': 'saved'}}}}))
            with patch.object(cm, 'CONFIG_DIR', Path(folder)), patch.object(cm, 'CONFIG_FILE', config), patch.dict(os.environ, {'GEMINI_API_KEY': '', 'JARVIS_OPENAI_ONLY': '1'}):
                configure()
                saved = json.loads(config.read_text())
                self.assertEqual(saved['providers']['mode'], 'gemini')
                self.assertEqual(saved['providers']['sidecar'], '')
                self.assertEqual(saved['providers']['creds']['other']['model'], 'saved')
                self.assertEqual(saved['user_name'], 'Hiago')
                self.assertNotIn('JARVIS_OPENAI_ONLY', os.environ)


if __name__ == '__main__':
    unittest.main()
