"""One-shot recovery policy, independent of CLI and persistence implementation."""
import time


class Recovery:
    def __init__(self, checker, store, report, sleep=time.sleep):
        self.checker, self.store, self.report = checker, store, report
        self.sleep = sleep

    def run(self, stage='run', samples=3, interval=10, dry_run=False):
        if stage == 'idle':
            idle = self.checker.printer.idle_status()
            self.report('idle', idle)
            return 0 if idle['idle'] else 2
        observation = self.checker.status()
        self.report('status', observation.to_dict())
        if stage == 'status':
            return 1 if observation.mismatch or not observation.reachable else 0
        if not observation.reachable:
            self.report('skipped', {'reason': 'Printer unavailable'})
            return 2
        if stage == 'run':
            if not observation.mismatch:
                self.report('no_action', {'reason': 'No printer status mismatch'})
                return 0
            for _ in range(samples - 1):
                self.sleep(interval)
                next_observation = self.checker.status()
                self.report('status', next_observation.to_dict())
                if (not next_observation.mismatch or
                        next_observation.wireless.ssid != observation.wireless.ssid):
                    self.report('skipped', {'reason': 'Mismatch did not persist consistently'})
                    return 2
                observation = next_observation
        idle = self.checker.printer.idle_status()
        self.report('idle', idle)
        if not idle['idle']:
            self.report('skipped', {'reason': 'Printer current job/port status is not idle'})
            return 2
        reason = self.store.block_reason()
        if reason:
            self.report('skipped', {'reason': reason})
            return 2
        if dry_run:
            self.report('dry_run', {'would_restart': True,
                                   'reason': 'No restart preparation or request sent'})
            return 0
        confirmation = self.checker.printer.prepare_restart()
        # Recheck directly before the final reset: nothing was made idle by us.
        observation = self.checker.status()
        idle = self.checker.printer.idle_status()
        self.report('before_restart', {'status': observation.to_dict(), 'idle': idle})
        if (not idle['idle'] or not observation.reachable or
                (stage == 'run' and not observation.mismatch)):
            self.report('skipped', {'reason': 'Pre-restart conditions changed'})
            return 2
        # Persist before sending. Even an ambiguous timeout consumes the budget.
        self.store.reserve()
        try:
            accepted = self.checker.printer.request_restart(confirmation)
            self.report('restart_requested', accepted)
        except Exception:
            # Never retry an uncertain reboot. It might already be scheduled.
            self.report('restart_uncertain', {'reason': 'No confirmed acknowledgement; request not retried'})
            return 3
        return 0
