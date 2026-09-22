"""Skill integration and rejection tests; never inject real desktop input."""
import ast
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'resources/skills/computer-use'
SCRIPT = SKILL / 'scripts/computer-use.ps1'


def powershell(*arguments):
    return subprocess.run(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', *arguments],
        capture_output=True, text=True, timeout=30,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )


class DiscoveryTests(unittest.TestCase):
    def test_existing_pet_loader_reads_nested_triggers(self):
        # Use the production parser without starting the desktop application.
        source = ast.parse((ROOT / 'src/main.py').read_text(encoding='utf-8-sig'))
        node = next(n for n in source.body if isinstance(n, ast.FunctionDef)
                    and n.name == 'parse_skill_frontmatter')
        namespace = {}
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<pet-parser>', 'exec'), namespace)
        meta, body = namespace['parse_skill_frontmatter']((SKILL / 'SKILL.md').read_text(encoding='utf-8'))
        self.assertEqual(meta['name'], 'computer-use')
        self.assertIn('帮我操作', meta['triggers'])
        self.assertTrue(body.strip())


@unittest.skipUnless(sys.platform == 'win32', 'Windows PowerShell helper')
class HelperTests(unittest.TestCase):
    def test_environment_compiles_native_input_layout_without_input(self):
        result = powershell('-File', str(SCRIPT), '-Action', 'Check')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        data = json.loads(result.stdout)
        self.assertEqual(data['status'], 'success')
        self.assertIn(data['input_size'], (28, 40))

    def test_input_without_observation_is_rejected(self):
        result = powershell('-File', str(SCRIPT), '-Action', 'Click', '-X', '10', '-Y', '10')
        self.assertNotEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertFalse(data['action_performed'])
        self.assertIn('observation token', data['message'])

    def test_observation_token_cannot_traverse_paths(self):
        result = powershell('-File', str(SCRIPT), '-Action', 'Key', '-Observation', '../outside', '-Keys', 'ENTER')
        self.assertNotEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertFalse(data['action_performed'])
        self.assertIn('observation token', data['message'])

    def test_validate_normalises_step_aliases_and_text_without_input(self):
        result = powershell('-File', str(SCRIPT), '-Action', 'Validate', '-Steps',
                            '[{"action":"double_click","x":1,"y":2},'
                            '{"action":"input","text":"a\\nb"},{"action":"sleep","ms":50}]')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        data = json.loads(result.stdout)
        self.assertEqual([step['action'] for step in data['steps']],
                         ['doubleclick', 'type', 'sleep'])
        # A literal backslash-n is normalised into a real line break.
        self.assertEqual(data['steps'][1]['text'], 'a\nb')

    def test_unsupported_step_action_lists_the_allowed_names(self):
        result = powershell('-File', str(SCRIPT), '-Action', 'Validate',
                            '-Steps', '[{"action":"flying_kick"}]')
        self.assertNotEqual(result.returncode, 0)
        message = json.loads(result.stdout)['message']
        self.assertIn('flying_kick', message)
        for name in ('click', 'doubleclick', 'type', 'key', 'sleep'):
            self.assertIn(name, message)

    def test_validate_reports_typing_mode(self):
        result = powershell('-File', str(SCRIPT), '-Action', 'Validate', '-Mode', 'replace')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout)['mode'], 'replace')

    def test_focus_requires_explicit_window_selection(self):
        result = powershell('-File', str(SCRIPT), '-Action', 'Focus')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('WindowId is required', json.loads(result.stdout)['message'])

    def test_real_coordinate_mapper_and_key_parser_without_input(self):
        script = str(SCRIPT).replace("'", "''")
        native = str(SKILL / 'scripts/native.cs').replace("'", "''")
        command = r"""
$ErrorActionPreference = 'Stop'
$parseErrors = $null; $tokens = $null
$tree = [Management.Automation.Language.Parser]::ParseFile('__SCRIPT__', [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
$fn = $tree.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Get-ImagePoint'}, $true)
Invoke-Expression $fn.Extent.Text
$snapshot = [pscustomobject]@{left=-1920; top=-200; width=2560; height=1440; image_width=1280; image_height=720}
$first = Get-ImagePoint $snapshot 0 0
$last = Get-ImagePoint $snapshot 1279 719
if ($first[0] -ne -1920 -or $first[1] -ne -200) { throw 'Negative monitor origin mismatch' }
if ($last[0] -ne 638 -or $last[1] -ne 1238) { throw 'Scaled coordinate mismatch' }
$rejected = 0
foreach ($point in @(@(-1,0),@(1280,0),@(0,720))) {
    try { Get-ImagePoint $snapshot $point[0] $point[1] | Out-Null } catch { $rejected++ }
}
if ($rejected -ne 3) { throw 'Off-image point accepted' }
Add-Type -Path '__NATIVE__'
if ([NijiComputer]::KeyCode('ctrl') -ne 17 -or [NijiComputer]::KeyCode('F12') -ne 123) { throw 'Key mismatch' }
$rejected = 0
foreach ($key in @('F13','{ENTER}','CTRL+Z','')) {
    try { [NijiComputer]::KeyCode($key) | Out-Null } catch { $rejected++ }
}
if ($rejected -ne 4) { throw 'Unsupported key accepted' }
'PASS'
""".replace('__SCRIPT__', script).replace('__NATIVE__', native)
        result = powershell('-Command', command)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn('PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
