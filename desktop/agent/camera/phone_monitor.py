"""Decides when the camera sees real phone use (as opposed to note-taking or a phone lying around).

Pure logic: it receives one Observation per analyzed frame and talks to the server/notifier passed
in, so every rule is unit-testable without a camera.

A frame counts as "phone in use" when a phone is detected AND the user is engaging with it:
- looking down (head pitched below their own normal screen-viewing angle), or
- holding it near their face, or
- their face isn't visible (head bowed so far the face detector loses it) while a phone is in view.

Writing notes = looking down with no phone in view, so it never counts. A phone that's visible
while the user looks at the screen doesn't count either.

Decisions use a sliding window so single-frame mistakes never trigger anything:
- start: phone in use in >= 60% of the last ~6 seconds of frames
- end:   phone in use in <= 20% of the last ~6 seconds
"""

import statistics
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol


@dataclass(frozen=True)
class Box:
    """Normalized to the frame: (x, y) is the top-left corner; all values 0..1."""

    x: float
    y: float
    w: float
    h: float

    @property
    def center(self) -> tuple[float, float]:
        return self.x + self.w / 2, self.y + self.h / 2


@dataclass(frozen=True)
class Detection:
    box: Box
    score: float


@dataclass(frozen=True)
class Observation:
    face: Box | None = None
    # Where the nose sits between the eyes (0) and the mouth (1). Grows as the head tilts down.
    head_pitch: float | None = None
    phones: tuple[Detection, ...] = field(default_factory=tuple)


class Server(Protocol):
    def log_distraction(self, subject: str, reason: str, started_at: datetime, source: str = "screen") -> int: ...
    def end_distraction(self, distraction_id: int, at: datetime) -> None: ...


class Notifier(Protocol):
    def notify(self, title: str, message: str) -> None: ...


PHONE_SCORE = 0.45
WINDOW = timedelta(seconds=6)
MIN_FRAMES = 4
START_RATIO = 0.6
END_RATIO = 0.2
# Head pitch more than this above the user's screen-viewing value counts as looking down.
LOOK_DOWN_DELTA = 0.12
DEFAULT_PITCH = 0.55
BASELINE_SAMPLES = 600  # ~5 minutes at 2 frames per second
MIN_BASELINE_SAMPLES = 10
REMIND_EVERY = timedelta(minutes=2)


class PhoneMonitor:
    def __init__(self, server: Server, notifier: Notifier) -> None:
        self.server = server
        self.notifier = notifier
        self.frames: deque[tuple[datetime, bool]] = deque()
        self.pitch_history: deque[float] = deque(maxlen=BASELINE_SAMPLES)
        self.episode_id: int | None = None
        self.episode_started: datetime | None = None
        self.last_reminder: datetime | None = None
        self.accepted = False  # the user dismissed the current episode

    # ---------- per-frame input ----------

    def observe(self, now: datetime, observation: Observation) -> None:
        in_use = self._phone_in_use(observation)
        if observation.head_pitch is not None and not observation.phones:
            # The user's normal head angle is learned from phone-free frames (mostly looking at the screen).
            self.pitch_history.append(observation.head_pitch)
        self.frames.append((now, in_use))
        while self.frames and now - self.frames[0][0] > WINDOW:
            self.frames.popleft()
        self._decide(now)

    def baseline_pitch(self) -> float:
        """The user's head angle when looking at the screen.

        Taken as the 20th percentile (the most upright common pose) rather than the median, so someone
        who spends most of their time writing notes doesn't end up with "looking down" as their normal.
        """
        if len(self.pitch_history) < MIN_BASELINE_SAMPLES:
            return DEFAULT_PITCH
        return statistics.quantiles(self.pitch_history, n=5, method="inclusive")[0]

    def _phone_in_use(self, obs: Observation) -> bool:
        phones = [d for d in obs.phones if d.score >= PHONE_SCORE]
        if not phones:
            return False
        if obs.face is None:
            return True
        if obs.head_pitch is not None and obs.head_pitch - self.baseline_pitch() >= LOOK_DOWN_DELTA:
            return True
        return any(_near_face(d.box, obs.face) for d in phones)

    # ---------- decisions ----------

    def _ratio(self) -> float | None:
        if len(self.frames) < MIN_FRAMES:
            return None
        return sum(in_use for _, in_use in self.frames) / len(self.frames)

    def _decide(self, now: datetime) -> None:
        ratio = self._ratio()
        if ratio is None:
            return
        if self.episode_id is None and not self.accepted:
            if ratio >= START_RATIO:
                self._start_episode(now)
        elif ratio <= END_RATIO:
            self._end_episode(now)
        elif self.episode_id is not None and self.last_reminder and now - self.last_reminder >= REMIND_EVERY:
            self.last_reminder = now
            minutes = max(1, int((now - self.episode_started).total_seconds() // 60))
            self.notifier.notify("Still on your phone", f"{minutes} min so far. Put it face down and get back to it.")

    def _start_episode(self, now: datetime) -> None:
        started = next((t for t, in_use in self.frames if in_use), now)
        try:
            self.episode_id = self.server.log_distraction("Phone", "Phone in use", started, source="camera")
        except Exception:
            return  # retried on the next frame
        self.episode_started = started
        self.last_reminder = now
        self.notifier.notify("Phone down?", "Looks like you picked up your phone. Your session is still running.")

    def _end_episode(self, now: datetime) -> None:
        if self.episode_id is not None:
            try:
                self.server.end_distraction(self.episode_id, now)
            except Exception:
                pass  # stays logged without a duration
        self.episode_id = None
        self.episode_started = None
        self.last_reminder = None
        self.accepted = False

    # ---------- control ----------

    def dismissed(self, distraction_id: int) -> None:
        """The user said this isn't phone use: stop flagging until the phone is out of view again."""
        if distraction_id == self.episode_id:
            self.episode_id = None
            self.last_reminder = None
            self.accepted = True

    def stop(self, now: datetime) -> None:
        """Camera tracking stopped (session paused/ended, switched off): close any open episode."""
        self._end_episode(now)
        self.frames.clear()


def _near_face(phone: Box, face: Box) -> bool:
    """Phone held up near the face: its center lies within the face box widened sideways and extended below."""
    cx, cy = phone.center
    return (face.x - face.w) <= cx <= (face.x + 2 * face.w) and (face.y - 0.5 * face.h) <= cy <= (face.y + 2 * face.h)
