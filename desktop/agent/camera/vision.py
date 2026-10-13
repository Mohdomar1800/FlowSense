"""Turns a camera frame into an Observation: face position, head tilt, and any phones in view.

Two small ONNX models run through OpenCV's DNN module (no other ML dependencies):
- YuNet face detector (OpenCV Zoo, MIT license): face box + 5 landmarks (eyes, nose, mouth corners).
- YOLOX-Nano object detector (Megvii, Apache-2.0), trained on COCO; class 67 is "cell phone".

Frames are processed in memory only.
"""

from pathlib import Path

import cv2
import numpy as np

from agent.camera.phone_monitor import Box, Detection, Observation

COCO_CELL_PHONE = 67
YOLOX_INPUT = 416
YOLOX_STRIDES = (8, 16, 32)
FACE_INPUT_WIDTH = 320
PHONE_CANDIDATE_SCORE = 0.25
NMS_IOU = 0.45


def _yolox_grids(size: int) -> tuple[np.ndarray, np.ndarray]:
    """Anchor-free grid offsets and strides used to decode YOLOX's raw outputs."""
    grids, strides = [], []
    for stride in YOLOX_STRIDES:
        cells = size // stride
        xv, yv = np.meshgrid(np.arange(cells), np.arange(cells))
        grid = np.stack((xv, yv), 2).reshape(-1, 2)
        grids.append(grid)
        strides.append(np.full((grid.shape[0], 1), stride))
    return np.concatenate(grids).astype(np.float32), np.concatenate(strides).astype(np.float32)


class FrameAnalyzer:
    def __init__(self, face_model: Path, object_model: Path) -> None:
        # One thread: OpenCV's default thread pool spins between frames and used >100% of a core at our
        # 1 frame/s pace; single-threaded it uses roughly a tenth of that, and latency doesn't matter here.
        cv2.setNumThreads(1)
        self.face_detector = cv2.FaceDetectorYN.create(str(face_model), "", (FACE_INPUT_WIDTH, 240), 0.7, 0.3, 5)
        self.object_net = cv2.dnn.readNetFromONNX(str(object_model))
        self.grids, self.strides = _yolox_grids(YOLOX_INPUT)

    def analyze(self, frame: np.ndarray) -> Observation:
        height, width = frame.shape[:2]
        face, pitch = self._face(frame, width, height)
        return Observation(face=face, head_pitch=pitch, phones=tuple(self._phones(frame, width, height)))

    # ---------- face ----------

    def _face(self, frame: np.ndarray, width: int, height: int) -> tuple[Box | None, float | None]:
        scale = FACE_INPUT_WIDTH / width
        small = cv2.resize(frame, (FACE_INPUT_WIDTH, int(height * scale)))
        self.face_detector.setInputSize((small.shape[1], small.shape[0]))
        _, faces = self.face_detector.detect(small)
        if faces is None or len(faces) == 0:
            return None, None
        f = max(faces, key=lambda row: row[2] * row[3])  # the largest (closest) face is the user
        sw, sh = small.shape[1], small.shape[0]
        box = Box(float(f[0] / sw), float(f[1] / sh), float(f[2] / sw), float(f[3] / sh))
        return box, head_pitch(f[4:14].reshape(5, 2))

    # ---------- phones ----------

    def _phones(self, frame: np.ndarray, width: int, height: int) -> list[Detection]:
        ratio = min(YOLOX_INPUT / height, YOLOX_INPUT / width)
        resized = cv2.resize(frame, (int(width * ratio), int(height * ratio)), interpolation=cv2.INTER_LINEAR)
        padded = np.full((YOLOX_INPUT, YOLOX_INPUT, 3), 114, dtype=np.uint8)
        padded[: resized.shape[0], : resized.shape[1]] = resized
        blob = padded.transpose(2, 0, 1)[np.newaxis].astype(np.float32)  # YOLOX expects raw BGR 0-255, NCHW

        self.object_net.setInput(blob)
        raw = self.object_net.forward()[0]  # (anchors, 85): cx, cy, w, h, objectness, 80 class scores
        scores = raw[:, 4] * raw[:, 5 + COCO_CELL_PHONE]
        keep = scores >= PHONE_CANDIDATE_SCORE
        if not np.any(keep):
            return []

        centers = (raw[keep, :2] + self.grids[keep]) * self.strides[keep]
        sizes = np.exp(raw[keep, 2:4]) * self.strides[keep]
        boxes = np.concatenate([centers - sizes / 2, sizes], axis=1) / ratio  # x, y, w, h in frame pixels
        kept_scores = scores[keep]
        indices = cv2.dnn.NMSBoxes(boxes.tolist(), kept_scores.tolist(), PHONE_CANDIDATE_SCORE, NMS_IOU)
        return [
            Detection(
                Box(
                    float(boxes[i, 0] / width),
                    float(boxes[i, 1] / height),
                    float(boxes[i, 2] / width),
                    float(boxes[i, 3] / height),
                ),
                float(kept_scores[i]),
            )
            for i in np.array(indices).flatten()
        ]


def head_pitch(landmarks: np.ndarray) -> float | None:
    """Where the nose tip sits between the eye line (0) and the mouth line (1).

    Tilting the head down moves the projected nose tip toward the mouth, so the value grows;
    tilting up shrinks it. Only the change from the user's own normal value is used.
    landmarks: right eye, left eye, nose tip, right mouth corner, left mouth corner (x, y).
    """
    eye_y = (landmarks[0, 1] + landmarks[1, 1]) / 2
    mouth_y = (landmarks[3, 1] + landmarks[4, 1]) / 2
    span = mouth_y - eye_y
    if span <= 1e-6:
        return None
    return float((landmarks[2, 1] - eye_y) / span)
