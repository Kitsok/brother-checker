import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from brother import Checker, CheckError, WirelessStatus, Observation
from telnet_client import TelnetClient, parse_idle
from recovery import Recovery
from state import FileState


def observation(mismatch=True, reachable=True):
    return Observation(reachable,
                       WirelessStatus('HOME', '-' if mismatch else 'WPA3-SAE',
                                      'AES', '' if mismatch else '802.11n',
                                      0 if mismatch else 1, '2') if reachable else None,
                       mismatch and reachable)


class FakePrinter:
    host = '172.20.20.127'

    def __init__(self, idle=True, jobs=0, fail_request=False):
        self.is_idle, self.jobs, self.fail_request = idle, jobs, fail_request
        self.prepared = self.requests = self.idle_calls = 0

    def idle_status(self):
        self.idle_calls += 1
        return {'idle': self.is_idle and not self.jobs, 'state': 'idle' if self.is_idle else 'processing',
                'reasons': ['none'], 'pending_jobs': self.jobs}

    def prepare_restart(self):
        self.prepared += 1
        return {'token': 'not-a-real-token'}

    def request_restart(self, token):
        self.requests += 1
        if self.fail_request:
            raise TimeoutError()
        return {'accepted': True}


class FakeChecker:
    def __init__(self, observations, printer=None):
        self.observations = iter(observations)
        self.printer = printer or FakePrinter()

    def status(self):
        return next(self.observations)


class FakeStore:
    def __init__(self, reason=None):
        self.reason, self.reservations = reason, 0

    def block_reason(self):
        return self.reason

    def reserve(self):
        self.reservations += 1


class RecoveryTests(unittest.TestCase):
    def execute(self, observations, printer=None, store=None, **kwargs):
        checker = FakeChecker(observations, printer)
        store = store or FakeStore()
        events = []; now = [0.0]
        def sleep(seconds): now[0] += seconds
        def report(event, data):
            if event == 'before_restart':
                self.assertEqual(checker.printer.requests, 0)
            events.append((event, data))
        code = Recovery(checker, store, report, sleep).run(**kwargs)
        return code, checker.printer, store, events

    def test_dry_run_never_even_prepares_restart(self):
        code, p, s, events = self.execute([observation()] * 3, dry_run=True)
        self.assertEqual(code, 0)
        self.assertEqual((p.prepared, p.requests, s.reservations), (0, 0, 0))
        self.assertEqual(events[-1][0], 'dry_run')

    def test_healthy_single_shot_does_not_restart(self):
        code, p, _, _ = self.execute([observation(False)])
        self.assertEqual(code, 0); self.assertEqual(p.requests, 0)

    def test_transient_mismatch_cannot_restart(self):
        code, p, _, _ = self.execute([observation(), observation(False)])
        self.assertEqual(code, 2); self.assertEqual(p.requests, 0)

    def test_busy_or_held_jobs_cannot_restart(self):
        for printer in [FakePrinter(idle=False), FakePrinter(jobs=1)]:
            code, p, _, _ = self.execute([observation()] * 3, printer=printer)
            self.assertEqual(code, 2); self.assertEqual(p.prepared, 0)

    def test_changed_idle_right_before_reset_blocks_final_request(self):
        printer = FakePrinter()
        original = printer.idle_status
        def idle():
            if printer.prepared: printer.jobs = 1
            return original()
        printer.idle_status = idle
        code, p, _, _ = self.execute([observation()] * 4, printer=printer)
        self.assertEqual(code, 2); self.assertEqual(p.requests, 0)

    def test_manual_stage_reports_before_one_request_and_does_not_verify(self):
        code, p, store, events = self.execute([observation(False)] * 2, stage='restart')
        self.assertEqual((code, p.requests, store.reservations), (0, 1, 1))
        self.assertIn('before_restart', [e for e, _ in events])
        self.assertNotIn('verification', [e for e, _ in events])

    def test_uncertain_request_exits_without_recheck_or_retry(self):
        code, p, store, events = self.execute([observation()] * 4,
                                             printer=FakePrinter(fail_request=True))
        self.assertEqual((code, p.requests, store.reservations), (3, 1, 1))
        self.assertIn('restart_uncertain', [e for e, _ in events])

    def test_automatic_stage_exits_immediately_after_acknowledgement(self):
        # Exactly four observations exist: three persistence samples and the
        # pre-reset check. Any post-restart check would exhaust this iterator.
        code, p, store, events = self.execute([observation()] * 4)
        self.assertEqual((code, p.requests, store.reservations), (0, 1, 1))
        self.assertEqual(events[-1][0], 'restart_requested')
        self.assertNotIn('verification', [e for e, _ in events])

    def test_cooldown_prevents_preparation(self):
        code, p, _, _ = self.execute([observation()] * 3, store=FakeStore('cooldown'))
        self.assertEqual(code, 2); self.assertEqual(p.prepared, 0)

    def test_transport_timeout_does_not_restart(self):
        printer = FakePrinter()
        class Unavailable:
            def status(self):raise TimeoutError()
        checker = Unavailable();checker.printer = printer
        with self.assertRaises(TimeoutError):
            Recovery(checker, FakeStore(), lambda *a: None).run()
        self.assertEqual(printer.requests, 0)

    def test_status_and_idle_stages_are_independent(self):
        code, p, _, _ = self.execute([observation()], stage='status')
        self.assertEqual(code, 1); self.assertEqual(p.idle_calls, 0)
        code, p, _, _ = self.execute([], stage='idle')
        self.assertEqual(code, 0); self.assertEqual(p.requests, 0)


