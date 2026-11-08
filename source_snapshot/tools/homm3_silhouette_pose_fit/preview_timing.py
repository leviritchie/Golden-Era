"""Shared preview playback timing for stick GIFs and lit mesh previews.

Side-by-side stick GIFs use Pillow ``duration=180`` ms per source frame.
Lit mp4/gif must match that wall-clock speed (not job ``fps``, which is often 12
and makes a one-cycle clip look ~2.4× too fast vs the GIF).
"""
from __future__ import annotations

# Matches render_fixed_length_preview.py / render_fitted_mesh_skeleton.py GIF delay.
PREVIEW_GIF_FRAME_MS = 180


def cycle_duration_s(n_source_frames: int, frame_ms: int = PREVIEW_GIF_FRAME_MS) -> float:
    """Wall-clock length of one GIF loop (n frames × delay)."""
    n = max(1, int(n_source_frames))
    return n * (float(frame_ms) / 1000.0)


def interpolated_frame_count(
    n_source_frames: int,
    out_fps: int,
    frame_ms: int = PREVIEW_GIF_FRAME_MS,
) -> int:
    """How many output frames cover one GIF-timed cycle at out_fps."""
    return max(2, int(round(cycle_duration_s(n_source_frames, frame_ms) * float(out_fps))))
