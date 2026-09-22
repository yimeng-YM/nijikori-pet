import base64
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import pet_snapshot
from pet_runtime import TurnState, TOOL_TURN
from PIL import Image


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'NijiKori-computer-use'
        self.root.mkdir()
        self.patch = patch.object(pet_snapshot.tempfile, 'gettempdir', return_value=self.temp.name)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.token = 'a' * 32

    def make_observation(self, *, age=0):
        state = {'observation': self.token, 'window_id': 1234, 'image_width': 80, 'image_height': 40,
                 'created_utc': (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat()}
        state_path = self.root / (self.token + '.json')
        state_path.write_text(json.dumps(state), encoding='utf-8-sig')
        png = self.root / (self.token + '.png')
        with Image.new('RGB', (80, 40), 'red') as image:
            image.save(png)
        return state_path, png

    def test_direct_capture_has_decodable_pixels_without_disk_files(self):
        with patch.object(pet_snapshot.ImageGrab, 'grab', return_value=Image.new('RGB', (2560, 1440), 'blue')) as grab:
            result = pet_snapshot.capture_snapshot(all_screens=True)
        grab.assert_called_once_with(all_screens=True)
        self.assertEqual((result['width'], result['height']), (1280, 720))
        self.assertEqual(result['source'], 'screen')
        self.assertFalse(result['saved_to_disk'])
        self.assertEqual(list(self.root.iterdir()), [])
        with Image.open(io.BytesIO(base64.b64decode(result['data_url'].split(',', 1)[1]))) as image:
            self.assertGreater(image.getpixel((100, 100))[2], 240)

    def test_single_tool_can_save_without_encoding_or_vision(self):
        target = Path(self.temp.name) / 'shots' / 'one.png'
        with patch.object(pet_snapshot.ImageGrab, 'grab', return_value=Image.new('RGB', (40, 20), 'green')):
            result = pet_snapshot.capture_snapshot(save_path=str(target), encode=False)
        self.assertTrue(result['saved_to_disk'])
        self.assertEqual(result['path'], str(target))
        self.assertNotIn('data_url', result)
        self.assertTrue(target.is_file())
        with Image.open(target) as saved:
            self.assertEqual(saved.size, (40, 20))

    def test_default_save_path_uses_window_name(self):
        path = pet_snapshot.default_save_path('window')
        self.assertTrue(path.endswith('.png'))
        self.assertIn('窗口截图', Path(path).name)

    def test_window_target_requires_a_keyword(self):
        with self.assertRaisesRegex(ValueError, 'window'):
            pet_snapshot.capture_snapshot(target='window')
        with self.assertRaisesRegex(ValueError, 'all_screens'):
            pet_snapshot.capture_snapshot(target='window', window='x', all_screens=True)

    def test_observation_read_deletes_png_preserves_coordinates(self):
        state, png = self.make_observation()
        result = pet_snapshot.capture_snapshot(observation=self.token)
        self.assertTrue(result['temporary_file_deleted'])
        self.assertEqual(result['observation'], self.token)
        self.assertEqual(result['width'], 80)
        self.assertFalse(png.exists())
        self.assertTrue(state.exists())

    def test_observation_can_also_be_saved_before_cleanup(self):
        _, png = self.make_observation()
        target = Path(self.temp.name) / 'kept.png'
        result = pet_snapshot.capture_snapshot(observation=self.token, save_path=str(target))
        self.assertTrue(result['saved_to_disk'])
        self.assertTrue(target.is_file())
        self.assertFalse(png.exists())

    def test_encoding_failure_also_deletes_png(self):
        _, png = self.make_observation()
        with patch.object(pet_snapshot, '_encode', side_effect=RuntimeError('encoder failed')):
            with self.assertRaisesRegex(RuntimeError, 'encoder failed'):
                pet_snapshot.capture_snapshot(observation=self.token)
        self.assertFalse(png.exists())

    def test_expired_observation_is_rejected_and_image_removed(self):
        _, png = self.make_observation(age=pet_snapshot.OBSERVATION_MAX_AGE_SECONDS + 30)
        with self.assertRaisesRegex(ValueError, '过期'):
            pet_snapshot.capture_snapshot(observation=self.token)
        self.assertFalse(png.exists())

    def test_observation_stays_readable_for_minutes(self):
        # A snapshot the model looked at a few minutes ago must still resolve, so
        # a long step list can keep using the same token.
        self.make_observation(age=240)
        result = pet_snapshot.capture_snapshot(observation=self.token)
        self.assertTrue(result['temporary_file_deleted'])
        self.assertEqual(result['observation'], self.token)

    def test_missing_snapshot_state_reports_a_clear_error(self):
        # The engine no longer consumes the state file, so a missing one means
        # the token really is gone; the message must say so instead of leaking a
        # "path does not exist" traceback.
        with self.assertRaisesRegex(ValueError, '请重新 Observe'):
            pet_snapshot.capture_snapshot(observation='a' * 32)

    def test_state_screenshot_path_cannot_read_or_delete_user_file(self):
        state, png = self.make_observation()
        other = Path(self.temp.name) / 'user-photo.png'
        other.write_bytes(b'keep me')
        data = json.loads(state.read_text(encoding='utf-8-sig'))
        data['screenshot'] = str(other)
        state.write_text(json.dumps(data), encoding='utf-8')
        pet_snapshot.capture_snapshot(observation=self.token)
        self.assertEqual(other.read_bytes(), b'keep me')
        self.assertFalse(png.exists())
        with self.assertRaises(ValueError):
            pet_snapshot.capture_snapshot(observation='../user-photo')
        self.assertTrue(other.exists())

    def test_mismatched_dimensions_rejected_with_cleanup(self):
        state, png = self.make_observation()
        data = json.loads(state.read_text(encoding='utf-8-sig'))
        data['image_width'] = 81
        state.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '尺寸'):
            pet_snapshot.capture_snapshot(observation=self.token)
        self.assertFalse(png.exists())

    def test_delete_failure_cannot_report_success(self):
        self.make_observation()
        with patch.object(Path, 'unlink', side_effect=PermissionError('locked')):
            with self.assertRaises(PermissionError):
                pet_snapshot.capture_snapshot(observation=self.token)


