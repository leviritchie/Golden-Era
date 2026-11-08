"""look.py --try-modes scores look A, the same look the rebuild's review and stage_apply's regression gate measure.

    python tools/homm3_unit_look/test_try_modes_stages.py        (or pytest)

2026-10-12 hota_cove_crew_mate: a bare --try-modes ran the finish before its review (look B, v7c 2.33) while the
rebuild reviewed before the finish (look A, 5.1 vs raw 5.05). No repo artifacts are read.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import look as L  # noqa: E402


def test_default_stages_drop_finish_and_apply():
    st = L.try_mode_stages(list(L.DEFAULT_STAGES))
    assert "finish" not in st and "apply" not in st
    assert st == [s for s in L.DEFAULT_STAGES if s not in ("finish", "apply")]


def test_matches_fleet_review_step():
    # fleet_rebuild's LOOK_REVIEW_STEP / LOOK_TRY_STEP stages: bake,fit,vfx,review
    assert L.try_mode_stages(["bake", "fit", "finish", "vfx", "review", "apply"]) == ["bake", "fit", "vfx", "review"]


def test_order_kept():
    assert L.try_mode_stages(["review", "fit", "finish"]) == ["review", "fit"]


def test_source_label_names_the_measured_glb():
    sha = "ec5e8ab0" + "0" * 56
    sup = L.try_source_label("u_test", {"glbSha256": sha, "from": "superseded"})
    assert sup.startswith("superseded ") and str(L.superseded_path("u_test", sha)) in sup and sup.endswith("sha ec5e8ab00000")
    cur = L.try_source_label("u_test", {"glbSha256": sha, "from": "glb"})
    assert cur.startswith("glb ") and str(L.S.glb_path("u_test")) in cur
    assert L.try_source_label("u_test", {}).endswith("sha ?")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
