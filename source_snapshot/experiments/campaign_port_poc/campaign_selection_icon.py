"""Build StoryHub campaign selection icons from HoMM3 hover/intro clip stills.

Native pattern (mainStory):
  storyHub.mainIconSid → campaigns/{hub}/icons/main_icon.png (378×693)
  storyHub.hubIconSid  → campaigns/{hub}/icons/save_icon.png (and hub_icon.png)

Cgood* / Cevil* / Cneutral / Csecret are wide hover-menu clips. Prefer a curated
vertical focus crop into the tall native slot over width-fit banner padding.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Native mainStory campaigns/mainStory/icons/main_icon.png dimensions.
NATIVE_MAIN_ICON_WIDTH = 378
NATIVE_MAIN_ICON_HEIGHT = 693
NATIVE_MAIN_ICON_ASPECT = NATIVE_MAIN_ICON_WIDTH / NATIVE_MAIN_ICON_HEIGHT

COMPOSE_VERTICAL_FOCUS = "letterbox_trim_then_vertical_focus"
COMPOSE_WIDTH_FIT_BANNER = "letterbox_trim_then_width_fit_top_banner"
COMPOSE_COVER = "letterbox_trim_then_center_cover"


def extract_frame_bgr(
    mp4_path: Path, *, frame_index: int | None = None, frame_fraction: float = 1.0 / 3.0
) -> Any:
    """Return a BGR ndarray frame from mp4_path (OpenCV). Fail closed if unreadable."""
    import cv2

    if not mp4_path.is_file():
        raise FileNotFoundError(f"missing selection-still source MP4: {mp4_path}")
    cap = cv2.VideoCapture(str(mp4_path))
    if not cap.isOpened():
        raise RuntimeError(f"OpenCV could not open MP4: {mp4_path}")
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if frame_index is None:
            frame_index = max(0, int(total * frame_fraction)) if total > 0 else 0
        if total > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, min(frame_index, total - 1))
        ok, frame = cap.read()
        if not ok or frame is None:
            raise RuntimeError(f"failed to read frame {frame_index} from {mp4_path}")
        return frame
    finally:
        cap.release()


def crop_letterbox_content(frame_bgr: Any, *, luma_threshold: float = 8.0) -> Any:
    """Trim near-black letterbox bars from a canvas-padded clip frame."""
    import cv2
    import numpy as np

    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    row_mean = gray.mean(axis=1)
    col_mean = gray.mean(axis=0)
    rows = np.where(row_mean > luma_threshold)[0]
    cols = np.where(col_mean > luma_threshold)[0]
    if len(rows) == 0 or len(cols) == 0:
        return frame_bgr
    return frame_bgr[int(rows[0]) : int(rows[-1]) + 1, int(cols[0]) : int(cols[-1]) + 1]


def compose_main_icon_banner(
    rgb_image: Any,
    *,
    width: int = NATIVE_MAIN_ICON_WIDTH,
    height: int = NATIVE_MAIN_ICON_HEIGHT,
    top_padding: int = 48,
    fill_rgb: tuple[int, int, int] = (8, 8, 12),
) -> Any:
    """Fit the full still to native width and pin it near the top of main_icon.

    Legacy policy for wide hover clips when no curated focus is available.
    """
    from PIL import Image

    if not isinstance(rgb_image, Image.Image):
        raise TypeError("compose_main_icon_banner expects a PIL Image")
    scale = width / rgb_image.width
    nw = width
    nh = max(1, int(round(rgb_image.height * scale)))
    if nh > height - top_padding:
        return compose_main_icon_cover(rgb_image, width=width, height=height)
    fitted = rgb_image.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (width, height), fill_rgb)
    canvas.paste(fitted, (0, top_padding))
    return canvas


def compose_main_icon_cover(
    rgb_image: Any,
    *,
    width: int = NATIVE_MAIN_ICON_WIDTH,
    height: int = NATIVE_MAIN_ICON_HEIGHT,
) -> Any:
    """Scale-to-cover then center-crop into native main_icon size (PIL Image)."""
    return compose_main_icon_vertical_focus(
        rgb_image, focus_x=0.5, focus_y=0.5, width=width, height=height
    )


def compose_main_icon_vertical_focus(
    rgb_image: Any,
    *,
    focus_x: float = 0.5,
    focus_y: float = 0.5,
    width: int = NATIVE_MAIN_ICON_WIDTH,
    height: int = NATIVE_MAIN_ICON_HEIGHT,
) -> Any:
    """Scale-to-cover with a curated focal point, then crop to native main_icon size.

    focus_x / focus_y are normalized [0, 1] positions in the source still
    (0=left/top, 1=right/bottom). The crop window keeps native aspect and is
    clamped to the source bounds.
    """
    from PIL import Image

    if not isinstance(rgb_image, Image.Image):
        raise TypeError("compose_main_icon_vertical_focus expects a PIL Image")
    if not (0.0 <= focus_x <= 1.0 and 0.0 <= focus_y <= 1.0):
        raise ValueError(f"focus_x/focus_y must be in [0,1]; got {focus_x}, {focus_y}")

    src_w, src_h = rgb_image.size
    target_aspect = width / height
    # Prefer full-height vertical strip when the still is wider than the card.
    crop_w = src_h * target_aspect
    crop_h = float(src_h)
    if crop_w > src_w:
        crop_w = float(src_w)
        crop_h = src_w / target_aspect

    cx = focus_x * src_w
    cy = focus_y * src_h
    left = max(0.0, min(cx - crop_w / 2.0, src_w - crop_w))
    top = max(0.0, min(cy - crop_h / 2.0, src_h - crop_h))
    box = (
        int(round(left)),
        int(round(top)),
        int(round(left + crop_w)),
        int(round(top + crop_h)),
    )
    cropped = rgb_image.crop(box)
    return cropped.resize((width, height), Image.Resampling.LANCZOS)


def _compose(
    still: Any,
    *,
    compose_policy: str,
    focus_x: float,
    focus_y: float,
) -> Any:
    if compose_policy == COMPOSE_VERTICAL_FOCUS:
        return compose_main_icon_vertical_focus(still, focus_x=focus_x, focus_y=focus_y)
    if compose_policy == COMPOSE_COVER:
        return compose_main_icon_cover(still)
    if compose_policy == COMPOSE_WIDTH_FIT_BANNER:
        return compose_main_icon_banner(still)
    raise ValueError(f"unknown composePolicy {compose_policy!r}")


def build_main_icon_from_still(
    still_path: Path,
    *,
    icon_out: Path,
    compose_policy: str = COMPOSE_VERTICAL_FOCUS,
    focus_x: float = 0.5,
    focus_y: float = 0.5,
) -> dict[str, Any]:
    """Compose a native-sized main_icon.png from an already-extracted still PNG."""
    from PIL import Image

    if not still_path.is_file():
        raise FileNotFoundError(f"missing selection still: {still_path}")
    still = Image.open(still_path).convert("RGB")
    icon = _compose(still, compose_policy=compose_policy, focus_x=focus_x, focus_y=focus_y)
    if icon.size != (NATIVE_MAIN_ICON_WIDTH, NATIVE_MAIN_ICON_HEIGHT):
        raise RuntimeError(
            f"main_icon must be {NATIVE_MAIN_ICON_WIDTH}x{NATIVE_MAIN_ICON_HEIGHT}; "
            f"got {icon.size}"
        )
    icon_out.parent.mkdir(parents=True, exist_ok=True)
    icon.save(icon_out, format="PNG")
    return {
        "sourceStill": str(still_path),
        "iconPath": str(icon_out),
        "stillSize": list(still.size),
        "iconSize": list(icon.size),
        "composePolicy": compose_policy,
        "focusX": focus_x,
        "focusY": focus_y,
        "nativeMainIconSize": [NATIVE_MAIN_ICON_WIDTH, NATIVE_MAIN_ICON_HEIGHT],
    }


def build_main_icon_from_mp4(
    mp4_path: Path,
    *,
    still_out: Path | None = None,
    icon_out: Path,
    frame_fraction: float = 1.0 / 3.0,
    compose_policy: str = COMPOSE_VERTICAL_FOCUS,
    focus_x: float = 0.5,
    focus_y: float = 0.5,
) -> dict[str, Any]:
    """Extract a C*-class still and write native-sized main_icon.png."""
    import cv2
    from PIL import Image

    frame = extract_frame_bgr(mp4_path, frame_fraction=frame_fraction)
    content = crop_letterbox_content(frame)
    rgb = cv2.cvtColor(content, cv2.COLOR_BGR2RGB)
    still = Image.fromarray(rgb)
    if still_out is not None:
        still_out.parent.mkdir(parents=True, exist_ok=True)
        still.save(still_out, format="PNG")
    icon = _compose(still, compose_policy=compose_policy, focus_x=focus_x, focus_y=focus_y)
    if icon.size != (NATIVE_MAIN_ICON_WIDTH, NATIVE_MAIN_ICON_HEIGHT):
        raise RuntimeError(
            f"main_icon must be {NATIVE_MAIN_ICON_WIDTH}x{NATIVE_MAIN_ICON_HEIGHT}; "
            f"got {icon.size}"
        )
    icon_out.parent.mkdir(parents=True, exist_ok=True)
    icon.save(icon_out, format="PNG")
    return {
        "sourceMp4": str(mp4_path),
        "stillPath": str(still_out) if still_out is not None else None,
        "iconPath": str(icon_out),
        "stillSize": list(still.size),
        "iconSize": list(icon.size),
        "composePolicy": compose_policy,
        "focusX": focus_x,
        "focusY": focus_y,
        "nativeMainIconSize": [NATIVE_MAIN_ICON_WIDTH, NATIVE_MAIN_ICON_HEIGHT],
    }
