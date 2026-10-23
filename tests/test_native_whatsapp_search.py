import threading
import types
import unittest
from unittest.mock import MagicMock, patch
from actions import computer_control as control
from actions.whatsapp_desktop_search import whatsapp_desktop_search, TOOL
from core import whatsapp_desktop as native
from core import screen_target


class TargetGuardTests(unittest.TestCase):
    def setUp(self):
        self.gui = MagicMock()
        self.gui.size.return_value = (1920, 1080)
        for item in (patch.object(control, '_INPUT_TARGET_BLOCKED', False), patch.object(control, 'pyautogui', self.gui), patch.object(control, '_require_pyautogui')):
            item.start()
            self.addCleanup(item.stop)

    def test_failed_lookup_blocks_following_blind_typing(self):
        with patch.object(control, '_screen_find', return_value=None):
            control.computer_control({'action': 'screen_click', 'description': 'Search'})
        result = control.computer_control({'action': 'type', 'text': 'Vitor'})
        self.gui.write.assert_not_called()
        self.gui.hotkey.assert_not_called()
        self.assertIn('bloqueada', result)

    def test_new_verified_click_allows_next_input(self):
        with patch.object(control, '_screen_find', side_effect=[None, (120, 90)]):
            control.computer_control({'action': 'screen_click', 'description': 'Search'})
            control.computer_control({'action': 'screen_click', 'description': 'Correct search field'})
        control.computer_control({'action': 'type', 'text': 'Vitor'})
        self.gui.write.assert_called_once_with('Vitor', interval=.03)

    def test_window_title_alone_does_not_override_failed_field(self):
        control._INPUT_TARGET_BLOCKED = True
        with patch.object(control, '_focus_window', return_value='status=done'):
            result = control.computer_control({'action': 'type', 'title': 'WhatsApp', 'text': 'Vitor'})
        self.gui.write.assert_not_called()
        self.assertIn('status=failed', result)

    def test_native_search_failure_also_blocks_blind_typing(self):
        with patch.object(native, 'run_search', return_value='status=failed'):
            whatsapp_desktop_search({'query': 'Vitor'})
        result = control.computer_control({'action': 'type', 'text': 'Vitor'})
        self.gui.write.assert_not_called()
        self.assertIn('status=failed', result)


class NativeSearchTests(unittest.TestCase):
    def setUp(self):
        self.search = MagicMock()
        self.search.element_info.name = 'Pesquisar ou iniciar uma nova conversa'
        self.search.element_info.automation_id = 'SearchBox'
        self.search.is_visible.return_value = True
        self.search.is_enabled.return_value = True
        self.search.has_keyboard_focus.return_value = True
        self.search.get_value.return_value = 'Vitor'
        self.window = MagicMock(handle=42)
        self.window.descendants.return_value = [self.search]
        item = patch.object(control, '_INPUT_TARGET_BLOCKED', False)
        item.start()
        self.addCleanup(item.stop)

    def run_search(self):
        with patch.object(screen_target, 'foreground_id', return_value=42):
            return native.search_in_window(self.window, 'Vitor', threading.Event())

    def test_search_is_verified_without_typing_or_selecting_chat(self):
        with patch.object(control, '_type') as keyboard:
            result = self.run_search()
        self.search.set_edit_text.assert_called_once_with('Vitor')
        keyboard.assert_not_called()
        self.assertIn('query_verified=true', result)
        self.assertIn('chat_selected=false', result)
        self.assertIn('draft_written=false', result)
        self.assertTrue(control._INPUT_TARGET_BLOCKED)

    def test_ambiguous_search_never_edits(self):
        self.window.descendants.return_value = [self.search, self.search]
        self.assertIn('status=ask', self.run_search())
        self.search.set_edit_text.assert_not_called()

    def test_composer_is_not_mistaken_for_search(self):
        self.search.element_info.name = 'Digite uma mensagem'
        self.search.element_info.automation_id = 'ComposerTextBox'
        self.assertIn('code=search_not_accessible', self.run_search())
        self.search.set_edit_text.assert_not_called()

    def test_focus_failure_never_edits(self):
        self.search.has_keyboard_focus.return_value = False
        self.assertIn('code=focus_not_verified', self.run_search())
        self.search.set_edit_text.assert_not_called()

    def test_readback_mismatch_never_reports_success(self):
        self.search.get_value.return_value = 'Outra pesquisa'
        self.assertIn('code=readback_mismatch', self.run_search())

    def test_edit_pattern_failure_has_no_keyboard_fallback(self):
        self.search.set_edit_text.side_effect = RuntimeError('ValuePattern unavailable')
        with patch.object(control, '_clipboard_paste') as clipboard:
            self.assertIn('code=edit_pattern_unavailable', self.run_search())
        clipboard.assert_not_called()

    def test_schema_is_accepted(self):
        from google.genai import types
        types.FunctionDeclaration(**{key: value for key, value in TOOL.items() if key in ('name', 'description', 'parameters')})


if __name__ == '__main__':
    unittest.main()
