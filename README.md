# Brother Wi-Fi Checker

This repository contains a Home Assistant custom integration for the Brother
DCP-L3520CDW and a standalone one-shot checker for local diagnosis. The HA
integration is packaged for installation as a HACS custom repository. It talks
directly to the printer over Telnet; it does not connect to the router.

## Home Assistant integration

### Install from HACS

After this repository is public on GitHub:

1. In HACS, open **Integrations** and choose **Custom repositories**.
2. Add `https://github.com/Kitsok/brother-checker` with category **Integration**.
3. Install **Brother Wi-Fi Checker**, then restart Home Assistant.
4. Open **Settings → Devices & services → Add integration**, search for
   **Brother Wi-Fi Checker**, and enter the printer host, Telnet password,
   connection timeout, and polling interval.

Automatic recovery is off by default. To opt in after setup, open the
integration's **Configure** dialog and enable **Automatic recovery**.

The repository has one HACS integration at
`custom_components/brother_wifi_checker/`. `hacs.json` and the integration
manifest are included. For local development, copy that directory under the HA
configuration's `custom_components/` directory, then restart HA.

### Entities and behavior

- **Telnet reachable** reports whether the printer answered the latest Telnet
  status or idle query.
- **Wi-Fi status incomplete** turns on when `SHOW WLAN` reports `OFF` and
  channel `0`, the state observed while the printer's Wi-Fi button blinked.
  This is an inferred diagnostic signal, not a direct reading of the physical
  button.
- Wi-Fi sensors expose SSID, mode, channel, signal, authentication, and
  encryption as reported by the printer.
- **Printer reports idle** and the port/job sensors expose the current job and
  port flags. The device does not expose a full held-job queue over these
  commands, so `pending_jobs` remains unknown.
- **Guarded restart** is an explicit button. It checks the current status and
  idle/port flags, checks a 30-minute cooldown and a limit of three attempts in
  24 hours, and reports status before sending one `INITIALIZE` request. The
  action does not poll after the reset request; normal scheduled monitoring
  continues on its next interval. An HA acknowledgement does not prove the
  printer completed its reboot.
- **Automatic recovery** is an opt-in integration option, disabled by default.
  When a poll finds the Telnet-reported Wi-Fi fault while Telnet is reachable,
  HA runs the same guarded recovery policy as the CLI: three fault samples ten
  seconds apart with the same SSID, idle/port checks, the persisted cooldown
  and daily limit, a final status/idle check, and one reset request. Manual and
  automatic HA resets share the same lock and budget. A skipped or uncertain
  request is not retried blindly, and the action performs no immediate
  post-reset polling.

The live reset command has not been validated on this printer. Use the button
only when its restart behavior is acceptable. A print job may arrive between
the idle check and reset, and the Telnet interface cannot report all held jobs.

### Connection and credential notes

Enable Telnet on the printer before adding it. Telnet has no transport
encryption, so the administrator password and commands travel in clear text on
the local network. HA stores the entered credentials in its config-entry
storage. Restrict network access to the printer and HA accordingly.

Polling uses a blocking standard-library Telnet client in Home Assistant's
executor, not HA's event loop. The default interval is 60 seconds; the allowed
range is 30–3600 seconds. The default socket timeout is 10 seconds.

## Standalone checker

Python 3.10+, standard library only. All network traffic goes directly to the
printer's Telnet port 23. The ignored local `secret.py` supplies `password` and
`printer_ip`:

```python
password = "your printer administrator password"
printer_ip = "printer IP address"
```

```bash
python3 checker.py --check-status
python3 checker.py --check-idle
python3 checker.py --dry-run
python3 checker.py
python3 checker.py --request-restart
```

Stages are `status`, `idle`, `run` (default), and `restart`. The one-shot `run`
stage requires three matching `OFF`/channel-0 observations ten seconds apart.
Both CLI restart paths check idle state, enforce the same 30-minute cooldown
and three-per-rolling-day limit in the CLI's local state file, report before
restarting, send one request, and exit without post-restart polling. The CLI
budget is separate from HA's budget file. Avoid running CLI reset mode and HA
automatic recovery at the same time, as their budgets are separate.

The Telnet client uses only read-only `SHOW` and `HELP` commands before reset.
It sends `EXIT` only if the printer explicitly requests it after `INITIALIZE`.
It never sends factory-reset, configuration, firmware, or hidden debug
commands. An ambiguous reset response is not retried.

See [VALIDATION.md](VALIDATION.md) for development checks and limitations.
