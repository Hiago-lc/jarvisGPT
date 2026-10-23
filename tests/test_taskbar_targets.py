import sys
import types
import unittest
from unittest.mock import MagicMock, patch
from PIL import Image
from core import taskbar_targets as targets
from actions import computer_control as control, screen_task as task


class TaskbarLabelTests(unittest.TestCase):
    def test_app_variants_and_prefixes_stay_distinct(self):
        self.assertTrue(targets.label_matches('Opera GX, 2 running windows', 'Opera GX'))
        self.assertTrue(targets.label_matches('Opera GX - 2 janelas', 'Opera GX'))
        self.assertFalse(targets.label_matches('Opera', 'Opera GX'))
        self.assertFalse(targets.label_matches('Opera GX', 'Opera'))
        self.assertFalse(targets.label_matches('Opera GX Installer', 'Opera GX'))

    def test_only_visible_named_primary_taskbar_buttons_are_candidates(self):
        def button(label, left=100, visible=True):
            obj = MagicMock()
            obj.window_text.return_value = label
            obj.is_visible.return_value = visible
            obj.is_enabled.return_value = True
            obj.rectangle.return_value = types.SimpleNamespace(left=left, top=1040, right=left + 40, bottom=1080)
            return obj
        bar, app = MagicMock(), MagicMock()
        bar.class_name.return_value = 'Shell_TrayWnd'
        app.class_name.return_value = 'Chrome_WidgetWin_1'
        bar.descendants.return_value = [button('Opera'), button('Opera GX, 2 windows'), button('Opera GX', -100), button('Opera GX', 300, False)]
        desktop = MagicMock()
        desktop.windows.return_value = [bar, app]
        with patch.dict(sys.modules, {'pywinauto': types.SimpleNamespace(Desktop=lambda **_: desktop)}):
            result = targets._read('Opera GX', (1920, 1080))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['label'], 'Opera GX, 2 windows')
        app.descendants.assert_not_called()

    def test_unique_label_click_does_not_need_visual_model(self):
        candidate = {'label': 'Opera GX', 'box_2d': [960, 100, 999, 125]}
        gui = MagicMock()
        gui.size.return_value = (1920, 1080)
        gui.screenshot.return_value = Image.new('RGB', (1920, 1080), 'white')
        with patch.object(control, '_require_pyautogui'), patch.object(control, 'pyautogui', gui), patch('core.screen_target.foreground_id', return_value=None), patch.object(targets, 'taskbar_targets', return_value=([candidate], 'ok')), patch('core.gemini.as_json') as model:
            result = task._observe('restore', [], desktop=True, taskbar_title='Opera GX')
        model.assert_not_called()
        self.assertEqual(result['input']['action'], 'click')
        self.assertEqual(result['input']['box_2d'], candidate['box_2d'])
        self.assertTrue(result['_frame']['desktop'])

    def test_provider_failure_releases_probe_lock(self):
        com = MagicMock()
        with patch.object(targets.platform, 'system', return_value='Windows'), patch.dict(sys.modules, {'pythoncom': com}), patch.object(targets, '_read', side_effect=RuntimeError('provider unavailable')):
            result, code = targets.taskbar_targets('Opera GX', (1920, 1080))
        self.assertEqual((result, code), ([], 'unavailable'))
        self.assertFalse(targets._LOCK.locked())
        com.CoUninitialize.assert_called_once()
