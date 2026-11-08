"""Still-sprite keep lock: consecutive RGB MAD and winner/pose copy."""
from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from roc_gpu_cascade_experiment import (
    consecutive_sprite_rgb_mad,
    lock_winner_indices_to_previous,
    still_sprite_lock_mask,
)


def _write_rgb(path: Path, color: tuple[int, int, int]) -> None:
    Image.fromarray(np.full((4, 4, 3), color, dtype=np.uint8), mode="RGB").save(path)


def test_consecutive_mad_and_still_mask() -> None:
    with tempfile.TemporaryDirectory() as raw:
        directory = Path(raw)
        _write_rgb(directory / "00.png", (10, 10, 10))
        _write_rgb(directory / "01.png", (10, 10, 10))
        _write_rgb(directory / "02.png", (10, 10, 11))
        _write_rgb(directory / "03.png", (200, 10, 10))
        _write_rgb(directory / "04.png", (200, 10, 10))
        paths = [directory / f"{index:02d}.png" for index in range(5)]
        mads = consecutive_sprite_rgb_mad(paths)
        assert mads[0] == 1.0
        assert mads[1] == 0.0
        assert 0.0 < mads[2] < 0.01
        assert mads[3] > 0.2
        assert mads[4] == 0.0
        still = still_sprite_lock_mask(mads, threshold=0.015)
        assert still == (False, True, True, False, True)


def test_still_mask_fail_closed() -> None:
    try:
        still_sprite_lock_mask((1.0, 0.04, 0.05), threshold=0.015)
        raise AssertionError("no-still mask must fail closed")
    except ValueError as exc:
        assert "no still frames" in str(exc)
    try:
        still_sprite_lock_mask((1.0, 0.001, 0.001), threshold=0.015)
        raise AssertionError("all-still mask must fail closed")
    except ValueError as exc:
        assert "freeze every frame after 0" in str(exc)
    try:
        consecutive_sprite_rgb_mad([])
        raise AssertionError("empty MAD path list must fail closed")
    except ValueError as exc:
        assert "at least one PNG" in str(exc)


def test_lock_winner_indices_copies_previous() -> None:
    locked = lock_winner_indices_to_previous(
        [3, 7, 2, 9],
        (False, True, False, True),
    )
    assert locked == [3, 3, 2, 2]
    try:
        lock_winner_indices_to_previous([1, 2], (False,))
        raise AssertionError("mismatched winner/mask lengths must fail closed")
    except ValueError as exc:
        assert "must match" in str(exc)


def run() -> dict[str, object]:
    test_consecutive_mad_and_still_mask()
    test_still_mask_fail_closed()
    test_lock_winner_indices_copies_previous()
    return {"ok": True}


if __name__ == "__main__":
    print(run())
