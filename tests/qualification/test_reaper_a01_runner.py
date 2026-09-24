from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess

from tools.qualification.reaper_a01 import (
    FocusGate,
    REAPER_BUNDLE_ID,
    _failure_record,
    _guard_duplicate_run,
    _dispatch_reopen_action,
    _new_json,
    _registered_reopen_action_id,
    _read_action_command_id,
    utc_now,
)
from tools.qualification.reaper_a01 import sha256


class FixedProbe:
    def __init__(self, bundle_id: str):
        self.bundle_id = bundle_id

    def read(self) -> dict:
        return {'observed_at_utc': utc_now(), 'name': 'test app',
                'bundle_id': self.bundle_id, 'process_id': 123}


class A01RunnerSafetyTests(unittest.TestCase):
    def test_focus_gate_refuses_reaper_and_system_login_window(self) -> None:
        for bundle_id in (REAPER_BUNDLE_ID, 'com.apple.loginwindow'):
            with self.subTest(bundle_id=bundle_id), tempfile.TemporaryDirectory() as temporary:
                journal = Path(temporary) / 'focus.jsonl'
                called = False

                def operation() -> str:
                    nonlocal called
                    called = True
                    return 'should not run'

                gate = FocusGate(FixedProbe(bundle_id), journal)
                with self.assertRaisesRegex(RuntimeError, 'no eligible user application'):
                    gate.step('test mutation', operation)
                self.assertFalse(called)
                event = json.loads(journal.read_text().splitlines()[0])
                self.assertEqual(event['event'], 'refused')
                self.assertEqual(event['focus']['bundle_id'], bundle_id)

    def test_failure_record_keeps_journal_and_project_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / 'session.RPP'
            project.write_bytes(b'disposable project bytes')
            (root / 'a01-manifest-profile.json').write_text(json.dumps({'project': str(project)}))
            journal = root / 'a01-focus.jsonl'
            journal.write_text('{"event":"finished","operation_result":{"receipt":"r1"}}\n')
            reopen_copy = root / 'a01-reopen-copy.RPP'
            reopen_copy.write_bytes(b'reopen copy')
            tabs = root / 'a01-tabs-before.tsv'
            tabs.write_text('ok=true\n')
            try:
                raise RuntimeError('failure after a recorded operation')
            except RuntimeError as error:
                failure = _failure_record(root, error)
            output = root / 'a01-failure.json'
            _new_json(output, failure)
            saved = json.loads(output.read_text())
            self.assertFalse(saved['ok'])
            self.assertEqual(saved['focus_journal_sha256'], failure['focus_journal_sha256'])
            self.assertEqual(saved['project_sha256_at_failure'], failure['project_sha256_at_failure'])
            self.assertEqual(saved['reopen_copy_sha256_at_failure'], sha256(reopen_copy))
            self.assertEqual(saved['tab_inventories']['a01-tabs-before.tsv']['sha256'], sha256(tabs))
            self.assertIn('operation_result', journal.read_text())

    def test_duplicate_run_guard_refuses_existing_failure_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _guard_duplicate_run(root)
            (root / 'a01-failure.json').write_text('{}\n')
            with self.assertRaisesRegex(FileExistsError, 'evidence or reopen-copy path already exists'):
                _guard_duplicate_run(root)

    def test_reopen_preflight_refuses_missing_or_invalid_registration_without_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            resource = Path(temporary)
            success = resource / 'a01-open-stage.txt'
            with self.assertRaisesRegex(RuntimeError, 'not registered'):
                _registered_reopen_action_id(resource)
            self.assertFalse(success.exists())

            (resource / 'reaper-kb.ini').write_text(
                'SCR 4 0 RSnot-a-command-id "Custom: llm_studio_a01_reopen.lua" '
                'llm_studio_a01_reopen.lua\n')
            with self.assertRaisesRegex(RuntimeError, 'exactly one valid'):
                _registered_reopen_action_id(resource)
            self.assertFalse(success.exists())

            registered = 'RS' + 'a' * 40
            action_id_file = resource / 'a01-action-id.txt'
            action_id_file.write_text(f'ok=true\nregistered_action_id={registered}\nreaper_command_id=abc\n')
            with self.assertRaisesRegex(RuntimeError, 'positive integer'):
                _read_action_command_id(action_id_file, registered)
            self.assertFalse(success.exists())

    def test_reopen_preflight_returns_exact_registered_action_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            resource = Path(temporary)
            action_id = 'RS' + 'a' * 40
            (resource / 'reaper-kb.ini').write_text(
                f'SCR 4 0 {action_id} "Custom: llm_studio_a01_reopen.lua" '
                'llm_studio_a01_reopen.lua\n')
            self.assertEqual(_registered_reopen_action_id(resource), action_id)
            receipt = resource / 'action-id.txt'
            receipt.write_text(f'ok=true\nregistered_action_id={action_id}\nreaper_command_id=12345\n')
            self.assertEqual(_read_action_command_id(receipt, action_id), 12345)

    def test_reopen_dispatch_uses_numeric_osc_action_and_checks_send_receipt(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='{"address":"/action","args":[12345],"bytes":16}', stderr='')
        with patch('tools.qualification.reaper_a01.subprocess.run', return_value=completed) as run:
            result = _dispatch_reopen_action(Path('/private/tmp/reaper-controller-fd56'), 12345)
        self.assertEqual(result['command_id'], 12345)
        self.assertEqual(run.call_args.args[0][-3:], ['osc-send', '/action', '12345'])


if __name__ == '__main__':
    unittest.main()
