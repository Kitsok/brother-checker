"""Brother Telnet client: status, current-job/port idle checks and unit reset."""
import re
import socket
import time
from brother import CheckError, WirelessStatus


def parse_wlan(text):
    def field(pattern):
        match = re.search(pattern, text, re.M)
        if not match:
            raise CheckError('Unrecognized Telnet SHOW WLAN response')
        return match.group(1).strip()
    ssid = field(r'^Ssid[ \t]+([^\r\n]*)')
    status = field(r'^Status[ \t]+([^\r\n]+)')
    channel = int(field(r'^\s*Operating Channel\s*=\s*(\d+)\s*$'))
    signal = field(r'^\s*Receiving Signal\s*=\s*([^\r\n]+)')
    auth = field(r'^Authentication[ \t]+([^\r\n]*)')
    encryption = field(r'^Encryption[ \t]+([^\r\n]*)')
    # The console does not recognize the WPA3 enum; do not treat (Unknown) as
    # failure when operating mode/channel remain valid.
    mode = '' if status.upper() == 'OFF' else status
    if (mode and channel <= 0) or (not mode and channel != 0):
        raise CheckError('Contradictory Telnet channel/mode response')
    return WirelessStatus(ssid, auth, encryption, mode, channel, signal)


class TelnetSession:
    def __init__(self, host, password, timeout=10):
        if '\r' in password or '\n' in password:
            raise CheckError('Telnet password contains a newline')
        self.host, self.password, self.timeout = host, password, timeout
        self.socket = None
        self.pending = bytearray()
        self.phase = 'greeting'

    def __enter__(self):
        self.socket = socket.create_connection((self.host, 23), self.timeout)
        try:
            self.expect(r'password at # prompt\s*$')
            self.phase = 'password prompt'
            self.socket.sendall(b'\r\n')
            try:
                self.expect(r'(?:^|\r?\n)#\s*$', duration=0.5)
            except CheckError as exc:
                if 'timed out' not in str(exc):
                    raise
                # This console requires another return after ECHO/SGA negotiation.
                self.socket.sendall(b'\r\n')
                self.expect(r'(?:^|\r?\n)#\s*$')
            self.phase = 'password login'
            self.socket.sendall(self.password.encode('utf-8') + b'\r\n')
            result = self.expect(r'(?:Enter username>|Local>|#)\s*$')
            if 'Enter username>' in result:
                self.phase = 'username'
                self.socket.sendall(b'checker\r\n')
                result = self.expect(r'(?:Local>|#)\s*$')
            if not result.rstrip().endswith('Local>'):
                raise CheckError('Telnet login rejected')
            return self
        except BaseException:
            self.socket.close()
            raise

    def __exit__(self, *args):
        self.socket.close()

    def _decode(self, data):
        """Handle split IAC negotiations; accept echo/SGA, refuse other options."""
        self.pending.extend(data)
        output = bytearray()
        while self.pending:
            if self.pending[0] != 255:
                output.append(self.pending.pop(0)); continue
            if len(self.pending) < 2:
                break
            command = self.pending[1]
            if command == 255:
                output.append(255);del self.pending[:2];continue
            if command in (251, 252, 253, 254):
                if len(self.pending) < 3:break
                option = self.pending[2];del self.pending[:3]
                if command == 251:
                    self.socket.sendall(bytes([255, 253 if option in (1, 3) else 254, option]))
                elif command == 253:
                    self.socket.sendall(bytes([255, 251 if option == 3 else 252, option]))
            elif command == 250:
                end = self.pending.find(b'\xff\xf0', 2)
                if end < 0:break
                del self.pending[:end+2]
            else:
                del self.pending[:2]
        if len(self.pending) > 8192:
            raise CheckError('Unterminated Telnet negotiation')
        return output.decode('ascii', errors='replace')

    def expect(self, pattern, duration=None):
        end = time.monotonic() + (self.timeout if duration is None else duration)
        output = ''
        while time.monotonic() < end:
            self.socket.settimeout(max(.01, end - time.monotonic()))
            try:
                data = self.socket.recv(8192)
            except socket.timeout as exc:
                raise CheckError('Telnet response timed out during ' + self.phase) from exc
            if not data:
                raise CheckError('Telnet disconnected before expected prompt')
            output += self._decode(data)
            output = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', output)
            if len(output) > 65536:
                raise CheckError('Telnet response too large')
            if re.search(pattern, output):
                return output
        raise CheckError('Telnet response timed out during ' + self.phase)

    def command(self, command):
        if command not in {'SHOW WLAN', 'SHOW JOB', 'SHOW PORT', 'HELP INITIALIZE'}:
            raise CheckError('Unapproved read-only Telnet command')
        self.phase = command
        self.socket.sendall(command.encode('ascii') + b'\r\n')
        return self.expect(r'(?:^|\r?\n)Local>\s*$')

    def wlan(self):
        return parse_wlan(self.command('SHOW WLAN'))


