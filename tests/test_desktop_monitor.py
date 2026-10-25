import os
import sys
import unittest
from unittest.mock import MagicMock
if sys.platform != 'win32' and not os.environ.get('DISPLAY'):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication
from core.desktop_monitor import DesktopMonitor

_APP = QApplication.instance() or QApplication([])


class DesktopMonitorTests(unittest.TestCase):
    def test_stop_and_back_interrupt_active_task(self):
        stop, back = MagicMock(), MagicMock()
        panel = DesktopMonitor(stop, back)
        panel.begin('Open Ads Manager')
        panel.back()
        stop.assert_called_once()
        back.assert_called_once()
        panel.running = False
        panel.close()
        panel.timer.stop()

    def test_capture_fallback_is_explicit_and_finish_never_claims_success(self):
        panel = DesktopMonitor(lambda: None, lambda: None)
        panel.show()
        panel.excluded = False
        panel.refresh()
        self.assertIn('Prévia indisponível', panel.picture.text())
        panel.finish(30)
        self.assertIn('encerrada', panel.status.text())
        self.assertFalse(panel.running)
        self.assertFalse(panel.stop_button.isEnabled())
        panel.close()
        panel.timer.stop()
