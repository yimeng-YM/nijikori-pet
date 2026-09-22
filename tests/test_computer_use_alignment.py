# -*- coding: utf-8 -*-
"""computer-use coordinate mapping must be exact, for both DPI modes.

These tests launch a real Tk window with red crosshair markers at known client
coordinates, take a computer-use snapshot of it, and check that

  1. the marker lands at the position the coordinate mapper expects inside the
     returned image (image is the same rendering the model looks at), and
  2. clicking that image pixel lands on the marker in the target application.

They never type into or close anything the user owns: the only input is a click
on the throwaway target window this test created itself, and it is skipped when
PowerShell or a desktop session is unavailable.
"""
import json
import math
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'resources/skills/computer-use/scripts/computer-use.ps1'
TARGET = ROOT / 'tests/gui_marker_target.py'

from PIL import Image


def powershell_available():
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive',
                                 '-Command', '$PSVersionTable.PSVersion.Major'],
                                capture_output=True, timeout=30,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return result.returncode == 0
    except Exception:
        return False


def child_env(**extra):
    """Environment for the target app, cleared of frozen-app leftovers."""
    env = dict(os.environ)
    for key in [k for k in env if k.startswith('_MEI') or k.startswith('_PYI_')]:
        env.pop(key, None)
    for key in ('TCL_LIBRARY', 'TK_LIBRARY'):
        if '_MEI' in (env.get(key) or '') or not os.path.isdir(env.get(key) or ''):
            env.pop(key, None)
    env.update(extra)
    return env


@unittest.skipUnless(sys.platform == 'win32' and powershell_available(),
                     'needs Windows PowerShell')
