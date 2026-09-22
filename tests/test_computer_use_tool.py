"""computer_use tool plumbing: payload translation, snapshot injection, helpers."""
import sys
import threading
import time
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


class HelperTests(unittest.TestCase):
    def test_extract_json_object_ignores_powershell_noise(self):
        import main
        text = "warning: something\n{'a': 1}\n{\"status\": \"success\", \"observation\": \"x\"}\ntrailing"
        self.assertEqual(main._extract_json_object(text),
                         {'status': 'success', 'observation': 'x'})
        self.assertIsNone(main._extract_json_object('no json here'))
        self.assertIsNone(main._extract_json_object(''))

    def test_console_command_never_double_wraps_cmd(self):
        import main
        self.assertEqual(main._console_command('notepad'), 'cmd /c notepad')
        self.assertEqual(main._console_command('notepad', True), 'cmd /k notepad')
        self.assertEqual(main._console_command('cmd /k npx dsh web'), 'cmd /k npx dsh web')
        self.assertEqual(main._console_command('cmd /c dir'), 'cmd /c dir')
        self.assertEqual(main._console_command('  '), '')

    def test_background_output_wait_seconds_reports_when_still_running(self):
        import pet_tools.shell as shell
        job = {'id': 'bg_test', 'cmd': 'x', 'cwd': '', 'shell': 'cmd', 'description': '',
               'stdout': deque(['line']), 'stderr': deque(), 'out_truncated': False, 'proc': None,
               'done': threading.Event(), 'exit_code': None, 'killed': False,
               'started_at': time.time(), 'finished_at': None}
        shell.BG_JOBS['bg_test'] = job
        try:
            result = shell.read_background_output({'job_id': 'bg_test', 'wait_seconds': 1})
            self.assertEqual(result['waited_seconds'], 1)
            self.assertEqual(result['state'], 'running')
            job['done'].set()
            job['exit_code'] = 0
            done = shell.read_background_output({'job_id': 'bg_test', 'wait_seconds': 1})
            self.assertEqual(done['state'], 'finished')
            self.assertNotIn('waited_seconds', done)
        finally:
            shell.BG_JOBS.pop('bg_test', None)