class PersistenceTests(unittest.TestCase):
    def test_cooldown_daily_limit_and_concurrent_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'state.json'; now = [100000.0]
            with FileState(path, 'printer', cooldown=10, daily_limit=2, clock=lambda: now[0]) as s:
                self.assertIsNone(s.block_reason());s.reserve()
                self.assertIn('cooldown', s.block_reason())
                with self.assertRaises(CheckError):
                    with FileState(path, 'printer'):pass
            now[0] += 11
            with FileState(path, 'printer', cooldown=10, daily_limit=2, clock=lambda: now[0]) as s:
                self.assertIsNone(s.block_reason());s.reserve()
            now[0] += 11
            with FileState(path, 'printer', cooldown=10, daily_limit=2, clock=lambda: now[0]) as s:
                self.assertIn('24-hour', s.block_reason())
            path.write_text('broken')
            with self.assertRaises(CheckError):FileState(path, 'printer').block_reason()



class TelnetTests(unittest.TestCase):
    def wlan(self, status='OFF', channel='0'):
        return ('SHOW WLAN\r\nComm.mode           Infrastructure\r\n'
                'Ssid                HOME\r\nAuthentication      (Unknown)\r\n'
                'Encryption          (Unknown)\r\nStatus              '+status+'\r\n'
                '                    Receiving Signal = 0\r\n'
                '                    Operating Channel = '+channel+'\r\n\r\nLocal> ')

    def test_live_off_signature_and_healthy_unknown_auth(self):
        from telnet_client import parse_wlan
        self.assertTrue(parse_wlan(self.wlan()).incomplete)
        self.assertFalse(parse_wlan(self.wlan('11n', '1')).incomplete)
        with self.assertRaises(CheckError):parse_wlan('syntax error')

    def test_login_negotiation_and_read_only_command(self):
        from telnet_client import TelnetSession
        class Socket:
            def __init__(self, chunks):self.chunks=iter(chunks);self.sent=[];self.closed=False
            def settimeout(self, value):pass
            def recv(self, size):return next(self.chunks)
            def sendall(self, value):self.sent.append(value)
            def close(self):self.closed=True
        sock=Socket([b'Welcome. Type <return>, enter password at # prompt\r\n',
                     b'\xff',b'\xfb',b'\x01\r\n# ',
                     b'Brother console\r\nEnter username> ',b'checker\r\nLocal> ',
                     self.wlan().encode()])
        with patch('telnet_client.socket.create_connection',return_value=sock):
            with TelnetSession('127.0.0.1','fake') as session:
                self.assertTrue(session.wlan().incomplete)
        self.assertTrue(sock.closed)
        self.assertIn(b'SHOW WLAN\r\n',sock.sent)
        self.assertIn(bytes([255,253,1]),sock.sent)
        self.assertNotIn(b'INITIALIZE\r\n',sock.sent)