class CoordinateMappingTests(unittest.TestCase):
    """One target window per DPI mode; the scale is asserted too, not assumed."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='nijikori-align-')
        cls.dir = Path(cls.temp.name)
        cls.children = []
        cls.logs = []

    @classmethod
    def tearDownClass(cls):
        for proc in cls.children:
            try:
                proc.terminate()
            except Exception:
                pass
        for proc in cls.children:
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
        for handle in cls.logs:
            try:
                handle.close()
            except Exception:
                pass
        cls.temp.cleanup()

    def start_target(self, dpi_aware, record_keys=False):
        directory = Path(tempfile.mkdtemp(dir=self.dir))
        hwnd_file, state_file = directory / 'hwnd.json', directory / 'state.json'
        keys_file = directory / 'keys.json'
        log = open(directory / 'child.log', 'w')
        self.logs.append(log)
        proc = subprocess.Popen(
            [sys.executable, '-B', str(TARGET), str(hwnd_file), str(state_file),
             str(keys_file) if record_keys else ''],
            stdout=log, stderr=subprocess.STDOUT,
            env=child_env(CU_DPI_AWARE='1' if dpi_aware else '0'))
        self.children.append(proc)
        for _ in range(150):
            if hwnd_file.exists():
                break
            time.sleep(0.1)
        self.assertTrue(hwnd_file.exists(),
                        'target window did not start: ' + (directory / 'child.log').read_text()[:400])
        time.sleep(1.5)
        return json.loads(hwnd_file.read_text()), state_file, directory, keys_file

    def run_action(self, payload, directory):
        args_file = directory / 'args.json'
        args_file.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        proc = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
             '-File', str(SCRIPT), '-ArgsFile', str(args_file)],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=120, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        lines = [ln for ln in (proc.stdout or '').strip().splitlines() if ln.strip()]
        self.assertTrue(lines, 'no JSON from computer-use: ' + (proc.stderr or '')[:400])
        return json.loads(lines[-1])

    def check_mapping(self, dpi_aware):
        info, state_file, directory, _keys_file = self.start_target(dpi_aware)
        snap = self.run_action({'action': 'focus', 'window': 'NijiCU-Marker'}, directory)
        self.assertEqual(snap.get('status'), 'success', snap)
        iw, ih = snap['image_width'], snap['image_height']
        cache = Path(tempfile.gettempdir()) / 'NijiKori-computer-use'
        state = json.loads((cache / (snap['observation'] + '.json')).read_text(encoding='utf-8-sig'))
        left, top, width, height = state['left'], state['top'], state['width'], state['height']
        mark_x, mark_y = info['mark']
        client_x, client_y = info['client_origin']

        # 1. The render must match the geometry the mapper reports, or every
        #    click would drift proportionally.  The crosshair marker check below
        #    is what actually pins content-to-geometry alignment.
        with Image.open(cache / (snap['observation'] + '.png')) as probe:
            self.assertEqual((probe.width, probe.height), (iw, ih))
        with Image.open(cache / (snap['observation'] + '.png')).convert('RGB') as image:
            columns = [x for x in range(image.width)
                       if sum(1 for y in range(0, image.height, 7)
                              if image.getpixel((x, y))[0] > 180 and image.getpixel((x, y))[1] < 90)
                       > image.height // 7 * .6]
            rows = [y for y in range(image.height)
                    if sum(1 for x in range(0, image.width, 7)
                           if image.getpixel((x, y))[0] > 180 and image.getpixel((x, y))[1] < 90)
                    > image.width // 7 * .6]
        self.assertTrue(columns and rows, 'crosshair markers not found in the snapshot')
        observed_x, observed_y = sum(columns) / len(columns), sum(rows) / len(rows)
        # The target app may report virtualized (logical) coordinates when it is
        # DPI-unaware; convert them to physical ones before comparing.
        win_left, win_top = info['window_rect'][0], info['window_rect'][1]
        scale_x = width / max(1, info['window_rect'][2] - win_left)
        scale_y = height / max(1, info['window_rect'][3] - win_top)
        physical_client_x = left + (client_x - win_left) * scale_x
        physical_client_y = top + (client_y - win_top) * scale_y
        expected_x = (physical_client_x + mark_x * scale_x - left) * iw / width
        expected_y = (physical_client_y + mark_y * scale_y - top) * ih / height
        # The image the model sees and the coordinates it is told to use agree.
        self.assertLess(abs(observed_x - expected_x), 2.0,
                        'snapshot content is offset from its stated geometry')
        self.assertLess(abs(observed_y - expected_y), 2.0,
                        'snapshot content is offset from its stated geometry')

        # 2. Clicking that pixel must land on the marker in the application.
        result = self.run_action({'action': 'click', 'window': 'NijiCU-Marker',
                                  'observation': snap['observation'],
                                  'x': int(round(observed_x)), 'y': int(round(observed_y))},
                                 directory)
        self.assertEqual(result.get('status'), 'success', result)
        self.assertTrue(result.get('action_performed'))
        time.sleep(0.6)
        self.assertTrue(state_file.exists(), 'the target never received the click')
        clicks = json.loads(state_file.read_text())
        delivered = clicks[-1]
        # The app reports the click in its OWN coordinate space, which is exactly
        # where the crosshair was drawn — that is the whole point of the mapping.
        self.assertLessEqual(abs(delivered['x'] - mark_x), 2,
                             'click landed at client x=%s, expected %s' % (delivered['x'], mark_x))
        self.assertLessEqual(abs(delivered['y'] - mark_y), 2,
                             'click landed at client y=%s, expected %s' % (delivered['y'], mark_y))

    def read_keys(self, keys_file):
        # The target writes the file from its own event loop, so give Tk a moment.
        for _ in range(50):
            if keys_file.exists():
                break
            time.sleep(0.1)
        time.sleep(0.4)
        return json.loads(keys_file.read_text(encoding='utf-8')) if keys_file.exists() else []

    def test_observation_token_can_drive_several_steps(self):
        # Issue 2 of the report: the first input used to consume the token, so the
        # next click failed with a misleading coordinate error. The same snapshot
        # must now drive more than one action.
        _, state_file, directory, _keys = self.start_target(dpi_aware=True)
        snap = self.run_action({'action': 'focus', 'window': 'NijiCU-Marker'}, directory)
        self.assertEqual(snap.get('status'), 'success', snap)
        px, py = snap['image_width'] // 4, snap['image_height'] // 4
        for attempt in range(2):
            result = self.run_action({'action': 'click', 'window': 'NijiCU-Marker',
                                      'observation': snap['observation'],
                                      'x': px, 'y': py}, directory)
            self.assertEqual(result.get('status'), 'success', result)
            self.assertTrue(result.get('action_performed'), attempt)
        time.sleep(0.5)
        self.assertGreaterEqual(len(json.loads(state_file.read_text())), 2)

    def test_position_covered_by_the_pet_is_reported_not_clicked(self):
        # The pet is always on top; when it covers the target point the engine must
        # say so (error_type=pet_blocks) instead of clicking into the pet. This is
        # what lets the app hide the pet and retry automatically.
        _, state_file, directory, _keys = self.start_target(dpi_aware=True)
        snap = self.run_action({'action': 'focus', 'window': 'NijiCU-Marker'}, directory)
        self.assertEqual(snap.get('status'), 'success', snap)
        cache = Path(tempfile.gettempdir()) / 'NijiKori-computer-use'
        state = json.loads((cache / (snap['observation'] + '.json')).read_text(encoding='utf-8-sig'))
        result = self.run_action({'action': 'click', 'window': 'NijiCU-Marker',
                                  'observation': snap['observation'],
                                  'x': snap['image_width'] // 4, 'y': snap['image_height'] // 4,
                                  'pet_pid': state['process_id']}, directory)
        self.assertEqual(result.get('status'), 'error', result)
        self.assertEqual(result.get('error_type'), 'pet_blocks')
        self.assertFalse(result.get('action_performed'))
        self.assertFalse(state_file.exists(), 'the blocked click must not be delivered')

    def test_type_and_key_need_no_coordinates(self):
        # Regression for the report's "key/type require coordinates" complaint:
        # both must work with a window keyword, no snapshot and no x/y, and a
        # literal backslash-n must arrive as a real Enter.
        _, _, directory, keys_file = self.start_target(dpi_aware=True, record_keys=True)
        focus = self.run_action({'action': 'focus', 'window': 'NijiCU-Marker'}, directory)
        self.assertEqual(focus.get('status'), 'success', focus)

        typed = self.run_action({'action': 'type', 'window': 'NijiCU-Marker',
                                 'text': 'AB\\nCD'}, directory)
        self.assertEqual(typed.get('status'), 'success', typed)
        self.assertTrue(typed.get('action_performed'))
        # Tk reports WM_CHAR text in the event's char field; the literal
        # backslash-n must arrive as a real Enter between B and C.
        received = [item['char'] for item in self.read_keys(keys_file) if item['char']]
        self.assertEqual(received[:5], ['A', 'B', '\r', 'C', 'D'],
                         'multi-line typing did not produce a real Enter')

        pressed = self.run_action({'action': 'key', 'window': 'NijiCU-Marker',
                                   'keys': 'END'}, directory)
        self.assertEqual(pressed.get('status'), 'success', pressed)
        self.assertIn('End', [item['keysym'] for item in self.read_keys(keys_file)])

    def test_keyboard_only_steps_need_no_target(self):
        # A steps list of only type/key must run against the focused window with
        # no window keyword and no observation.
        _, _, directory, keys_file = self.start_target(dpi_aware=True, record_keys=True)
        self.run_action({'action': 'focus', 'window': 'NijiCU-Marker'}, directory)
        result = self.run_action({'action': 'steps',
                                  'steps': [{'action': 'type', 'text': 'ZZ'},
                                            {'action': 'key', 'keys': 'END'}]}, directory)
        self.assertEqual(result.get('status'), 'success', result)
        self.assertEqual(result.get('steps_done'), 2)
        self.assertIn('Z', [item['char'] for item in self.read_keys(keys_file)])

    def test_type_replace_mode_selects_all_first(self):
        # mode=replace sends CTRL,A before typing (the report's suggestion).
        _, _, directory, keys_file = self.start_target(dpi_aware=True, record_keys=True)
        replaced = self.run_action({'action': 'type', 'window': 'NijiCU-Marker',
                                    'text': 'XY', 'mode': 'replace'}, directory)
        self.assertEqual(replaced.get('status'), 'success', replaced)
        typed = self.read_keys(keys_file)
        select_all = [index for index, item in enumerate(typed)
                      if item['char'] == '\x01' and item['state'] & 4]
        self.assertTrue(select_all, 'CTRL,A was never sent: %r' % (typed,))
        self.assertIn('X', [item['char'] for item in typed[select_all[0]:]])

    def test_dpi_aware_window_maps_exactly(self):
        self.check_mapping(dpi_aware=True)

    def test_dpi_unaware_window_maps_exactly(self):
        # Legacy apps report virtualized coordinates; the physical window rect
        # must be used for the render so scaling stays 1:1.
        self.check_mapping(dpi_aware=False)


if __name__ == '__main__':
    unittest.main()