@unittest.skipUnless(sys.platform == 'win32', 'Desktop app imports Win32 APIs')
class ComputerUseToolTests(unittest.TestCase):
    def setUp(self):
        import main
        self.main = main
        self.pet = main.DesktopPet.__new__(main.DesktopPet)
        self.pet.config = {'vision_supported': True}
        self.pet._ai_work_lock = threading.Lock()
        self.pet._ai_work = {}
        self.pet._tk_call = Mock()
        self.pet._confirm_tool_action = Mock(return_value=True)

    def test_payload_translation_defaults_and_types(self):
        payload = self.pet._computer_use_payload({
            'action': 'double_click', 'window': '记事本', 'x': '10', 'y': 20,
            'observation': 'a' * 32, 'button': 'right', 'no_snapshot': True,
            'save_path': str(Path(self._tmpdir()) / 'shot.png')})
        self.assertEqual(payload['action'], 'doubleclick')
        self.assertEqual((payload['x'], payload['y']), (10, 20))
        self.assertEqual(payload['snapshot_delay_ms'], 300)
        self.assertTrue(payload['no_snapshot'])
        self.assertTrue(payload['save_snapshot'].endswith('shot.png'))

    def _tmpdir(self):
        import tempfile
        path = tempfile.mkdtemp(prefix='cu-tool-test-')
        return path

    def test_payload_rejects_bad_numbers_and_empty_steps(self):
        with self.assertRaises(ValueError):
            self.pet._computer_use_payload({'action': 'click', 'x': 'abc'})
        with self.assertRaises(ValueError):
            self.pet._computer_use_payload({'action': 'steps', 'steps': []})
        with self.assertRaises(ValueError):
            self.pet._computer_use_payload({'action': 'steps', 'steps': 'not-a-list'})

    def test_payload_keeps_explicit_delay_and_steps(self):
        steps = [{'action': 'click', 'x': 1, 'y': 2}]
        payload = self.pet._computer_use_payload({'action': 'steps', 'steps': steps,
                                                  'snapshot_delay_ms': 900})
        self.assertEqual(payload['action'], 'steps')
        self.assertEqual(payload['snapshot_delay_ms'], 900)
        self.assertEqual(payload['steps'], steps)

    def test_payload_normalizes_step_aliases_and_typing_mode(self):
        payload = self.pet._computer_use_payload({
            'action': 'steps', 'window': '记事本', 'mode': 'replace',
            'steps': [{'action': 'double_click', 'x': 5, 'y': 6},
                      {'action': 'input', 'text': '你好'}]})
        self.assertEqual([step['action'] for step in payload['steps']],
                         ['doubleclick', 'type'])
        self.assertEqual(payload['mode'], 'replace')
        self.assertEqual(payload['snapshot_delay_ms'], 300)

    def test_payload_keeps_unknown_step_names_for_the_engine_to_reject(self):
        # The engine owns the canonical list and prints it in the error, so a
        # typo must reach it unchanged instead of being silently rewritten.
        payload = self.pet._computer_use_payload({'action': 'steps',
                                                  'steps': [{'action': 'flying_kick'}]})
        self.assertEqual(payload['steps'][0]['action'], 'flying_kick')
        with self.assertRaises(ValueError):
            self.pet._computer_use_payload({'action': 'steps', 'steps': ['not-a-dict']})

    def test_payload_append_mode_and_bad_mode(self):
        payload = self.pet._computer_use_payload({'action': 'type', 'text': 'x', 'mode': 'append'})
        self.assertNotIn('mode', payload)          # append is the engine default
        with self.assertRaises(ValueError):
            self.pet._computer_use_payload({'action': 'type', 'text': 'x', 'mode': 'sideways'})

    def test_missing_script_is_reported(self):
        self.pet._computer_use_script = lambda: ''
        result = self.pet._handle_computer_use({'action': 'click', 'x': 1, 'y': 2})
        self.assertEqual(result['status'], 'error')
        self.assertIn('computer-use', result['message'])

    def test_unknown_action_is_rejected(self):
        self.pet._computer_use_script = lambda: 'x.ps1'
        result = self.pet._handle_computer_use({'action': 'launch_missiles'})
        self.assertEqual(result['status'], 'error')
        self.assertIn('action', result['message'])

    def test_step_snapshots_are_injected_without_an_extra_read_call(self):
        from pet_runtime import TurnState, TOOL_TURN
        turn = TurnState()
        handle = TOOL_TURN.set(turn)
        script = 'x.ps1'
        run_result = {'status': 'success', 'action_performed': True, 'window_id': 7,
                      'observations': ['b' * 32, 'c' * 32], 'image_width': 40, 'image_height': 20,
                      'steps_done': 2}
        try:
            with patch.object(self.pet, '_computer_use_script', return_value=script), \
                    patch.object(self.pet, '_run_computer_use', return_value=(run_result, '')), \
                    patch.object(self.main, 'capture_snapshot',
                                 side_effect=[{'data_url': 'data:image/jpeg;base64,AA', 'width': 40, 'height': 20},
                                              {'data_url': 'data:image/jpeg;base64,BB', 'width': 40, 'height': 20}]) as capture:
                result = self.pet._handle_computer_use({'action': 'click', 'x': 5, 'y': 6,
                                                        'observation': 'a' * 32})
        finally:
            TOOL_TURN.reset(handle)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['snapshots_returned'], 2)
        self.assertEqual(result['last_observation'], 'c' * 32)
        self.assertEqual([c.kwargs['observation'] for c in capture.call_args_list], ['b' * 32, 'c' * 32])
        self.assertEqual([img['label'] for img in turn.images],
                         ['computer-use 窗口快照', 'computer-use 窗口快照'])

    def test_failed_steps_still_return_the_snapshot_taken_before_failure(self):
        from pet_runtime import TurnState, TOOL_TURN
        turn = TurnState()
        handle = TOOL_TURN.set(turn)
        try:
            with patch.object(self.pet, '_computer_use_script', return_value='x.ps1'), \
                    patch.object(self.pet, '_run_computer_use',
                                 return_value=({'status': 'error', 'action_performed': True,
                                                'message': 'boom', 'observations': ['b' * 32]}, '')), \
                    patch.object(self.main, 'capture_snapshot',
                                 return_value={'data_url': 'data:image/jpeg;base64,AA'}):
                result = self.pet._handle_computer_use({'action': 'click', 'x': 5, 'y': 6,
                                                        'observation': 'a' * 32})
        finally:
            TOOL_TURN.reset(handle)
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['message'], 'boom')
        self.assertEqual(result['snapshots_returned'], 1)

    def test_steps_label_each_snapshot_in_order(self):
        from pet_runtime import TurnState, TOOL_TURN
        turn = TurnState()
        handle = TOOL_TURN.set(turn)
        run_result = {'status': 'success', 'action_performed': True,
                      'observations': ['b' * 32, 'c' * 32], 'steps_done': 2}
        try:
            with patch.object(self.pet, '_computer_use_script', return_value='x.ps1'),                     patch.object(self.pet, '_run_computer_use', return_value=(run_result, '')),                     patch.object(self.main, 'capture_snapshot',
                                 side_effect=[{'data_url': 'data:image/jpeg;base64,AA'},
                                              {'data_url': 'data:image/jpeg;base64,BB'}]):
                self.pet._handle_computer_use({'action': 'steps', 'window': '记事本',
                                               'steps': [{'action': 'click', 'x': 1, 'y': 2}]})
        finally:
            TOOL_TURN.reset(handle)
        self.assertEqual([img['label'] for img in turn.images],
                         ['computer-use 第 1 步后的窗口快照', 'computer-use 第 2 步后的窗口快照'])

    def test_whole_screen_mode_detected_and_labelled(self):
        from pet_runtime import TurnState, TOOL_TURN
        turn = TurnState()
        handle = TOOL_TURN.set(turn)
        run_result = {'status': 'success', 'action_performed': False,
                      'window': {'whole_screen': True, 'title': '整个屏幕'},
                      'observations': ['b' * 32], 'image_width': 1280, 'image_height': 720}
        try:
            with patch.object(self.pet, '_computer_use_script', return_value='x.ps1'),                     patch.object(self.pet, '_run_computer_use', return_value=(run_result, '')),                     patch.object(self.main, 'capture_snapshot',
                                 return_value={'data_url': 'data:image/jpeg;base64,AA'}):
                result = self.pet._handle_computer_use({'action': 'observe', 'window': 'screen'})
        finally:
            TOOL_TURN.reset(handle)
        self.assertTrue(result['whole_screen'])
        self.assertEqual(turn.images[0]['label'], 'computer-use 整个屏幕快照')

    def _fake_run(self, payload, stdout='{"status":"success"}'):
        """Drive the real _run_computer_use with a stubbed powershell process."""
        import subprocess as sp
        proc = Mock(returncode=0, stdout=stdout, stderr='')
        with patch.object(sp, 'run', return_value=proc) as run, \
                patch.object(self.pet, '_set_pet_hidden', return_value=False) as hide:
            data, error = self.pet._run_computer_use('x.ps1', payload, 30)
        return run, hide, data, error

    def test_whole_screen_observation_hides_the_pet_around_the_capture(self):
        run, hide, data, error = self._fake_run({'action': 'observe', 'window': 'screen'})
        self.assertEqual(error, '')
        self.assertEqual(hide.call_args_list[0].args, (True,))
        self.assertEqual(hide.call_args_list[1].args, (False,))
        self.assertEqual(hide.call_args_list[1].kwargs, {'was_hidden': False})
        self.assertTrue(data['pet_hidden'])

    def test_window_targeted_operation_never_hides_the_pet(self):
        for payload in ({'action': 'click', 'window': '记事本', 'x': 1, 'y': 2},
                        {'action': 'observe', 'window': '记事本'},
                        {'action': 'windows'}):
            with self.subTest(payload=payload):
                run, hide, data, error = self._fake_run(payload)
                hide.assert_not_called()
                self.assertFalse(data.get('pet_hidden'))

    def test_already_hidden_pet_is_not_reshown(self):
        import subprocess as sp
        proc = Mock(returncode=0, stdout='{"status":"success"}', stderr='')
        with patch.object(sp, 'run', return_value=proc), \
                patch.object(self.pet, '_set_pet_hidden', return_value=True) as hide:
            data, error = self.pet._run_computer_use('x.ps1', {'action': 'observe', 'window': '屏幕'}, 30)
        self.assertFalse(data['pet_hidden'])   # it was already hidden by the user
        # It was already hidden by the user, so nothing is restored afterwards.
        self.assertEqual([c.args for c in hide.call_args_list], [(True,)])

    def test_pet_occlusion_is_retried_once_with_the_pet_hidden(self):
        blocked = {'status': 'error', 'error_type': 'pet_blocks', 'action_performed': False,
                   'message': '操作位置被桌宠自己的窗口挡住'}
        ok = {'status': 'success', 'action_performed': True,
              'window': {'id': 1, 'title': '记事本', 'process': 'notepad'},
              'observations': [], 'image_width': 0, 'image_height': 0}
        with patch.object(self.pet, '_computer_use_script', return_value='x.ps1'), \
                patch.object(self.pet, '_run_computer_use',
                             side_effect=[(blocked, ''), (ok, '')]) as run, \
                patch.object(self.pet, '_set_pet_hidden', side_effect=[False, None]) as hide, \
                patch.object(self.main.time, 'sleep'):
            result = self.pet._handle_computer_use(
                {'action': 'click', 'window': '记事本', 'x': 10, 'y': 20})
        self.assertEqual(result['status'], 'success')
        self.assertTrue(result['pet_hidden'])
        self.assertEqual(run.call_count, 2)
        self.assertIn('pet_pid', run.call_args_list[0].args[1])
        self.assertEqual([call.args for call in hide.call_args_list], [(True,), (False,)])
        self.assertEqual(hide.call_args_list[1].kwargs, {'was_hidden': False})

    def test_engine_errors_get_a_concrete_hint(self):
        failed = {'status': 'error', 'action_performed': False,
                  'message': 'Coordinates must be inside the observed image'}
        with patch.object(self.pet, '_computer_use_script', return_value='x.ps1'), \
                patch.object(self.pet, '_run_computer_use', return_value=(failed, '')):
            result = self.pet._handle_computer_use(
                {'action': 'click', 'window': '记事本', 'x': 10, 'y': 20})
        self.assertEqual(result['status'], 'error')
        self.assertIn('image_width', result['message'])

    def test_no_snapshot_means_no_injection(self):
        from pet_runtime import TurnState, TOOL_TURN
        turn = TurnState()
        handle = TOOL_TURN.set(turn)
        try:
            with patch.object(self.pet, '_computer_use_script', return_value='x.ps1'), \
                    patch.object(self.pet, '_run_computer_use',
                                 return_value=({'status': 'success', 'action_performed': True,
                                                'observations': ['b' * 32]}, '')), \
                    patch.object(self.main, 'capture_snapshot') as capture:
                result = self.pet._handle_computer_use({'action': 'click', 'x': 1, 'y': 2,
                                                        'observation': 'a' * 32, 'no_snapshot': True})
        finally:
            TOOL_TURN.reset(handle)
        self.assertEqual(result['snapshots_returned'], 0)
        capture.assert_not_called()


if __name__ == '__main__':
    unittest.main()