PORT = """SHOW PORT
Port                               Type
 *P1                               Parallel
 Status = Sleep
Off line           No       Paper out         No
Operator needed    No       Paper Jam         No
Toner Low          No       Print overrun     No
Memory full        No       Busy              No
Waiting for data   Yes      Warming up        No
Cover open         No       Printing          No
Other channel busy No       Paper output full No
Local>
"""


class TelnetIdleTests(unittest.TestCase):
    def test_sleep_and_no_current_job(self):
        result = parse_idle('Current Job String: None', PORT)
        self.assertTrue(result['idle'])
        self.assertIsNone(result['pending_jobs'])
        self.assertFalse(result['current_job_present'])

    def test_busy_printing_or_current_job_blocks(self):
        for label in ['Busy', 'Printing', 'Other channel busy', 'Warming up', 'Off line']:
            import re
            changed = re.sub(r'('+re.escape(label)+r'\s+)No', r'\g<1>Yes', PORT)
            self.assertFalse(parse_idle('Current Job String: None', changed)['idle'], label)
        result = parse_idle('Current Job String: Some confidential job', PORT)
        self.assertFalse(result['idle'])
        self.assertNotIn('confidential', str(result))

    def test_unknown_or_missing_flags_block(self):
        with self.assertRaises(CheckError):parse_idle('garbage', PORT)
        with self.assertRaises(CheckError):parse_idle('Current Job String: None', 'Status = Sleep')
        self.assertFalse(parse_idle('Current Job String: None', PORT.replace('Sleep', 'Unknown'))['idle'])


class TelnetResetTests(unittest.TestCase):
    def session(self, response):
        from unittest.mock import MagicMock
        session = MagicMock()
        session.__enter__.return_value = session
        session.expect.return_value = response
        session.command.return_value = 'INitialize               Reset unit'
        return session

    def test_prepare_is_help_only(self):
        client = TelnetClient('127.0.0.1', 'fake')
        session = self.session('')
        with patch.object(client, 'session', return_value=session):
            self.assertEqual(client.prepare_restart(), 'INITIALIZE')
        session.command.assert_called_once_with('HELP INITIALIZE')
        session.socket.sendall.assert_not_called()

    def test_unit_reset_then_exit_only_if_explicitly_instructed(self):
        client = TelnetClient('127.0.0.1', 'fake')
        for reply, expected in [('Please type EXIT to reset the unit.\r\nLocal> ',
                                 [b'INITIALIZE\r\n', b'EXIT\r\n']),
                                ('Resetting unit\r\n', [b'INITIALIZE\r\n'])]:
            session = self.session(reply)
            with patch.object(client, 'session', return_value=session):
                self.assertTrue(client.request_restart('INITIALIZE')['accepted'])
            self.assertEqual([c.args[0] for c in session.socket.sendall.call_args_list], expected)

    def test_unknown_response_and_timeout_do_not_retry_or_factory_reset(self):
        client = TelnetClient('127.0.0.1', 'fake')
        for reply in ['Local> ', 'Error: denied\r\nLocal> ']:
            session = self.session(reply)
            with patch.object(client, 'session', return_value=session):
                with self.assertRaises(CheckError):client.request_restart('INITIALIZE')
            session.socket.sendall.assert_called_once_with(b'INITIALIZE\r\n')
        session = self.session('');session.expect.side_effect = TimeoutError()
        with patch.object(client, 'session', return_value=session):
            with self.assertRaises(TimeoutError):client.request_restart('INITIALIZE')
        session.socket.sendall.assert_called_once_with(b'INITIALIZE\r\n')


if __name__ == '__main__':unittest.main()
