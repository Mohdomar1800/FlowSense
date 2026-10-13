"""Draw the FlowSense icon (same design as frontend/assets/icon.svg) into a multi-size Windows .ico.

    python desktop/packaging/make_icon.py

Each size is drawn at 4x and downscaled for smooth edges, then stored as PNG inside the ICO container.
"""

import struct
from pathlib import Path

import cv2
import numpy as np

OUT = Path(__file__).resolve().parent / "flowsense.ico"
SIZES = (256, 64, 48, 32, 16)
INDIGO_BGR = (229, 70, 79)  # #4f46e5


def draw(size: int) -> np.ndarray:
    s = size * 4
    img = np.zeros((s, s, 4), np.uint8)  # BGRA, transparent
    radius = int(s * 16 / 64)
    color = (*INDIGO_BGR, 255)
    # Rounded square: two rectangles plus four corner circles.
    cv2.rectangle(img, (radius, 0), (s - radius, s), color, -1)
    cv2.rectangle(img, (0, radius), (s, s - radius), color, -1)
    for cx, cy in ((radius, radius), (s - radius, radius), (radius, s - radius), (s - radius, s - radius)):
        cv2.circle(img, (cx, cy), radius, color, -1, cv2.LINE_AA)
    center = (s // 2, s // 2)
    white = (255, 255, 255, 255)
    # Open ring (~300 degrees, gap at the top right) and a center dot, as in the SVG.
    ring_radius = int(s * 17 / 64)
    thickness = max(1, int(s * 5 / 64))
    cv2.ellipse(img, center, (ring_radius, ring_radius), -90, 0, 300, white, thickness, cv2.LINE_AA)
    cv2.circle(img, center, int(s * 5 / 64), white, -1, cv2.LINE_AA)
    return cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)


def main() -> None:
    images = []
    for size in SIZES:
        ok, png = cv2.imencode(".png", draw(size))
        assert ok
        images.append((size, png.tobytes()))

    header = struct.pack("<HHH", 0, 1, len(images))  # reserved, type=icon, count
    offset = len(header) + 16 * len(images)
    entries, blobs = b"", b""
    for size, png in images:
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO format
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset + len(blobs))
        blobs += png
    OUT.write_bytes(header + entries + blobs)
    cv2.imwrite(str(OUT.with_suffix(".png")), draw(256))  # preview
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
