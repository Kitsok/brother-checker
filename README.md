# brother-checker

Single-shot, Telnet-only checker for Brother DCP-L3520CDW, firmware 1.28.
Python 3.10+, standard library only. No HTTP, TLS, IPP, SNMP, ping, SSH/router
access, daemon or Home Assistant integration. All network traffic goes directly
to the printer's Telnet port 23, with a timeout.

## Configuration and commands

`secret.py` is populated with the existing local configuration, mode 0600,
and ignored by Git:

```python
password = "your printer administrator password"
printer_ip = "172.20.20.127"
```

The user has enabled Telnet on the printer. Credentials are unencrypted on the
network. The application never prints passwords, job names or raw console output.

```bash
python3 checker.py --check-status
python3 checker.py --check-idle
python3 checker.py --dry-run
python3 checker.py
python3 checker.py --request-restart
```

Equivalent `--stage` values: `status`, `idle`, `run` (default), `restart`.

- **status**: login over Telnet and `SHOW WLAN`. A successful response establishes
  reachability. OFF/channel 0 is the observed stale Wi-Fi state while the printer
  remains accessible. It is not a direct LED reading or a general network-health
  test. Authentication/encryption `(Unknown)` is normal for this console with
  WPA3 and does not trigger recovery by itself. Timeout, failed login or unknown
  output is an error, never a reason to restart blindly.
- **idle**: `SHOW JOB` and `SHOW PORT`. Requires Current Job String=None, port state
  Idle/Ready/Sleep/Deep Sleep, and all Busy/Printing/Other channel busy/Warming up
  and required error flags=No. Waiting for data=Yes is normal when asleep. Blank,
  missing or unrecognized fields prevent restart. This does not read Wi-Fi state.
- **run**: confirm the same mismatch and SSID three times, ten seconds apart;
  check idle and budget; verify `HELP INITIALIZE` advertises Reset unit; recheck
  status and idle; print/flush `before_restart`; persist the attempt; send exactly
  one `INITIALIZE`. If its response explicitly asks to type/enter EXIT, send one
  `EXIT` to complete it. Otherwise require an explicit resetting/restarting reply.
  An unknown response or connection loss is uncertain and is never retried.
  Exit after the single request/acknowledgement; there is no post-restart polling.
  An acknowledgement does not prove the printer has completed a reboot.
- **restart**: explicit manual restart regardless of mismatch. Still requires
  readable status, idle checks, budget and pre-restart reporting. Requests one
  restart and exits after acknowledgement, without persistence samples or
  post-reset monitoring. Use `--check-status` afterwards.
- **dry-run**: with run/restart, performs checks but never even prepares a restart
  or sends INITIALIZE/EXIT. It does not consume the restart budget.

**Idle-check limit:** normal Telnet output exposes the current job and port flags,
not a complete held-job queue. Output therefore reports `pending_jobs: null` and
`queue_visibility: "current job and port flags only"`, rather than inventing a zero
queue count. A job can also arrive after the last idle check; a reset may abort it.

All output is flushed JSON, one event per line. `before_restart` contains current
Wi-Fi and idle/port status and is emitted before INITIALIZE. Reset is a unit-reset
operation, distinct from SET DEFAULT (factory defaults), which is never sent.
No SET, CLEAR, ZERO, firmware-update or hidden debug commands are implemented.

| Exit | Meaning |
| --- | --- |
| 0 | Healthy/no action, successful dry-run, acknowledged manual request  |
| 1 | Status mismatch |
| 2 | Restart withheld: busy/error, inconsistent samples or cooldown/budget |
| 3 | Transport/login/parsing error or uncertain manual reset acknowledgement |

Options: `--samples` (minimum 2), `--interval`, `--timeout`,
`--cooldown`, `--daily-limit`, `--state-file`. Run `--help` for defaults.

Default budget: 30-minute cooldown and 3 attempts per rolling 24h across invocations,
saved in `.checker-state.json`. A nonblocking lock prevents concurrent recoveries.
Even uncertain final requests consume the budget. Use the same state file for all
invocations; deleting/changing it removes that history. Invalid state blocks reset.
Read-only status/idle stages need no persistent state. The program is not a loop
or scheduled service: it exits after each sequence and never retries reset.

## Files and later Home Assistant reuse

- `checker.py`: CLI, configuration import and composition.
- `brother.py`: transport-independent data classes and observation logic.
- `telnet_client.py`: Telnet negotiation/login, read-only status/idle parsers, reset.
- `recovery.py`: injectable single-shot policy and reporting callback.
- `state.py`: replaceable file-based budget/lock implementation.
- `test_checker.py`: protocol and recovery tests with fake transports.
- `secret.py`: ignored credentials/IP; never committed.

A future integration can call the blocking client in its executor and provide HA
config-entry credentials, storage and events. No HA integration or scheduling is
implemented. No alert acknowledge/Wi-Fi-only reconnect command was found in the
inspected normal console help; CLEAR NOTIFICATION concerns email settings only.
No undocumented debug modes are used.

## Validation

```bash
python3 -m unittest -v
```

20 mocked tests cover split Telnet negotiation, stale/healthy Wi-Fi state, port/job
idle decisions, unknown replies, preserving the status report before reset,
conditional EXIT, transient faults, transport failures, locking and restart budget.
Live status, idle and dry-run also pass against the reproduced blinking condition:
OFF/channel0 while reachable, Current Job String=None, port Sleep, Busy/Printing=No.
No live INITIALIZE/EXIT was sent during development. Telnet restart acknowledgement
handling is mock-tested; actual hardware reset through this path remains untested.
Diagnostic scripts/help captures are retained separately in `../temp/`.
