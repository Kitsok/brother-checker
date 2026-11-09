"""Local-file restart budget. Future integrations can provide another store."""
import fcntl
import json
import os
from pathlib import Path
import time
from .brother import CheckError


class FileState:
    def __init__(self, path, identity, cooldown=1800, daily_limit=3, clock=time.time):
        self.path, self.identity = Path(path), identity
        self.cooldown, self.daily_limit, self.clock = cooldown, daily_limit, clock
        self.lock = None

    def __enter__(self):
        self.lock = open(str(self.path) + '.lock', 'a')
        os.chmod(self.lock.name, 0o600)
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.lock.close()
            raise CheckError('Another recovery invocation is running') from exc
        return self

    def __exit__(self, *args):
        self.lock.close()

    def _read(self):
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text())
            if not isinstance(data, dict):
                raise ValueError()
            for key, entries in data.items():
                if not isinstance(key, str) or not isinstance(entries, list):
                    raise ValueError()
                if any(type(x) not in (int, float) or not 0 <= x < float('inf') for x in entries):
                    raise ValueError()
            return data
        except (ValueError, TypeError) as exc:
            raise CheckError('Invalid cooldown state; refusing restart') from exc

    def block_reason(self):
        entries = self._read().get(self.identity, [])
        now = self.clock()
        if entries and now - max(entries) < self.cooldown:
            return 'Restart cooldown is active (or system clock moved backwards)'
        if sum(now - x < 86400 for x in entries) >= self.daily_limit:
            return 'Rolling 24-hour restart limit reached'
        return None

    def reserve(self):
        if self.lock is None or self.lock.closed:
            raise CheckError('Recovery state must be locked before reserving a restart')
        reason = self.block_reason()
        if reason:
            raise CheckError(reason)
        data = self._read(); now = self.clock()
        data[self.identity] = [x for x in data.get(self.identity, []) if now - x < 86400] + [now]
        tmp = Path(str(self.path) + '.tmp')
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as stream:
            os.chmod(tmp, 0o600)
            json.dump(data, stream); stream.flush(); os.fsync(stream.fileno())
        os.replace(tmp, self.path)
