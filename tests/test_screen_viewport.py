import unittest
from unittest.mock import patch, MagicMock
from PIL import Image
from core.screen_viewport import crop, locate
from actions import screen_task as task, computer_control as control


class ViewportTests(unittest.TestCase):
    def test_retina_capture_crop_maps_back_to_mouse_space(self):
        image = Image.new('RGB', (3840, 2160), 'white')
        image.paste('black', (800, 400, 2400, 1600))
        bounds = (400, 200, 1200, 800)
        view = crop(image, bounds, (1920, 1080))
        self.assertEqual(view.size, (1600, 1200))
        self.assertEqual(view.getextrema(), ((0, 0), (0, 0), (0, 0)))
        result = {'found': True, 'confidence': .95, 'box_2d': [400, 400, 600, 600]}
        self.assertEqual(locate(result, bounds), (800, 500))

    def test_moved_window_during_model_call_never_clicks(self):
        task._STOP.clear()
        frame = {'window': None, 'size': (1920, 1080), 'bounds': (400, 200, 1200, 800), 'image': Image.new('RGB', (800, 600))}
        data = {'action': 'click', 'description': 'Search', 'confidence': .95, 'box_2d': [400, 400, 600, 600]}
        with patch('core.screen_target.foreground_id', return_value=None), patch('core.screen_target.accessible_target', return_value=None), patch('core.screen_viewport.active_bounds', return_value=(500, 200, 1300, 800)), patch.object(control, 'pyautogui', MagicMock()) as gui, patch.object(control, 'computer_control') as execute:
            gui.size.return_value = (1920, 1080)
            result = task._execute_step(data, frame, None)
        execute.assert_not_called()
        self.assertIn('reobserve=true', result)
