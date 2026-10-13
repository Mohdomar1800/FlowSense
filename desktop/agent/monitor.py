"""Decides when on-screen activity becomes a distraction.

Pure logic with no OS or network access: the server and notifier are passed in, and time is
an explicit argument, so every rule here is unit-testable.

Rules:
- Each time the foreground window changes, it is reported to the server, which classifies it.
- Off-task (distracting) windows count as a distraction only after the grace period, so a quick
  glance at a chat doesn't. Hopping between distracting windows keeps the same clock and episode.
- When the distraction is logged the user is notified, and reminded again every few minutes.
- Returning to a focus or neutral window ends the episode, recording how long it lasted.
- No keyboard/mouse input for a while on a non-focus window logs an inactivity distraction.
  (Watching a lecture or reading in a focus app is fine without input.)
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from agent.window_source import Window


@dataclass(frozen=True)
class Verdict:
    category: str  # "focus" | "neutral" | "distracting"
    subject: str
    reason: str


class Server(Protocol):
    def report_activity(self, window: Window, at: datetime) -> Verdict: ...
    def log_distraction(self, subject: str, reason: str, started_at: datetime) -> int: ...
    def end_distraction(self, distraction_id: int, at: datetime) -> None: ...
    def log_inactivity(self, minutes: int, started_at: datetime) -> None: ...


class Notifier(Protocol):
    def notify(self, title: str, message: str) -> None: ...


DISTRACTING = "distracting"
FOCUS = "focus"


class FocusMonitor:
    REMIND_EVERY = timedelta(minutes=2)
    IDLE_THRESHOLD = timedelta(minutes=5)
    RETRY_AFTER_ERROR = timedelta(seconds=5)

    def __init__(self, server: Server, notifier: Notifier, grace_seconds: int = 15) -> None:
        self.server = server
        self.notifier = notifier
        self.grace = timedelta(seconds=grace_seconds)
        self._clear()

    def _clear(self) -> None:
        self.window: Window | None = None
        self.verdict: Verdict | None = None
        self.off_task_since: datetime | None = None
        self.episode_id: int | None = None
        self.last_reminder: datetime | None = None
        self.idle_logged = False
        self.retry_at: datetime | None = None

    @property
    def engaged(self) -> bool:
        return self.window is not None or self.episode_id is not None

    def set_grace(self, seconds: int) -> None:
        self.grace = timedelta(seconds=max(0, seconds))

    def dismissed(self, distraction_id: int) -> None:
        """The user said the current distraction isn't one: accept this window until they switch away."""
        if distraction_id != self.episode_id or self.verdict is None:
            return
        self.episode_id = None
        self.last_reminder = None
        self.off_task_since = None
        self.verdict = Verdict("neutral", self.verdict.subject, "You said this isn't a distraction")

    def stop(self, now: datetime) -> None:
        """Tracking stopped (session paused/ended, tracking turned off): close any open episode."""
        self._end_episode(now)
        self._clear()

    def tick(self, now: datetime, window: Window | None, idle_seconds: float | None = None) -> None:
        window = window or Window(app="", title="")
        if window != self.window and (self.retry_at is None or now >= self.retry_at):
            self._on_window_change(now, window)
        if self.verdict is not None and self.verdict.category == DISTRACTING:
            self._check_distraction(now)
        self._check_idle(now, idle_seconds)

    # ------------------------------------------------------------------

    def _on_window_change(self, now: datetime, window: Window) -> None:
        try:
            verdict = self.server.report_activity(window, now)
        except Exception:
            self.retry_at = now + self.RETRY_AFTER_ERROR  # server unreachable: try again shortly
            return
        self.retry_at = None
        was_off_task = self.verdict is not None and self.verdict.category == DISTRACTING
        self.window, self.verdict = window, verdict

        if verdict.category == DISTRACTING:
            if not was_off_task:
                self.off_task_since = now
        else:
            if self.episode_id is not None:
                self.notifier.notify("Welcome back", "Nice, you're back on track.")
            self._end_episode(now)
            self.off_task_since = None

    def _check_distraction(self, now: datetime) -> None:
        assert self.off_task_since is not None and self.verdict is not None
        elapsed = now - self.off_task_since
        if self.episode_id is None:
            if elapsed < self.grace:
                return
            try:
                self.episode_id = self.server.log_distraction(
                    self.verdict.subject, self.window.title if self.window else "", self.off_task_since
                )
            except Exception:
                return  # retried on the next tick
            self.last_reminder = now
            self.notifier.notify("Back to focus?", f"You've drifted to {self.verdict.subject}. {self.verdict.reason}.")
        elif self.last_reminder is not None and now - self.last_reminder >= self.REMIND_EVERY:
            self.last_reminder = now
            minutes = max(1, int(elapsed.total_seconds() // 60))
            self.notifier.notify("Still distracted", f"{minutes} min on {self.verdict.subject} so far.")

    def _end_episode(self, now: datetime) -> None:
        if self.episode_id is None:
            return
        try:
            self.server.end_distraction(self.episode_id, now)
        except Exception:
            pass  # the distraction stays logged; only its duration is unknown
        self.episode_id = None
        self.last_reminder = None

    def _check_idle(self, now: datetime, idle_seconds: float | None) -> None:
        if idle_seconds is None:
            return
        if idle_seconds < 5:
            self.idle_logged = False
            return
        on_focus = self.verdict is not None and self.verdict.category == FOCUS
        if self.idle_logged or on_focus or idle_seconds < self.IDLE_THRESHOLD.total_seconds():
            return
        try:
            self.server.log_inactivity(int(idle_seconds // 60), now - timedelta(seconds=idle_seconds))
        except Exception:
            return
        self.idle_logged = True
        self.notifier.notify("Still there?", "No activity for a while. Pause the session if you're taking a break.")
