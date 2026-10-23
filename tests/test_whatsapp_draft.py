import threading
import unittest
from unittest.mock import MagicMock, patch
from actions.whatsapp_draft import whatsapp_draft, TOOL
from core import whatsapp_web as web


class DraftTests(unittest.TestCase):
    def setUp(self):
        self.current = 'Vitor'
        self.text = ''
        self.page = MagicMock(url='https://web.whatsapp.com/')
        header = MagicMock()
        header.is_visible.return_value = True
        header.get_attribute.side_effect = lambda attr: self.current
        headers = MagicMock()
        headers.all.return_value = [header]
        self.composer = MagicMock()
        self.composer.first = self.composer
        self.composer.count.return_value = 1
        self.composer.inner_text.side_effect = lambda **kwargs: self.text
        self.composer.fill.side_effect = lambda value, **kwargs: setattr(self, 'text', value)
        self.search = MagicMock()
        self.search.first = self.search
        self.search.count.return_value = 1
        self.candidates = MagicMock()
        self.candidates.first = self.candidates
        self.candidates.count.return_value = 1
        self.candidates.get_attribute.return_value = 'Vitor'
        self.candidates.click.side_effect = lambda **kwargs: setattr(self, 'current', 'Vitor')
        self.results = MagicMock()
        self.results.filter.return_value = self.candidates
        locators = {'#main header [title]': headers,
                    '#main footer [contenteditable="true"][role="textbox"]': self.composer,
                    '#side [contenteditable="true"][role="textbox"]': self.search,
                    '#pane-side span[title]': self.results}
        self.page.locator.side_effect = lambda selector: locators[selector]
        self.stop = threading.Event()

    def run_edit(self, action='write', text='Estou testando agora.', replace=False):
        return web.edit_draft(self.page, 'Vitor', action, text, replace, self.stop)

    def test_write_is_verified_by_readback_and_never_presses_enter(self):
        self.assertEqual(self.run_edit(), 'Estou testando agora.')
        self.composer.fill.assert_called_once_with('Estou testando agora.', timeout=3000)
        self.composer.press.assert_not_called()
        self.page.keyboard.press.assert_not_called()
        self.page.get_by_role.assert_not_called()
        self.search.fill.assert_not_called()

    def test_exact_contact_is_opened_before_filling(self):
        self.current = 'Ana'
        self.run_edit()
        self.search.fill.assert_called_once_with('Vitor', timeout=3000)
        self.candidates.click.assert_called_once()
        self.assertEqual(self.current, 'Vitor')
        self.assertEqual(self.text, 'Estou testando agora.')

    def test_duplicate_contacts_do_not_type(self):
        self.current = 'Ana'
        self.candidates.count.return_value = 2
        with self.assertRaises(web.DraftError) as error:
            self.run_edit()
        self.assertEqual(error.exception.code, 'ambiguous_contact')
        self.candidates.click.assert_not_called()
        self.composer.fill.assert_not_called()

    def test_clear_changes_only_the_composer(self):
        self.text = 'Texto antigo'
        self.assertEqual(self.run_edit(action='clear'), '')
        self.composer.fill.assert_called_once_with('', timeout=3000)
        self.page.keyboard.press.assert_not_called()

    def test_existing_draft_requires_explicit_replace(self):
        self.text = 'Rascunho anterior'
        with self.assertRaises(web.DraftError) as error:
            self.run_edit()
        self.assertEqual(error.exception.code, 'existing_draft')
        self.composer.fill.assert_not_called()
        self.assertEqual(self.run_edit(replace=True), 'Estou testando agora.')

    def test_read_does_not_mutate_existing_draft(self):
        self.text = 'Texto para ler'
        self.assertEqual(self.run_edit(action='read'), self.text)
        self.composer.fill.assert_not_called()

    def test_cancellation_prevents_mutation(self):
        self.stop.set()
        with self.assertRaises(web.DraftError):
            self.run_edit()
        self.composer.fill.assert_not_called()

    def test_login_or_changed_ui_produces_actionable_error(self):
        self.current = 'Ana'
        self.search.wait_for.side_effect = RuntimeError('not visible')
        with self.assertRaises(web.DraftError) as error:
            self.run_edit()
        self.assertEqual(error.exception.code, 'login_or_ui')
        self.assertIn('QR Code', str(error.exception))
        self.composer.fill.assert_not_called()

    def test_changed_conversation_is_not_reported_as_verified(self):
        def fill(value, **kwargs):
            self.text = value
            self.current = 'Ana'
        self.composer.fill.side_effect = fill
        with self.assertRaises(web.DraftError) as error:
            self.run_edit()
        self.assertEqual(error.exception.code, 'chat_changed')

    def test_tool_returns_only_the_verified_readback_as_untrusted_data(self):
        with patch.object(web, 'run', return_value=(True, 'verified', 'Texto real do campo')):
            result = whatsapp_draft({'action': 'write', 'recipient': 'Vitor', 'text': 'Texto real do campo'})
        self.assertIn('status=done', result)
        self.assertIn('sent=false', result)
        self.assertIn('UNTRUSTED', result)
        self.assertIn('Texto real do campo', result)

    def test_tool_schema_has_no_send_action(self):
        from google.genai import types
        self.assertEqual(TOOL['parameters']['properties']['action']['enum'], ['write', 'clear', 'read'])
        types.FunctionDeclaration(**{k: v for k, v in TOOL.items() if k in ('name', 'description', 'parameters')})


if __name__ == '__main__':
    unittest.main()
