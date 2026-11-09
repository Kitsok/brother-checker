# Validation notes — 9 November 2026

## HACS integration packaging

- Added one integration under `custom_components/brother_wifi_checker/`, root
  `hacs.json`, manifest, English translations, and the required root brand icon.
- HACS/HA JSON metadata parses; the icon is a 256×256 PNG; `git diff --check`
  reports no whitespace errors.
- Shared Telnet/status/recovery modules now live inside the HACS component;
  root compatibility modules retain the standalone CLI imports.
- Home Assistant installation and live integration setup were not performed.
  The new integration code and existing unit suite were not runtime-tested in
  this packaging pass. No printer restart was requested.
- The manifest links to `Kitsok/brother-checker`. No push or publication was
  performed.

The implementation is now Telnet-only. Earlier web/IPP code and tests, including
HTML parsers and certificate/protocol options, were removed by explicit user request.

- Repository initialized; secret.py contains password/printer_ip, mode0600, ignored.
- Runtime source has no HTTP/TLS/IPP/SNMP clients, subprocess, ping, SSH or router calls.
- All 20 mocked tests pass for Telnet protocol/parsing, idle guards, reset response
  handling, conditional EXIT, cooldown/limits, locking and no reset retries.
- Live status: reachable via Telnet, SHOW WLAN OFF/channel0/signal0, mismatch=true.
- Live idle: SHOW JOB Current Job String=None; SHOW PORT Status=Sleep, Busy=No,
  Printing=No, Other channel busy=No; required error flags all No. idle=true.
- Live dry-run: three consecutive mismatch samples, idle=true, would_restart=true.
  No INITIALIZE/EXIT or state-changing printer commands were sent.
- Telnet does not expose a complete held-job queue through these commands. The
  application reports pending_jobs=null and explicit limited queue visibility.
- HELP INITIALIZE advertises Reset unit. Factory defaults is a separate SET DEFAULT
  branch, never used. Reset handling accepts explicit resetting acknowledgement or
  sends EXIT only if explicitly instructed after INITIALIZE. These branches are
  mock-tested; actual Telnet reboot on this printer is not yet hardware-tested.
- No acknowledge/refresh/reconnect command was found in inspected normal HELP
  branches; CLEAR NOTIFICATION deletes email recipients. No hidden debug modes used.

The blinking condition was reproduced by a user-authorized one-off printer Wi-Fi
registration kick on border at 19:09:25, outside this application. User confirmed
blinking and restored reachability. Investigation scripts/help output remain in
../temp, separate from this application's runtime. All later live validations use
Telnet only.

Post-restart verification removed by explicit user request. Both run and restart
exit after the single reset request: code0 for acknowledged, code3 for uncertain.
No post-reset sleep/status polling or verification-timeout option remains. Tests
verify no additional observation is requested after accepted or uncertain reset.
