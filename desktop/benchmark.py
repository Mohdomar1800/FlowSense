"""Measure FlowSense's CPU and memory use in its three typical states.

Runs the real embedded server and focus agent in this process (as the desktop app does, minus the
window) and reports, per phase, the CPU used (% of one core) and the resident memory:

1. idle      - signed in, no session running
2. screen    - a session with screen tracking (reads the real foreground window, read-only)
3. camera    - screen tracking plus phone detection: the real models analyze 2 frames/s
               (a still image stands in for the webcam, so no camera is used)

PostgreSQL must be running. Usage:
    python desktop/benchmark.py [--seconds 30] [--image path/to/photo.jpg]
"""

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import appconfig  # noqa: E402

URL = "http://127.0.0.1:8020"


def rss_mb() -> float:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        # Declare the types: without them the 64-bit process handle is truncated and the call fails.
        get_process = ctypes.windll.kernel32.GetCurrentProcess
        get_process.restype = wintypes.HANDLE
        get_info = ctypes.windll.psapi.GetProcessMemoryInfo
        get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        counters = Counters(cb=ctypes.sizeof(Counters))
        get_info(get_process(), ctypes.byref(counters), counters.cb)
        return counters.WorkingSetSize / 1e6
    import resource

    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return usage / 1e6 if sys.platform == "darwin" else usage / 1e3


def call(method: str, path: str, token: str | None = None, body: dict | None = None):
    request = urllib.request.Request(
        f"{URL}/api/v1{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})},
    )
    with urllib.request.urlopen(request) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


def measure(label: str, seconds: int) -> dict:
    wall, cpu = time.perf_counter(), time.process_time()
    peak = 0.0
    end = wall + seconds
    while time.perf_counter() < end:
        time.sleep(1)
        peak = max(peak, rss_mb())
    cpu_percent = 100 * (time.process_time() - cpu) / (time.perf_counter() - wall)
    result = {"phase": label, "cpu_percent_of_one_core": round(cpu_percent, 1), "memory_mb": round(peak)}
    print(
        f"  {label:<8} CPU {result['cpu_percent_of_one_core']:>5.1f}% of one core   memory {result['memory_mb']:>4} MB"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--image", type=Path, help="photo to feed the camera models (default: a synthetic frame)")
    args = parser.parse_args()

    appconfig.setup_logging()
    appconfig.load_config()
    os.environ["SCHEDULER_ENABLED"] = "false"

    import cv2
    import numpy as np

    from agent.camera.worker import CameraWorker
    from agent.tracker import FocusAgent
    from flowsense import EmbeddedServer, wait_until_up

    frame = cv2.resize(cv2.imread(str(args.image)), (640, 480)) if args.image else np.full((480, 640, 3), 128, np.uint8)

    class StillCamera:
        def grab(self):
            return True

        def read(self):
            return True, frame.copy()

        def release(self):
            pass

    class QuietNotifier:
        def notify(self, title, message):
            pass

    print(f"Baseline (Python + libraries loaded): {rss_mb():.0f} MB")
    server = EmbeddedServer("127.0.0.1", 8020)
    server.start()
    assert wait_until_up(URL, 30), "server did not start"

    email = f"bench{int(time.time())}@example.com"
    call("POST", "/auth/register", body={"email": email, "password": "password123"})
    token = call("POST", "/auth/login", body={"email": email, "password": "password123"})["access_token"]
    call("PATCH", "/settings", token, {"screen_tracking_enabled": True, "camera_tracking_enabled": False})

    notifier = QuietNotifier()
    camera = CameraWorker(notifier, capture_factory=lambda index: StillCamera())
    agent = FocusAgent(URL, notifier=notifier, camera=camera)
    agent.start()
    agent.set_token(token)
    time.sleep(2)

    print(f"Measuring {args.seconds}s per phase:")
    results = [measure("idle", args.seconds)]
    call("POST", "/sessions/start", token, {})
    results.append(measure("screen", args.seconds))
    call("PATCH", "/settings", token, {"camera_tracking_enabled": True})
    time.sleep(3)  # first frame loads the models
    results.append(measure("camera", args.seconds))
    call("POST", "/sessions/stop", token, {})

    agent.stop()
    server.stop()
    print(json.dumps(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