def parse_idle(job_text, port_text):
    job = re.search(r'^Current Job String:[ \t]*([^\r\n]*)', job_text, re.M)
    status = re.search(r'^\s*Status\s*=[ \t]*([^\r\n]+)', port_text, re.M)
    if not job or not status:
        raise CheckError('Unrecognized Telnet job/port response')
    labels = ['Busy', 'Printing', 'Other channel busy', 'Warming up', 'Off line',
              'Operator needed', 'Paper Jam', 'Memory full', 'Cover open',
              'Paper out', 'Print overrun', 'Paper output full']
    flags = {}
    for label in labels:
        pattern = r'(?:^|\s{2,})' + r'\s+'.join(map(re.escape, label.split())) + r'\s+(Yes|No)\b'
        match = re.search(pattern, port_text, re.I | re.M)
        if not match:
            raise CheckError('Required Telnet port flag missing: ' + label)
        flags[label] = match.group(1).lower() == 'yes'
    current_job = job.group(1).strip()
    if not current_job:
        raise CheckError('Current job state is blank/unknown')
    state = status.group(1).strip()
    no_current_job = current_job.lower() == 'none'
    reasons = [label for label, value in flags.items() if value]
    if not no_current_job:
        reasons.append('current job present')
    if state.lower() not in {'idle', 'ready', 'sleep', 'deep sleep'}:
        reasons.append('port state is not idle/ready/sleep')
    return {'idle': not reasons, 'state': state, 'reasons': reasons or ['none'],
            'current_job_present': not no_current_job,
            'pending_jobs': None, 'queue_visibility': 'current job and port flags only',
            'flags': flags}


class TelnetClient:
    def __init__(self, host, password, timeout=10):
        if not re.fullmatch(r'[A-Za-z0-9.-]+', host):
            raise ValueError('Printer host must be an IPv4 address or hostname')
        self.host, self.password, self.timeout = host, password, timeout

    def session(self):
        return TelnetSession(self.host, self.password, self.timeout)

    def wireless_status(self):
        with self.session() as session:
            return session.wlan()

    def idle_status(self):
        with self.session() as session:
            return parse_idle(session.command('SHOW JOB'), session.command('SHOW PORT'))

    def prepare_restart(self):
        # Read help only; no reset/configuration is sent before the final report.
        with self.session() as session:
            help_text = session.command('HELP INITIALIZE')
            if not re.search(r'INitialize\s+Reset unit', help_text, re.I):
                raise CheckError('Unit-reset command not confirmed by device help')
        return 'INITIALIZE'

    def request_restart(self, confirmation):
        if confirmation != 'INITIALIZE':
            raise CheckError('Invalid restart preparation')
        with self.session() as session:
            session.phase = 'unit reset'
            # INITIALIZE is the exposed unit reset. Never use SET DEFAULT,
            # CLEAR, firmware update or undocumented debug operations.
            session.socket.sendall(b'INITIALIZE\r\n')
            response = session.expect(r'(?:Local>\s*$|(?:resetting|restarting|reinitializing)[^\r\n]*[\r\n])')
            if re.search(r'(?:unknown|unrecognized|invalid|denied|not permitted|error)', response, re.I):
                raise CheckError('Telnet reset rejected; request will not be retried')
            if re.search(r'(?:type|enter)\s+[\'"]?EXIT\b', response, re.I):
                # Some Brother consoles defer the reset until EXIT. Only send
                # this when explicitly instructed after INITIALIZE.
                session.socket.sendall(b'EXIT\r\n')
                return {'accepted': True, 'message': 'INITIALIZE acknowledged; instructed EXIT sent'}
            if re.search(r'(?:resetting|restarting|reinitializing)', response, re.I):
                return {'accepted': True, 'message': 'Unit reset acknowledged'}
            raise CheckError('Reset acknowledgement unknown; do not blindly retry')
