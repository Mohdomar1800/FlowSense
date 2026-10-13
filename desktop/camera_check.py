"""Check camera phone detection with your own webcam, setup and lighting.

Prints, about twice a second, what FlowSense sees: whether a face is found, your head angle, the best
phone confidence, and whether that frame would count as "phone in use". Nothing is saved or sent.

    python desktop/camera_check.py            # 30 seconds
    python desktop/camera_check.py --seconds 60 --camera 1

Try: look at the screen, look down as if writing notes, then pick up your phone and use it.
"""

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent.camera.models import ensure_models  # noqa: E402
from agent.camera.phone_monitor import LOOK_DOWN_DELTA, PHONE_SCORE, PhoneMonitor  # noqa: E402
from agent.camera.vision import FrameAnalyzer  # noqa: E402
from agent.camera.worker import _open_camera  # noqa: E402


class _PrintingServer:
    def log_distraction(self, subject, reason, started_at, source="screen"):
        print(f"  >>> would log a distraction: {subject} (started {started_at:%H:%M:%S})")
        return 1

    def end_distraction(self, distraction_id, at):
        print("  >>> would end the distraction (phone put away)")


class _PrintingNotifier:
    def notify(self, title, message):
        print(f"  >>> notification: {title}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--camera", type=int, default=0, help="camera index (default 0)")
    args = parser.parse_args()

    print("Loading models (downloaded once, verified by checksum)...")
    analyzer = FrameAnalyzer(*ensure_models())
    capture = _open_camera(args.camera)
    if capture is None:
        print("Could not open the camera. Is another app using it?")
        return 1

    monitor = PhoneMonitor(_PrintingServer(), _PrintingNotifier())
    print(f"Running for {args.seconds}s. Frames are analyzed in memory only.\n")
    print(f"{'time':>8}  {'face':>4}  {'head':>11}  {'phone':>5}  verdict   ({'ms':>3})")
    deadline = time.monotonic() + args.seconds
    try:
        while time.monotonic() < deadline:
            started = time.monotonic()
            capture.grab()
            ok, frame = capture.read()
            if not ok:
                print("Camera stopped delivering frames.")
                return 1
            obs = analyzer.analyze(frame)
            elapsed_ms = (time.monotonic() - started) * 1000
            monitor.observe(datetime.now(UTC), obs)

            phone = max((d.score for d in obs.phones), default=0.0)
            if obs.head_pitch is None:
                head = "-"
            else:
                tilt = obs.head_pitch - monitor.baseline_pitch()
                head = f"{obs.head_pitch:.2f} {'down' if tilt >= LOOK_DOWN_DELTA else 'level'}"
            in_use = monitor.frames[-1][1] if monitor.frames else False
            verdict = "PHONE" if in_use else ("phone?" if phone >= PHONE_SCORE else "ok")
            print(
                f"{datetime.now():%H:%M:%S}  {'yes' if obs.face else 'no':>4}  {head:>11}  {phone:>5.2f}"
                f"  {verdict:<8}  ({elapsed_ms:>3.0f})"
            )
            time.sleep(max(0.0, 0.5 - (time.monotonic() - started)))
    finally:
        capture.release()
        print("\nCamera released.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
