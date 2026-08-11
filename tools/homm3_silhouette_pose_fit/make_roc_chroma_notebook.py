#!/usr/bin/env python3
"""Generate the inspectable Roc chromatic single-bone experiment notebook.

Syncs from the live .ipynb (strips outputs). Prefer editing the notebook for
interactive work; re-run this only when you want a clean regenerated copy.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "tools/homm3_silhouette_pose_fit/roc_chromatic_single_bone_match.ipynb"
OUT = SRC


def main() -> None:
    nb = json.loads(SRC.read_text(encoding="utf-8"))
    marker = "# LOCAL_GPU_ANATOMICAL_BOX_STAGE"
    detector_md = {
        "cell_type": "markdown",
        "metadata": {},
        "source": [
            "## Local GPU anatomical boxes\n",
            "\n",
            "Grounding DINO runs locally through Transformers on CUDA. It uses a fixed anatomical vocabulary for both the sprite target and mesh renders. Target boxes are passed into the inner score loop; the worker builds cheap current-pose boxes from the named bones so the detector is not rerun for every angle candidate. Full detector boxes are still produced for each committed mesh frame as a visual audit.\n",
        ],
    }
    detector_code = {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": [
            marker + "\n",
            "from roc_anatomical_boxes import (RocAnatomicalBoxDetector, FIXED_PART_LIBRARY, draw_boxes, write_boxes)\n",
            "PART_BOX_MODEL_ID = 'IDEA-Research/grounding-dino-tiny'\n",
            "ANATOMICAL_PART_WEIGHT = 0.20\n",
            "PART_BOX_OUT = PILOT / 'roc_anatomical_boxes'\n",
            "PART_BOX_OUT.mkdir(parents=True, exist_ok=True)\n",
            "detector = RocAnatomicalBoxDetector(model_id=PART_BOX_MODEL_ID)  # asserts CUDA; no CPU fallback\n",
            "SHOW_ANATOMICAL_BOXES = False  # semantic-only pilot: show the actual image pair, not detector overlays\n",
            "PART_BOXES_BY_FRAME = {}\n",
            "def normalized_boxes(boxes, width, height):\n",
            "    return [{'part': b.part, 'box': (b.box[0]/width, b.box[1]/height, b.box[2]/width, b.box[3]/height), 'score': b.score} for b in boxes]\n",
            "def detect_target_boxes(frame_index):\n",
            "    source = ANIMATION_TARGET_FRAMES / f'{frame_index:02d}.png'\n",
            "    image = Image.open(source)\n",
            "    boxes = detector.detect(image)\n",
            "    PART_BOXES_BY_FRAME[frame_index] = normalized_boxes(boxes, image.width, image.height)\n",
            "    draw_boxes(Image.open(source), boxes, PART_BOX_OUT / f'sprite_{frame_index:02d}_boxes.png', f'sprite frame {frame_index:02d} local CUDA boxes')\n",
            "    write_boxes(PART_BOX_OUT / f'sprite_{frame_index:02d}_boxes.json', boxes, image=source, device='cuda:0', model_id=PART_BOX_MODEL_ID)\n",
            "if SHOW_ANATOMICAL_BOXES:\n",
            "    for frame_index in range(30):\n",
            "        detect_target_boxes(frame_index)\n",
            "    print('detected target box frames:', len(PART_BOXES_BY_FRAME), 'library:', FIXED_PART_LIBRARY)\n",
            "else:\n",
            "    print('anatomical box detector disabled for semantic-only pilot')\n",
        ],
    }
    inserted = False
    for cell in nb.get("cells", []):
        if cell.get("cell_type") == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
        source = "".join(cell.get("source", []))
        if "TARGET_FRAMES = PILOT / \"frames_nn_shadow_culled\"" in source and "ANIMATION_TARGET_FRAMES" not in source:
            source = source.replace(
                'TARGET_FRAMES = PILOT / "frames_nn_shadow_culled"\n',
                'ANIMATION_TARGET_FRAMES = PILOT / "frames_nn_shadow_culled"\nTARGET_FRAMES = ANIMATION_TARGET_FRAMES\n',
            )
        if "_USE_UPSCALED_GEN_PILOT =" in source:
            source = source.replace(
                '_USE_UPSCALED_GEN_PILOT = True',
                '_USE_UPSCALED_GEN_PILOT = False',
            ).replace(
                '_USE_UPSCALED_GEN_PILOT = False',
                '# Original-frame-only contract: generated/temp targets are disabled.\n_USE_UPSCALED_GEN_PILOT = False',
                1,
            )
        if "ANIMATION_TARGET_FRAMES = PILOT /" in source or "# Original-frame-only contract" in source:
            cell["source"] = source.splitlines(True)
        if "def scan_bone_axis(" in source or "def detect_target_boxes(" in source or "sources = sorted(TARGET_FRAMES" in source:
            source = source.replace("ANIMATION_ANIMATION_TARGET_FRAMES", "ANIMATION_TARGET_FRAMES")
            source = source.replace("TARGET_FRAMES / f", "ANIMATION_TARGET_FRAMES / f")
            source = source.replace("sorted(TARGET_FRAMES.glob", "sorted(ANIMATION_TARGET_FRAMES.glob")
            source = source.replace("ANIMATION_ANIMATION_TARGET_FRAMES", "ANIMATION_TARGET_FRAMES")
            cell["source"] = source.splitlines(True)
        if "show_live_preview" in source or "LIVE_PREVIEW = True" in source:
            source = source.replace(
                "from IPython.display import display, clear_output",
                "from IPython.display import display, update_display, Image as IPImage",
            )
            if "_LIVE_DISPLAY_ID" not in source:
                anchor = "PREVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)\n"
                helper = anchor + (
                    "_LIVE_DISPLAY_ID = 'roc_pose_live_preview'\n"
                    "_LIVE_DISPLAY_STARTED = False\n"
                    "def update_live_preview_image():\n"
                    "    global _LIVE_DISPLAY_STARTED\n"
                    "    if not PREVIEW_PATH.exists():\n"
                    "        return\n"
                    "    image = IPImage(filename=str(PREVIEW_PATH))\n"
                    "    if _LIVE_DISPLAY_STARTED:\n"
                    "        update_display(image, display_id=_LIVE_DISPLAY_ID)\n"
                    "    else:\n"
                    "        display(image, display_id=_LIVE_DISPLAY_ID)\n"
                    "        _LIVE_DISPLAY_STARTED = True\n"
                )
                source = source.replace(anchor, helper, 1)
            source = source.replace("    clear_output(wait=True)\n", "")
            source = source.replace("        clear_output(wait=True)\n", "")
            source = source.replace(
                '    display({"image/png": PREVIEW_PATH.read_bytes()}, raw=True)\n',
                "    update_live_preview_image()\n",
            )
            source = source.replace(
                '            display({"image/png": PREVIEW_PATH.read_bytes()}, raw=True)\n',
                "            update_live_preview_image()\n",
            )
            cell["source"] = source.splitlines(True)
        if "def scan_bone(" in source or "def scan_bone_axis(" in source:
            if "SEMANTIC_ONLY" not in source:
                anchor = '_preview_state = {"n": 0, "best_iou": -1.0, "best_label": ""}\n'
                semantic_setup = anchor + (
                    "# Slow first-frame semantic pilot toggle. True replaces depth/silhouette as the decision score.\n"
                    "SEMANTIC_ONLY = True\n"
                    "SEMANTIC_MODEL_ID = 'google/siglip2-base-patch16-512'\n"
                    "if SEMANTIC_ONLY:\n"
                    "    from roc_semantic_embedding_match import RocSemanticEmbedder\n"
                    "    semantic_encoder = RocSemanticEmbedder(model_id=SEMANTIC_MODEL_ID)  # asserts CUDA\n"
                    "    _semantic_target_vectors = {}\n"
                    "    _semantic_candidate_dir = PILOT / 'tmp' / 'semantic_candidates'\n"
                    "    _semantic_candidate_dir.mkdir(parents=True, exist_ok=True)\n"
                    "    def semantic_target_vector(frame_index):\n"
                    "        if frame_index not in _semantic_target_vectors:\n"
                    "            image = semantic_encoder.load_image(ANIMATION_TARGET_FRAMES / f'{frame_index:02d}.png')\n"
                    "            _semantic_target_vectors[frame_index] = semantic_encoder.embed([image])[0]\n"
                    "        return _semantic_target_vectors[frame_index]\n"
                )
                source = source.replace(anchor, semantic_setup, 1)
            source = source.replace(
                'result = worker.request({"cmd": "score", "target": str(target), "targetDepth": str(depth_target) if depth_target.exists() else None, "angles": pose, "scoreMode": SCORE_MODE, "depthMaxDist": DEPTH_MAX_DIST, "colorMaxDist": COLOR_MAX_DIST, "predOnlyPenalty": PRED_ONLY_PENALTY, "targetEdgeSigmaPx": TARGET_EDGE_SIGMA_PX, "targetEdgeFloor": TARGET_EDGE_FLOOR, "previewOut": str(PREVIEW_PATH) if LIVE_PREVIEW else None, "previewCaption": f"{frame_index:02d} {bone} {angle_label}"})',
                'result = worker.request({"cmd": "score", "target": str(target), "targetDepth": str(depth_target) if depth_target.exists() else None, "angles": pose, "scoreMode": SCORE_MODE, "depthMaxDist": DEPTH_MAX_DIST, "colorMaxDist": COLOR_MAX_DIST, "predOnlyPenalty": PRED_ONLY_PENALTY, "targetEdgeSigmaPx": TARGET_EDGE_SIGMA_PX, "targetEdgeFloor": TARGET_EDGE_FLOOR, "targetPartBoxes": PART_BOXES_BY_FRAME.get(frame_index, []), "anatomicalPartWeight": ANATOMICAL_PART_WEIGHT, "previewOut": str(PREVIEW_PATH) if LIVE_PREVIEW else None, "previewCaption": f"{frame_index:02d} {bone} {angle_label}"})'
            )
            source = source.replace(
                '        if live:\n            req["previewOut"] = str(PREVIEW_PATH)\n',
                '        if live:\n            req["previewOut"] = str(PREVIEW_PATH)\n            req["previewRgb"] = True\n',
            )
            if "semanticCandidateOut" not in source:
                source = source.replace(
                    "        result = worker.request(req)\n",
                    "        if SEMANTIC_ONLY:\n            req['scoreMode'] = 'chroma'\n            req['semanticCandidateOut'] = str(_semantic_candidate_dir / f'f{frame_index:02d}_{bone}_{axis}_{region}_{angle_deg:+07.2f}.png')\n        result = worker.request(req)\n        if SEMANTIC_ONLY:\n            candidate_image = semantic_encoder.load_image(Path(req['semanticCandidateOut']))\n            candidate_vector = semantic_encoder.embed([candidate_image])[0]\n            semantic_score = float(np.dot(semantic_target_vector(frame_index), candidate_vector))\n            result['silhouetteIoU'] = float(result.get('iou', 0.0))\n            result['semanticCosine'] = semantic_score\n            result['iou'] = semantic_score\n",
                    1,
                )
            cell["source"] = source.splitlines(True)
        if ("def scan_bone_axis(" in source or "def scan_bone(" in source) and "targetPartBoxes" not in source:
            source = source.replace(
                '            "colorMaxDist": COLOR_MAX_DIST,\n',
                '            "colorMaxDist": COLOR_MAX_DIST,\n            "targetPartBoxes": PART_BOXES_BY_FRAME.get(frame_index, []),\n            "anatomicalPartWeight": ANATOMICAL_PART_WEIGHT,\n',
            )
            cell["source"] = source.splitlines(True)
        source = "".join(cell.get("source", []))
        if "semanticCandidateOut" in source and "if not result.get('ok')" not in source:
            source = source.replace(
                "        if SEMANTIC_ONLY:\n            candidate_image =",
                "        if not result.get('ok'):\n            raise RuntimeError(result)\n        if SEMANTIC_ONLY:\n            candidate_image =",
                1,
            )
            cell["source"] = source.splitlines(True)
        source = "".join(cell.get("source", []))
        if "semanticCandidateOut" in source and "previewRgb" not in source:
            source = source.replace(
                "            req['scoreMode'] = 'chroma'\n",
                "            req['scoreMode'] = 'chroma'\n            req['previewRgb'] = True\n",
                1,
            )
            cell["source"] = source.splitlines(True)
        source = "".join(cell.get("source", []))
        if "targetPartBoxes" in source and "showAnatomicalBoxes" not in source:
            source = source.replace(
                '            "anatomicalPartWeight": ANATOMICAL_PART_WEIGHT,\n',
                '            "anatomicalPartWeight": ANATOMICAL_PART_WEIGHT,\n            "showAnatomicalBoxes": SHOW_ANATOMICAL_BOXES,\n',
                1,
            )
            cell["source"] = source.splitlines(True)
        source = "".join(cell.get("source", []))
        if "def detect_target_boxes(" in source and "SHOW_ANATOMICAL_BOXES" not in source:
            source = source.replace(
                "PART_BOXES_BY_FRAME = {}\n",
                "SHOW_ANATOMICAL_BOXES = False  # hidden for semantic-only pilot\nPART_BOXES_BY_FRAME = {}\n",
                1,
            )
            source = source.replace(
                "for frame_index in range(30):\n    detect_target_boxes(frame_index)\nprint('detected target box frames:', len(PART_BOXES_BY_FRAME), 'library:', FIXED_PART_LIBRARY)\n",
                "if SHOW_ANATOMICAL_BOXES:\n    for frame_index in range(30):\n        detect_target_boxes(frame_index)\n    print('detected target box frames:', len(PART_BOXES_BY_FRAME), 'library:', FIXED_PART_LIBRARY)\nelse:\n    print('anatomical box detector disabled for semantic-only pilot')\n",
                1,
            )
            cell["source"] = source.splitlines(True)
        source = "".join(cell.get("source", []))
        if "SHOW_ANATOMICAL_BOXES = False" in source and "detector = None" not in source:
            source = source.replace(
                "detector = RocAnatomicalBoxDetector(model_id=PART_BOX_MODEL_ID)  # asserts CUDA; no CPU fallback\nSHOW_ANATOMICAL_BOXES = False  # hidden for semantic-only pilot\n",
                "SHOW_ANATOMICAL_BOXES = False  # hidden for semantic-only pilot\ndetector = RocAnatomicalBoxDetector(model_id=PART_BOX_MODEL_ID) if SHOW_ANATOMICAL_BOXES else None  # CUDA only\n",
                1,
            )
            cell["source"] = source.splitlines(True)
        if "MATCH_OUT = PILOT" in source and "mesh_part_boxes" in source:
            pass
    cells = nb.get("cells", [])
    if not any(marker in "".join(c.get("source", [])) for c in cells):
        insert_at = next((i + 1 for i, c in enumerate(cells) if "worker = BlenderWorker()" in "".join(c.get("source", []))), len(cells))
        cells[insert_at:insert_at] = [detector_md, detector_code]
    semantic_marker = "# LOCAL_GPU_SEMANTIC_EMBEDDING_STAGE"
    if not any(semantic_marker in "".join(c.get("source", [])) for c in cells):
        cells.extend([
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "## Local GPU semantic image comparison\n",
                    "\n",
                    "Semantic image embeddings are the proven pose-selection path. The first-frame pilot also runs the adaptive semantic optimizer inside the one-bone loop; this report cell remains available for post-run pairwise inspection.\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    semantic_marker + "\n",
                    "from roc_semantic_embedding_match import RocSemanticEmbedder\n",
                    "SEMANTIC_MODEL_ID = 'google/siglip2-base-patch16-512'\n",
                    "SEMANTIC_MESH_DIR = PILOT / 'roc_chroma_match_v1'\n",
                    "SEMANTIC_OUT = PILOT / 'roc_chroma_match_v1' / 'semantic_embedding_report.json'\n",
                    "SEMANTIC_OUT.parent.mkdir(parents=True, exist_ok=True)\n",
                    "semantic_pairs = []\n",
                    "for target in sorted(ANIMATION_TARGET_FRAMES.glob('*.png')):\n",
                    "    mesh = SEMANTIC_MESH_DIR / f'frame_{target.stem}.png'\n",
                    "    if mesh.exists():\n",
                    "        semantic_pairs.append((target, mesh))\n",
                    "semantic_encoder = RocSemanticEmbedder(model_id=SEMANTIC_MODEL_ID)  # asserts CUDA\n",
                    "semantic_rows = semantic_encoder.compare_pairs(semantic_pairs, batch_size=1)\n",
                    "semantic_report = {'model': SEMANTIC_MODEL_ID, 'device': str(semantic_encoder.device), 'pairs': semantic_rows, 'meanCosine': float(np.mean([row['cosine'] for row in semantic_rows])), 'proof': 'local GPU SigLIP2 image embeddings; original frames only'}\n",
                    "SEMANTIC_OUT.write_text(json.dumps(semantic_report, indent=2) + '\\n')\n",
                    "print('semantic mean cosine:', semantic_report['meanCosine'], 'pairs:', len(semantic_rows), 'device:', semantic_report['device'])\n",
                ],
            },
        ])
    # Add committed-mesh detector proof to the final render loop without making
    # the expensive detector part of every angle candidate.
    for cell in cells:
        source = "".join(cell.get("source", []))
        if "worker.request({\"cmd\": \"save_render\"" in source and "mesh_part_boxes" not in source:
            needle = 'worker.request({"cmd": "save_render", "out": str(out)})\n'
            replacement = needle + (
                "    mesh_boxes = detector.detect(Image.open(out))\n"
                "    draw_boxes(Image.open(out), mesh_boxes, PART_BOX_OUT / f'mesh_{frame_index:02d}_boxes.png', f'mesh frame {frame_index:02d} local CUDA boxes')\n"
                "    write_boxes(PART_BOX_OUT / f'mesh_{frame_index:02d}_boxes.json', mesh_boxes, image=out, device='cuda:0', model_id=PART_BOX_MODEL_ID)\n"
                "    mesh_part_boxes = [b.as_dict() for b in mesh_boxes]\n"
            )
            if needle in source:
                cell["source"] = source.replace(needle, replacement).splitlines(True)
        source = "".join(cell.get("source", []))
        if "all_history.append({" in source and "meshPartBoxes" not in source:
            source = source.replace(
                '        "pose": _pose_public(pose),\n',
                '        "pose": _pose_public(pose),\n        "meshPartBoxes": mesh_part_boxes,\n',
            )
            source = source.replace(
                '            "score": "soft_depth_iou",\n',
                '            "score": "weighted_soft_depth_or_chroma_iou_plus_anatomical_part_iou",\n            "anatomicalPartWeight": ANATOMICAL_PART_WEIGHT,\n',
            )
            cell["source"] = source.splitlines(True)
        if "MATCH_OUT = PILOT" in source and "for frame_index in range(30):" in source:
            source = source.replace(
                "for frame_index in range(30):",
                "for frame_index in ([0] if SEMANTIC_ONLY else range(30)):",
                1,
            )
            cell["source"] = source.splitlines(True)
    OUT.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
