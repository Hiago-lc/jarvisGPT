import asyncio
import io
import re
import threading
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from PIL import Image
from core.live_screen_planner import LiveScreenPlanner, proposal_tool
from core import live_screen_planner, automation_view
from actions import screen_task, computer_control


class ProposalTests(unittest.IsolatedAsyncioTestCase):
    async def test_outdated_or_unsolicited_tool_calls_cannot_supply_next_action(self):
        planner = LiveScreenPlanner(threading.Event())
        planner.session = types.SimpleNamespace(send_tool_response=AsyncMock())
        future = asyncio.get_running_loop().create_future()
        planner.pending = ('new-request', future)
        stale = types.SimpleNamespace(name='propose_desktop_step', id='tool-1', args={'request_id': 'old-request', 'state': 'act'})
        await planner._proposals([stale])
        self.assertFalse(future.done())
        acknowledgement = planner.session.send_tool_response.call_args.kwargs['function_responses'][0]
        self.assertEqual(acknowledgement.response['status'], 'ignored_outdated_or_unsolicited')
        valid = types.SimpleNamespace(name='propose_desktop_step', id='tool-2', args={'request_id': 'new-request', 'state': 'act', 'input': {'action': 'click', 'description': 'Search'}})
        await planner._proposals([valid])
        self.assertEqual(future.result()['input']['description'], 'Search')
        self.assertNotIn('request_id', future.result())

    async def test_cancelled_task_rejects_even_matching_proposal(self):
        stop = threading.Event()
        planner = LiveScreenPlanner(stop)
        planner.session = types.SimpleNamespace(send_tool_response=AsyncMock())
        future = asyncio.get_running_loop().create_future()
        planner.pending = ('request', future)
        stop.set()
        await planner._proposals([types.SimpleNamespace(name='propose_desktop_step', id='1', args={'request_id': 'request', 'state': 'act'})])
        self.assertFalse(future.done())

    async def test_stop_during_capture_prevents_sending_another_frame(self):
        stop = threading.Event()
        def capture():
            stop.set()
            return b'frame', 'image/jpeg'
        planner = LiveScreenPlanner(stop, frame_source=capture)
        planner.session = types.SimpleNamespace(send_realtime_input=AsyncMock())
        planner.shutdown = asyncio.Event()
        await planner._stream()
        planner.session.send_realtime_input.assert_not_called()
        self.assertTrue(planner.shutdown.is_set())


class StreamingTests(unittest.TestCase):
    def test_one_live_session_streams_and_serves_multiple_reference_requests(self):
        class Session:
            def __init__(self):
                self.queue = asyncio.Queue()
                self.frames = []
                self.acks = []
            async def send_realtime_input(self, **kwargs):
                self.frames.append(kwargs['video'])
            async def send_client_content(self, **kwargs):
                text = kwargs['turns']['parts'][1].text
                request = re.search(r'Planning request_id=(\w+)', text).group(1)
                proposal = types.SimpleNamespace(name='propose_desktop_step', id=request, args={'request_id': request, 'state': 'act', 'reason': 'Visible control', 'input': {'action': 'click', 'description': 'Search', 'confidence': .95, 'box_2d': [100, 100, 200, 200]}})
                await self.queue.put(types.SimpleNamespace(tool_call=types.SimpleNamespace(function_calls=[proposal]), go_away=None))
            async def send_tool_response(self, **kwargs):
                self.acks.extend(kwargs['function_responses'])
            async def receive(self):
                yield await self.queue.get()
        session = Session()
        context = types.SimpleNamespace(__aenter__=AsyncMock(return_value=session), __aexit__=AsyncMock())
        client = MagicMock()
        client.aio.live.connect.return_value = context
        client.aio.aclose = AsyncMock()
        planner = LiveScreenPlanner(threading.Event(), frame_source=lambda: (b'frame', 'image/jpeg'))
        with patch('google.genai.Client', return_value=client), patch('core.gemini.api_key', return_value='test'), patch('core.gemini.live_model', return_value='test-live'), patch('core.live_screen_planner.notify', return_value=True):
            try:
                self.assertEqual(planner.decide(b'reference-1', 'Find search')['state'], 'act')
                self.assertEqual(planner.decide(b'reference-2', 'Find search again')['state'], 'act')
            finally:
                planner.close()
                planner.thread.join(timeout=2)
        client.aio.live.connect.assert_called_once()
        self.assertGreaterEqual(len(session.frames), 1)
        self.assertEqual(session.frames[0].data, b'frame')
        self.assertEqual(len(session.acks), 2)
        self.assertTrue(all(a.response['status'] == 'proposal_received_not_executed' for a in session.acks))
        context.__aexit__.assert_awaited_once()
        self.assertFalse(planner.thread.is_alive())

    def test_tool_schema_is_accepted_by_sdk(self):
        from google.genai import types
        types.LiveConnectConfig(response_modalities=['AUDIO'], tools=[{'function_declarations': [proposal_tool()]}])

    def test_live_failure_falls_back_to_reference_image_rest(self):
        planner = MagicMock(failed=False)
        planner.decide.side_effect = RuntimeError('connection unavailable')
        gui = MagicMock()
        gui.size.return_value = (1920, 1080)
        gui.screenshot.return_value = Image.new('RGB', (1920, 1080), 'white')
        with patch.object(computer_control, '_require_pyautogui'), patch.object(computer_control, 'pyautogui', gui), patch('core.screen_target.foreground_id', return_value=None), patch.object(live_screen_planner, 'current', return_value=planner), patch('core.gemini.as_json', return_value={'state': 'blocked', 'reason': 'Uncertain'}) as rest:
            screen_task._STOP.clear()
            result = screen_task._observe('Find target', [])
        rest.assert_called_once()
        planner.disable.assert_called_once()
        self.assertIn('_frame', result)

    def test_concurrent_capture_does_not_reshow_panel_during_input(self):
        events = []
        entered, release = threading.Event(), threading.Event()
        def handler(action, payload):
            events.append(payload['hidden'])
            payload['_ok'] = True
            payload['_ack'].set()
        def capture():
            with automation_view.unobstructed():
                entered.set()
                release.wait(2)
        automation_view.install(handler)
        thread = threading.Thread(target=capture)
        try:
            with automation_view.unobstructed():
                thread.start()
                self.assertTrue(entered.wait(1))
            self.assertEqual(events, [True])
            release.set()
            thread.join(2)
            self.assertEqual(events, [True, False])
        finally:
            release.set()
            thread.join(2)
            automation_view.install(None)

    def test_task_owns_and_closes_its_planner_even_on_failure(self):
        planner = MagicMock()
        with patch.object(live_screen_planner, 'enabled', return_value=True), patch.object(live_screen_planner, 'LiveScreenPlanner', return_value=planner), patch.object(screen_task, '_observe', side_effect=RuntimeError('failed')):
            result = screen_task.screen_task({'goal': 'Open requested tab'})
        self.assertIn('status=failed', result)
        planner.close.assert_called_once()
        self.assertIsNone(live_screen_planner.current())