@unittest.skipUnless(sys.platform == 'win32', 'Desktop app imports Win32 APIs')
class SnapshotIntegrationTests(unittest.TestCase):
    def setUp(self):
        import main
        self.main = main
        self.pet = main.DesktopPet.__new__(main.DesktopPet)
        self.pet.config = {'vision_supported': True}
        self.pet._ai_work_lock = threading.Lock()
        self.pet._ai_work = {}
        self.pet._tk_call = Mock()

    def test_three_old_names_collapsed_into_one_tool(self):
        names = [t['function']['name'] for t in self.main.PET_TOOLS]
        self.assertEqual(names.count('screenshot'), 1)
        for gone in ('take_screenshot', 'take_snapshot', 'capture_window'):
            self.assertNotIn(gone, names)

    def test_screenshot_survives_vision_off_but_read_image_does_not(self):
        self.assertIn('screenshot', [t['function']['name'] for t in self.pet._get_active_tools()])
        self.pet.config['vision_supported'] = False
        active = [t['function']['name'] for t in self.pet._get_active_tools()]
        self.assertIn('screenshot', active)
        self.assertIn('screenshot', active)
        self.assertNotIn('read_image', active)
        self.assertNotIn('computer_use', active)  # never drive the GUI blind
        self.assertIsNone(self.pet._tool_permission_error('screenshot'))
        self.assertEqual(self.pet._tool_permission_error('read_image')['error_type'], 'vision_disabled')
        self.assertEqual(self.pet._tool_permission_error('computer_use')['error_type'], 'vision_disabled')

    def test_screenshot_without_vision_requires_save(self):
        self.pet.config['vision_supported'] = False
        result = self.pet._handle_screenshot({})
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error_type'], 'vision_disabled')

    def test_screenshot_saves_a_file_without_a_turn(self):
        self.pet.config['vision_supported'] = False
        with patch.object(self.main, 'capture_snapshot',
                          return_value={'width': 10, 'height': 5, 'path': 'x.png', 'saved_to_disk': True}) as capture:
            result = self.pet._handle_screenshot({'save': True})
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['path'], 'x.png')
        self.assertFalse(capture.call_args.kwargs['encode'])

    def test_window_target_without_keyword_is_rejected(self):
        result = self.pet._handle_screenshot({'target': 'window'})
        self.assertEqual(result['status'], 'error')

    def run_model_loop(self, *, fail=False):
        received = []
        calls = 0

        def model(base, payload, headers, *unused):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {'content': '', 'tool_calls': [{'id': 'shot-1', 'type': 'function',
                    'function': {'name': 'screenshot', 'arguments': '{"question":"查看屏幕"}'}}]}
            image_parts = [part for msg in payload['messages'] if isinstance(msg.get('content'), list)
                           for part in msg['content'] if part.get('type') == 'image_url']
            self.assertEqual(len(image_parts), 1)
            received.append(image_parts[0])
            data = base64.b64decode(image_parts[0]['image_url']['url'].split(',', 1)[1])
            with Image.open(io.BytesIO(data)) as image:
                self.assertEqual(image.size, (40, 20))
            tool_results = [m['content'] for m in payload['messages'] if m.get('role') == 'tool']
            self.assertNotIn('data:image', json.dumps(tool_results))
            if fail:
                raise RuntimeError('API failed')
            return {'content': '看到了测试画面'}

        self.pet._stream_request = model
        payload = {'messages': [{'role': 'user', 'content': '查看屏幕'}], 'tools': [pet_snapshot.SCHEMA]}
        turn = TurnState()
        with patch.object(pet_snapshot.ImageGrab, 'grab', return_value=Image.new('RGB', (40, 20), 'green')):
            if fail:
                with self.assertRaisesRegex(RuntimeError, 'API failed'):
                    self.pet._chat_complete_loop('unused', payload, {}, turn_state=turn)
            else:
                result, _ = self.pet._chat_complete_loop('unused', payload, {}, turn_state=turn)
                self.assertEqual(result, '看到了测试画面')
        self.assertEqual(calls, 2)
        self.assertEqual(turn.images, [])
        self.assertEqual(turn.transient_image_parts, [])
        self.assertNotIn('data:image', json.dumps(payload))
        self.assertTrue(received)
        self.assertEqual(received[0]['type'], 'text')
        self.assertIsNone(TOOL_TURN.get())

    def test_real_tool_loop_injects_image_then_releases_it(self):
        self.run_model_loop()

    def test_api_failure_releases_injected_image(self):
        self.run_model_loop(fail=True)


if __name__ == '__main__':
    unittest.main()
