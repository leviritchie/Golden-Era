"""Map native-length clips into a longer token window without synthesizing frames."""
from __future__ import annotations

from typing import Any

import numpy as np

NATIVE_POLICY = "native_length"
REPEAT_TO_24_POLICY = "repeat_complete_cycles_or_endpoint_holds_to_24"
TARGET_TOKENS = 24


def expand_frame_indices(
    frame_count: int,
    *,
    cyclic: bool,
    target_tokens: int = TARGET_TOKENS,
) -> dict[str, Any]:
    count = int(frame_count)
    if count < 1:
        raise ValueError("clip has no frames")
    target = int(target_tokens)
    if target < count:
        raise ValueError(
            f"refusing to truncate {count} frames to {target} tokens; "
            "temporal context may only add repeats or holds"
        )
    if count == target:
        source_index = list(range(count))
        return {
            "policy": REPEAT_TO_24_POLICY,
            "cyclic": bool(cyclic),
            "nativeLength": count,
            "tokenLength": target,
            "mode": "already_target_length",
            "sourceIndex": source_index,
            "outputIndex": list(range(count)),
            "playbackDurationUnchanged": True,
        }
    if cyclic:
        repeats = (target + count - 1) // count
        source_index = [index % count for index in range(repeats * count)][:target]
        if target % count == 0:
            middle_cycle = (target // count) // 2
            output_index = [middle_cycle * count + index for index in range(count)]
            mode = "repeated_complete_cycles"
        else:
            output_index = list(range(count))
            mode = "repeated_cycles_truncated_to_target_without_dropping_originals"
            if source_index[:count] != list(range(count)):
                raise RuntimeError("cycle expansion lost the original frame order")
        return {
            "policy": REPEAT_TO_24_POLICY,
            "cyclic": True,
            "nativeLength": count,
            "tokenLength": target,
            "mode": mode,
            "sourceIndex": source_index,
            "outputIndex": output_index,
            "playbackDurationUnchanged": True,
        }
    extra = target - count
    left = extra // 2
    right = extra - left
    source_index = [0] * left + list(range(count)) + [count - 1] * right
    output_index = [left + index for index in range(count)]
    return {
        "policy": REPEAT_TO_24_POLICY,
        "cyclic": False,
        "nativeLength": count,
        "tokenLength": target,
        "mode": "endpoint_holds",
        "sourceIndex": source_index,
        "outputIndex": output_index,
        "leftHold": left,
        "rightHold": right,
        "playbackDurationUnchanged": True,
    }


def map_predictions_to_native(values: np.ndarray, output_index: list[int]) -> np.ndarray:
    payload = np.asarray(values)
    if payload.shape[0] <= max(output_index):
        raise ValueError(
            f"prediction length {payload.shape[0]} cannot map output indices {output_index}"
        )
    return payload[list(output_index)]
