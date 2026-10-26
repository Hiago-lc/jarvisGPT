import unittest
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QApplication
from ui import MainWindow
from core.automation_view import install
from actions import screen_task

_APP = QApplication.instance() or QApplication([])


class IndicatorControlTests(unittest.TestCase):
    def test_indicator_controls_and_lightweight_default(self):
        with patch.object(MainWindow, '_check_config', return_value=True):
            window = MainWindow('core/face_model.obj')
        try:
            window.show(); _APP.processEvents()
            self.assertEqual(window._hud_cam_stack.currentIndex(), 3)
            self.assertFalse(window.hud._tmr.isActive())
            self.assertFalse(window._metric_tmr.isActive())
            self.assertTrue(window._left_panel.isHidden())
            window.on_interrupt = MagicMock()
            window.showMinimized(); _APP.processEvents()
            indicator = window._stability_indicator
            self.assertTrue(indicator.isVisible())
            indicator.mic_button.click()
            self.assertTrue(window._muted)
            self.assertEqual(indicator.mic_button.text(), 'Ligar microfone')
            window._toggle_mute()
            self.assertFalse(window._muted)
            self.assertEqual(indicator.mic_button.text(), 'Desligar microfone')
            screen_task._STOP.clear()
            indicator.stop_button.click()
            self.assertTrue(screen_task._STOP.is_set())
            window.on_interrupt.assert_called_once()
            indicator.button.click(); _APP.processEvents()
            self.assertFalse(window.isMinimized())
        finally:
            screen_task._STOP.clear()
            if window._stability_indicator:
                window._stability_indicator.hide()
            window.hide()
            install(None)
