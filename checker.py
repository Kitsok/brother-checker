#!/usr/bin/env python3
"""Printer-only single-shot checker. See README.md before automated recovery."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from brother import Checker, CheckError
from recovery import Recovery
from state import FileState
from telnet_client import TelnetClient


def positive_float(value):
    import math
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('must be finite and greater than zero')
    return number


def report(event, data):
    print(json.dumps({'time': datetime.now(timezone.utc).isoformat(),
                      'event': event, **data}), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--stage', choices=['run', 'status', 'idle', 'restart'], default='run')
    modes.add_argument('--check-status', dest='stage', action='store_const', const='status')
    modes.add_argument('--check-idle', dest='stage', action='store_const', const='idle')
    modes.add_argument('--request-restart', dest='stage', action='store_const', const='restart')
    parser.add_argument('--dry-run', action='store_true', help='never prepare or request restart')
    parser.add_argument('--samples', type=int, default=3, help='consecutive mismatch checks (minimum 2)')
    parser.add_argument('--interval', type=positive_float, default=10)
    parser.add_argument('--timeout', type=positive_float, default=10, help='Telnet timeout')
    parser.add_argument('--cooldown', type=positive_float, default=1800, help='seconds between restart attempts')
    parser.add_argument('--daily-limit', type=int, default=3, help='maximum attempts in rolling 24 hours')
    parser.add_argument('--state-file', type=Path, default=Path(__file__).resolve().parent / '.checker-state.json')
    args = parser.parse_args(argv)
    if args.samples < 2 or args.daily_limit < 1:
        parser.error('samples >= 2 and daily-limit >= 1 required')
    try:
        # This is the only configuration import; library modules remain reusable.
        from secret import password, printer_ip
        printer = TelnetClient(printer_ip, password, args.timeout)
        checker = Checker(printer)
        store = FileState(args.state_file, printer_ip, args.cooldown, args.daily_limit)
        recovery = Recovery(checker, store, report)
        kwargs = dict(stage=args.stage, samples=args.samples, interval=args.interval,
                      dry_run=args.dry_run)
        if args.stage in ('status', 'idle'):
            return recovery.run(**kwargs)
        with store:
            return recovery.run(**kwargs)
    except KeyboardInterrupt:
        report('error', {'message': 'Interrupted; any submitted restart is not cancelled'})
        return 3
    except Exception as exc:
        # Never print raw console responses or credential-bearing exceptions.
        message = str(exc) if isinstance(exc, (CheckError, ValueError, ImportError)) else type(exc).__name__
        report('error', {'message': message})
        return 3


if __name__ == '__main__':
    sys.exit(main())
