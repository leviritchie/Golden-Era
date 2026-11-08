"""Vendored DWPose ONNX whole-body detector (IDEA-Research DWPose onnx branch)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import onnxruntime as ort

from .onnxdet import inference_detector
from .onnxpose import inference_pose

# OpenPose body-18 names after Wholebody remapping (index order).
OPENPOSE_BODY18 = [
    "Nose",
    "Neck",
    "RShoulder",
    "RElbow",
    "RWrist",
    "LShoulder",
    "LElbow",
    "LWrist",
    "MidHip",
    "RHip",
    "RKnee",
    "RAnkle",
    "LHip",
    "LKnee",
    "LAnkle",
    "REye",
    "LEye",
    "REar",
]


def _providers() -> list[str]:
    available = ort.get_available_providers()
    if "CUDAExecutionProvider" in available:
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]


class Wholebody:
    def __init__(self, det_path: Path, pose_path: Path):
        providers = _providers()
        self.session_det = ort.InferenceSession(str(det_path), providers=providers)
        self.session_pose = ort.InferenceSession(str(pose_path), providers=providers)

    def __call__(self, ori_img: np.ndarray, *, allow_fullframe_fallback: bool = True) -> tuple[np.ndarray, np.ndarray]:
        """
        Returns:
            keypoints: (N, 18, 2) in pixel coords (OpenPose body order)
            scores: (N, 18)
        """
        det_result = inference_detector(self.session_det, ori_img)
        if det_result is None or len(det_result) == 0:
            if not allow_fullframe_fallback:
                return np.zeros((0, 18, 2), dtype=np.float32), np.zeros((0, 18), dtype=np.float32)
            h, w = ori_img.shape[:2]
            det_result = np.array([[0.0, 0.0, float(w), float(h)]], dtype=np.float32)

        keypoints, scores = inference_pose(self.session_pose, det_result, ori_img)

        # Match IDEA-Research Wholebody remapping to OpenPose body-18.
        keypoints_info = np.concatenate((keypoints, scores[..., None]), axis=-1)
        neck = np.mean(keypoints_info[:, [5, 6]], axis=1)
        neck_score = np.logical_and(
            keypoints_info[:, 5, 2] > 0.3,
            keypoints_info[:, 6, 2] > 0.3,
        ).astype(np.float32)
        neck = np.concatenate([neck[:, :2], neck_score[:, None]], axis=1)
        new_keypoints_info = np.insert(keypoints_info, 17, neck, axis=1)
        mmpose_idx = [17, 6, 8, 10, 7, 9, 12, 14, 16, 13, 15, 2, 1, 4, 3]
        openpose_idx = [1, 2, 3, 4, 6, 7, 8, 9, 10, 12, 13, 14, 15, 16, 17]
        new_keypoints_info[:, openpose_idx] = new_keypoints_info[:, mmpose_idx]
        body = new_keypoints_info[:, :18]
        return body[..., :2].astype(np.float32), body[..., 2].astype(np.float32)
