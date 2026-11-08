#!/usr/bin/env python3
"""One-shot patch: score-escape fail-fast, root abort, collision cache, camera seed."""
from __future__ import annotations

import ast
from pathlib import Path

TOOL = Path(__file__).resolve().parent


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing block: {label}")
    return text.replace(old, new, 1)


def patch_cascade() -> None:
    path = TOOL / "roc_gpu_cascade_experiment.py"
    text = path.read_text(encoding="utf-8")

    broken = (
        "@dataclass(frozen=True)\n"
        "\n"
        "# Process-local collision tables keyed by (mesh, sample, hops, margin, device).\n"
        "# Same rigidized GLB across clips of one unit should not rebuild geodesic pairs.\n"
        "_MESH_COLLISION_TABLE_CACHE: dict[tuple, dict] = {}\n"
        "\n"
        "\n"
        "\n"
        "class GpuCascadeConfig:\n"
    )
    fixed = (
        "# Process-local collision tables keyed by (mesh, sample, hops, margin, device).\n"
        "# Same rigidized GLB across clips of one unit should not rebuild geodesic pairs.\n"
        "_MESH_COLLISION_TABLE_CACHE: dict[tuple, dict] = {}\n"
        "\n"
        "\n"
        "@dataclass(frozen=True)\n"
        "class GpuCascadeConfig:\n"
    )
    if broken in text:
        text = text.replace(broken, fixed, 1)
        print("fixed dataclass/cache placement")
    elif "_MESH_COLLISION_TABLE_CACHE" not in text:
        raise SystemExit("collision cache global missing")

    old_init = (
        "        self.asset: ProxyAsset = load_asset("
        "Path(src_glb).resolve(), decode_images=True)"
    )
    new_init = (
        "        self.src_glb = Path(src_glb).resolve()\n"
        "        self.asset: ProxyAsset = load_asset(self.src_glb, decode_images=True)"
    )
    if "self.src_glb = Path(src_glb)" not in text:
        text = _replace_once(text, old_init, new_init, "src_glb stash")

    start = text.find("    def _initialize_mesh_collision(self) -> None:")
    if start < 0:
        raise SystemExit("collision init missing")
    rest = text[start + 4 :]
    next_def = rest.find("\n    def ")
    old_fn = text[start : start + 4 + next_def]
    if "cache hit" not in old_fn:
        new_fn = '''    def _initialize_mesh_collision(self) -> None:
        from gpu_mesh_collision import build_backend_collision_table

        mesh_key = str(getattr(self, "src_glb", "") or "")
        if not mesh_key:
            mesh_key = f"asset:{id(self.asset)}"
        cache_key = (
            mesh_key,
            int(self.config.collision_sample_count),
            int(self.config.collision_geodesic_min_hops),
            float(self.config.collision_margin_body_lengths),
            str(self.device),
        )
        cached = _MESH_COLLISION_TABLE_CACHE.get(cache_key)
        if cached is not None:
            self._collision_table = cached
            report = cached["report"]
            print(
                "GPU mesh collision: cache hit "
                f"samples={report['sampleCount']} pairs={report['pairCount']} "
                f"mesh={mesh_key}",
                flush=True,
            )
            return
        self._collision_table = build_backend_collision_table(
            self,
            sample_count=int(self.config.collision_sample_count),
            geodesic_min_hops=int(self.config.collision_geodesic_min_hops),
            margin_body_lengths=float(self.config.collision_margin_body_lengths),
        )
        _MESH_COLLISION_TABLE_CACHE[cache_key] = self._collision_table
        report = self._collision_table["report"]
        print(
            "GPU mesh collision: "
            f"samples={report['sampleCount']} pairs={report['pairCount']} "
            f"hops>={report['geodesicMinHops']} margin={float(report['margin']):.4f} "
            f"islands={report['rawIslandCount']}->{report['weldedIslandCount']} "
            f"crossComponentPairs={report['crossComponentPairs']} "
            f"weight={float(self.config.collision_weight):.2f}",
            flush=True,
        )

'''
        text = text.replace(old_fn, new_fn, 1)
        print("collision cache wired")

    # Root hypothesis -> bool
    start = text.find("    def _root_hypothesis_start(")
    rest = text[start + 4 :]
    next_def = rest.find("\n    def ")
    fn = text[start : start + 4 + next_def]
    if "-> bool:" not in fn.split("\n", 2)[0] and "-> bool:" not in "\n".join(fn.split("\n")[:15]):
        fn2 = fn.replace(
            "        use_current_bones: bool = False,\n    ):",
            "        use_current_bones: bool = False,\n    ) -> bool:",
            1,
        )
        fn2 = fn2.replace(
            "            return\n        if not score_escape and not self.config.root_search_enabled:\n            return\n",
            "            return False\n        if not score_escape and not self.config.root_search_enabled:\n            return False\n",
            1,
        )
        # Generic: any lone `return` at 16-space indent inside this fn that is not `return False/True`
        lines = fn2.splitlines(keepends=True)
        out: list[str] = []
        for line in lines:
            if line == "            return\n" or line == "                return\n":
                indent = line[: len(line) - len(line.lstrip(" "))]
                out.append(f"{indent}return False\n")
            else:
                out.append(line)
        fn2 = "".join(out)
        if not fn2.rstrip().endswith("return True"):
            fn2 = fn2.rstrip() + "\n        return True\n\n"
        text = text.replace(fn, fn2, 1)
        print("root hypothesis returns bool")
    else:
        print("root hypothesis already bool")

    # pass_worst_root_burst short-circuit — locate by unique call site
    marker = "            def pass_worst_root_burst(*, tag: str = \"worst_root_burst\") -> float:"
    if marker not in text:
        raise SystemExit("pass_worst_root_burst missing")
    # Replace the for-loop that calls _root_hypothesis_start inside this function only
    old_loop = (
        "                for position in worst_positions:\n"
        "                    self._root_hypothesis_start(\n"
        "                        bone_vectors,\n"
        "                        root_translation,\n"
        "                        root_rotation,\n"
        "                        position,\n"
        "                        progress=progress,\n"
        "                        started=started,\n"
        "                        score_escape=True,\n"
        "                        use_current_bones=True,\n"
        "                    )\n"
    )
    new_loop = (
        "                held_abort = int(getattr(self.config, \"score_escape_root_held_abort\", 0) or 0)\n"
        "                held_streak = 0\n"
        "                searched_positions: list[int] = []\n"
        "                skipped_positions: list[int] = []\n"
        "                for position in worst_positions:\n"
        "                    improved = bool(\n"
        "                        self._root_hypothesis_start(\n"
        "                            bone_vectors,\n"
        "                            root_translation,\n"
        "                            root_rotation,\n"
        "                            position,\n"
        "                            progress=progress,\n"
        "                            started=started,\n"
        "                            score_escape=True,\n"
        "                            use_current_bones=True,\n"
        "                        )\n"
        "                    )\n"
        "                    searched_positions.append(int(position))\n"
        "                    if improved:\n"
        "                        held_streak = 0\n"
        "                    else:\n"
        "                        held_streak += 1\n"
        "                        if held_abort > 0 and held_streak >= held_abort:\n"
        "                            remain = [\n"
        "                                int(p)\n"
        "                                for p in worst_positions\n"
        "                                if int(p) not in searched_positions\n"
        "                            ]\n"
        "                            skipped_positions.extend(remain)\n"
        "                            if progress:\n"
        "                                print(\n"
        "                                    f\"gpu score_escape {tag} root-search abort \"\n"
        "                                    f\"after {held_streak} held frames; \"\n"
        "                                    f\"skipped={len(remain)}\",\n"
        "                                    flush=True,\n"
        "                                )\n"
        "                            break\n"
    )
    # Only replace first occurrence after pass_worst_root_burst
    burst_at = text.find(marker)
    loop_at = text.find(old_loop, burst_at)
    if loop_at < 0:
        # try alternate kw names from live source
        print("primary loop not found; dumping snippet:")
        print(text[burst_at : burst_at + 1200])
        raise SystemExit("worst root loop missing")
    text = text[:loop_at] + new_loop + text[loop_at + len(old_loop) :]
    print("worst-root held abort wired")

    # Annotate report after that loop: replace worstFrameIndices list source
    old_frames = (
        "                        \"worstFrameIndices\": [\n"
        "                            int(self.frame_indices[position])\n"
        "                            for position in worst_positions\n"
        "                        ],\n"
    )
    new_frames = (
        "                        \"worstFrameIndices\": [\n"
        "                            int(self.frame_indices[position])\n"
        "                            for position in searched_positions\n"
        "                        ],\n"
        "                        \"skippedFrameIndices\": [\n"
        "                            int(self.frame_indices[position])\n"
        "                            for position in skipped_positions\n"
        "                        ],\n"
    )
    frames_at = text.find(old_frames, burst_at)
    if frames_at > 0:
        text = text[:frames_at] + new_frames + text[frames_at + len(old_frames) :]
        print("worst-root report annotated")
    else:
        print("WARN: worstFrameIndices report pattern not found (non-fatal)")

    old_full = (
        "            def run_full_stack(*, round_index: int | None = None) -> float:\n"
        "                before = mean_score()\n"
        "                prefix = f\"r{round_index}_\" if round_index is not None else \"\"\n"
        "                if still_underfit():\n"
        "                    pass_articulated_retry(tag=f\"{prefix}stack_retry\")\n"
        "                if still_underfit():\n"
        "                    pass_coarse_push(tag=f\"{prefix}stack_coarse\")\n"
        "                if still_underfit():\n"
        "                    pass_branch_rescue(tag=f\"{prefix}stack_rescue\")\n"
        "                run_root_escape_passes(prefix=prefix)\n"
        "                return mean_score() - before\n"
    )
    new_full = (
        "            def run_full_stack(*, round_index: int | None = None) -> float:\n"
        "                before = mean_score()\n"
        "                prefix = f\"r{round_index}_\" if round_index is not None else \"\"\n"
        "                fail_fast = bool(getattr(self.config, \"score_escape_fail_fast\", True))\n"
        "                min_gain = float(self.config.score_escape_min_improvement)\n"
        "                prior_gain = False\n"
        "                cursor = before\n"
        "                if still_underfit():\n"
        "                    after = pass_articulated_retry(tag=f\"{prefix}stack_retry\")\n"
        "                    prior_gain = after > cursor + min_gain\n"
        "                    cursor = after\n"
        "                if still_underfit():\n"
        "                    after = pass_coarse_push(tag=f\"{prefix}stack_coarse\")\n"
        "                    prior_gain = prior_gain or after > cursor + min_gain\n"
        "                    cursor = after\n"
        "                if still_underfit() and (prior_gain or not fail_fast):\n"
        "                    after = pass_branch_rescue(tag=f\"{prefix}stack_rescue\")\n"
        "                    prior_gain = prior_gain or after > cursor + min_gain\n"
        "                    cursor = after\n"
        "                elif still_underfit() and fail_fast:\n"
        "                    reports.append(\n"
        "                        {\n"
        "                            \"pass\": f\"{prefix}stack_rescue_skipped_no_prior_gain\",\n"
        "                            \"meanAfter\": cursor,\n"
        "                        }\n"
        "                    )\n"
        "                    if progress:\n"
        "                        print(\n"
        "                            \"gpu score_escape skip rescue: prior passes did not improve\",\n"
        "                            flush=True,\n"
        "                        )\n"
        "                if still_underfit() and (prior_gain or not fail_fast):\n"
        "                    run_root_escape_passes(prefix=prefix)\n"
        "                elif still_underfit() and fail_fast:\n"
        "                    reports.append(\n"
        "                        {\n"
        "                            \"pass\": f\"{prefix}stack_root_skipped_no_prior_gain\",\n"
        "                            \"meanAfter\": mean_score(),\n"
        "                        }\n"
        "                    )\n"
        "                    if progress:\n"
        "                        print(\n"
        "                            \"gpu score_escape skip root bursts: prior passes did not improve\",\n"
        "                            flush=True,\n"
        "                        )\n"
        "                return mean_score() - before\n"
    )
    text = _replace_once(text, old_full, new_full, "run_full_stack")

    old_rescue = (
        "                    if still_underfit():\n"
        "                        pass_branch_rescue(tag=f\"{prefix}worst_stack_rescue\")\n"
        "                    after_round = mean_score()\n"
        "                    reports.append(\n"
        "                        {\n"
        "                            \"pass\": f\"worst_stack_round_{round_index + 1}\",\n"
    )
    new_rescue = (
        "                    round_gain = mean_score() > before_round + float(\n"
        "                        self.config.score_escape_min_improvement\n"
        "                    )\n"
        "                    if still_underfit() and (\n"
        "                        round_gain\n"
        "                        or not bool(getattr(self.config, \"score_escape_fail_fast\", True))\n"
        "                    ):\n"
        "                        pass_branch_rescue(tag=f\"{prefix}worst_stack_rescue\")\n"
        "                    elif still_underfit():\n"
        "                        reports.append(\n"
        "                            {\n"
        "                                \"pass\": f\"{prefix}worst_stack_rescue_skipped_no_prior_gain\",\n"
        "                                \"meanAfter\": mean_score(),\n"
        "                            }\n"
        "                        )\n"
        "                        if progress:\n"
        "                            print(\n"
        "                                \"gpu score_escape skip worst_stack rescue: \"\n"
        "                                \"round had no prior gain\",\n"
        "                                flush=True,\n"
        "                            )\n"
        "                    after_round = mean_score()\n"
        "                    reports.append(\n"
        "                        {\n"
        "                            \"pass\": f\"worst_stack_round_{round_index + 1}\",\n"
    )
    if old_rescue in text:
        text = text.replace(old_rescue, new_rescue, 1)
        print("worst_stack fail-fast rescue")
    else:
        print("WARN: worst_stack rescue pattern not found")

    ast.parse(text)
    path.write_text(text, encoding="utf-8")
    print("cascade patched OK")


def patch_kwargs_passthrough() -> None:
    path = TOOL / "gpu_raster_depth_animation.py"
    text = path.read_text(encoding="utf-8")
    # Add new kwargs next to score_escape_keep_best if missing
    if "score_escape_fail_fast" not in text:
        text = _replace_once(
            text,
            "    score_escape_keep_best: bool = True,\n",
            "    score_escape_keep_best: bool = True,\n"
            "    score_escape_fail_fast: bool = True,\n"
            "    score_escape_root_held_abort: int = 3,\n",
            "raster kwargs defaults",
        )
        text = _replace_once(
            text,
            "        score_escape_keep_best=bool(score_escape_keep_best),\n",
            "        score_escape_keep_best=bool(score_escape_keep_best),\n"
            "        score_escape_fail_fast=bool(score_escape_fail_fast),\n"
            "        score_escape_root_held_abort=int(score_escape_root_held_abort),\n",
            "raster kwargs wiring",
        )
        path.write_text(text, encoding="utf-8")
        print("raster kwargs passthrough")
    else:
        print("raster kwargs already present")

    # Preserve initialization when camera_fit lives under it
    text = path.read_text(encoding="utf-8")
    old = (
        "    output_dir = replace_owned_run_artifacts(Path(output_dir))\n"
        "    from gpu_depth_silhouette_solver import GpuDepthLivePreview, render_chroma_occupancy_preview\n"
        "\n"
        "    camera_fit = Path(camera_fit)\n"
    )
    new = (
        "    output_dir = Path(output_dir)\n"
        "    camera_fit = Path(camera_fit)\n"
        "    wipe_children = OWNED_RUN_CHILDREN\n"
        "    init_dir = (output_dir / \"initialization\").resolve()\n"
        "    if camera_fit.is_file():\n"
        "        try:\n"
        "            camera_fit.resolve().relative_to(init_dir)\n"
        "        except ValueError:\n"
        "            pass\n"
        "        else:\n"
        "            # Reused profile camera lives in this run slot — do not wipe it.\n"
        "            wipe_children = tuple(c for c in OWNED_RUN_CHILDREN if c != \"initialization\")\n"
        "    output_dir = replace_owned_run_artifacts(output_dir, children=wipe_children)\n"
        "    from gpu_depth_silhouette_solver import GpuDepthLivePreview, render_chroma_occupancy_preview\n"
        "\n"
    )
    if "wipe_children = OWNED_RUN_CHILDREN" not in text:
        # function name may differ slightly
        if old not in text:
            # try without the import line variation
            print("WARN: solve wipe block not exact; searching")
            idx = text.find("output_dir = replace_owned_run_artifacts(Path(output_dir))")
            print(repr(text[idx : idx + 250]))
            raise SystemExit("solve wipe block missing")
        text = text.replace(old, new, 1)
        # replace_owned_run_artifacts signature uses children= kw
        # Ensure function accepts children=
        if "def replace_owned_run_artifacts(output_dir: Path, *, children:" not in text:
            raise SystemExit("replace_owned_run_artifacts signature unexpected")
        path.write_text(text, encoding="utf-8")
        print("initialization wipe race fixed")
    else:
        print("wipe race already fixed")


def patch_batch_camera_and_seed() -> None:
    path = TOOL / "run_fused_push_batch_all_units.py"
    text = path.read_text(encoding="utf-8")

    old_seed = (
        "def _seed_profile_camera(choice) -> Path | None:\n"
        "    pilot = Path(choice.pilot_dir)\n"
        "    for subdir in (GPU_RUN_NAME, \"gpu_cascade_delivery\"):\n"
        "        cam = pilot / subdir / \"initialization\" / \"profile_camera_fit.json\"\n"
        "        if cam.is_file():\n"
        "            return cam\n"
        "    return None\n"
    )
    new_seed = (
        "def _seed_profile_camera(choice) -> Path | None:\n"
        "    pilot = Path(choice.pilot_dir)\n"
        "    for subdir in (GPU_RUN_NAME, \"gpu_cascade_delivery\"):\n"
        "        cam = pilot / subdir / \"initialization\" / \"profile_camera_fit.json\"\n"
        "        if cam.is_file():\n"
        "            return cam\n"
        "    # Non-idle clips: reuse the unit idle profile camera when present.\n"
        "    if str(choice.animation_name) != \"idle\":\n"
        "        idle_pilot = pilot.parent / \"idle\"\n"
        "        for subdir in (GPU_RUN_NAME, \"gpu_cascade_delivery\"):\n"
        "            cam = idle_pilot / subdir / \"initialization\" / \"profile_camera_fit.json\"\n"
        "            if cam.is_file():\n"
        "                return cam\n"
        "    return None\n"
    )
    if "idle_pilot = pilot.parent / \"idle\"" not in text:
        text = _replace_once(text, old_seed, new_seed, "profile camera idle fallback")

    idle_seed_helper = '''
def _idle_seed_poses(choice) -> dict[int, dict[str, Any]] | None:
    """Seed non-idle clips from the unit idle solve (frame 0), without skipping articulated."""
    if str(choice.animation_name) == "idle":
        return None
    idle_pilot = Path(choice.pilot_dir).parent / "idle"
    for subdir in (GPU_RUN_NAME, "gpu_cascade_delivery"):
        clip = idle_pilot / subdir / "gpu_clip_result.json"
        if not clip.is_file():
            continue
        payload = json.loads(clip.read_text(encoding="utf-8"))
        poses = payload.get("poses") or {}
        frame0 = poses.get("0", poses.get(0))
        if isinstance(frame0, dict) and frame0:
            return {0: dict(frame0)}
    return None


'''
    if "_idle_seed_poses" not in text:
        text = text.replace(
            "def kwargs_for_choice(",
            idle_seed_helper + "def kwargs_for_choice(",
            1,
        )
        # Inject into kwargs_for_choice before return filter_kwargs
        old_ret = (
            "        if batch and not full_pipeline:\n"
            "            kw[\"idle_fused_macro_enabled\"] = True\n"
            "            kw[\"idle_fused_reroot_transit_after_articulated\"] = True\n"
            "    return filter_kwargs(kw)\n"
        )
        new_ret = (
            "        if batch and not full_pipeline:\n"
            "            kw[\"idle_fused_macro_enabled\"] = True\n"
            "            kw[\"idle_fused_reroot_transit_after_articulated\"] = True\n"
            "    seed_poses = _idle_seed_poses(choice)\n"
            "    if seed_poses is not None:\n"
            "        kw[\"initial_poses\"] = seed_poses\n"
            "        # Seed from idle, but still run articulated refine on motion.\n"
            "        kw[\"articulated_skip_when_seeded\"] = False\n"
            "        kw[\"root_skip_when_seeded\"] = False\n"
            "    return filter_kwargs(kw)\n"
        )
        text = _replace_once(text, old_ret, new_ret, "idle pose injection")

    # --animation filter
    if '"--animation"' not in text and "'--animation'" not in text:
        text = _replace_once(
            text,
            '    parser.add_argument(\n'
            '        "--limit-clips",\n',
            '    parser.add_argument(\n'
            '        "--animation",\n'
            '        default="",\n'
            '        help="optional animation name filter (e.g. idle_start_move_end)",\n'
            '    )\n'
            '    parser.add_argument(\n'
            '        "--limit-clips",\n',
            "animation CLI",
        )
        # Filter jobs after building
        old_jobs = "    want_preview = bool(args.preview_gif)\n"
        new_jobs = (
            "    animation_filter = str(args.animation or \"\").strip()\n"
            "    if animation_filter:\n"
            "        jobs = [\n"
            "            (row, choice)\n"
            "            for row, choice in jobs\n"
            "            if str(choice.animation_name) == animation_filter\n"
            "        ]\n"
            "        print(\n"
            "            f\"animation filter={animation_filter!r} jobs={len(jobs)}\",\n"
            "            flush=True,\n"
            "        )\n"
            "    want_preview = bool(args.preview_gif)\n"
        )
        text = _replace_once(text, old_jobs, new_jobs, "animation filter apply")

    ast.parse(text)
    path.write_text(text, encoding="utf-8")
    print("batch camera/seed/animation patched OK")


def main() -> None:
    patch_cascade()
    patch_kwargs_passthrough()
    patch_batch_camera_and_seed()
    print("ALL PATCHES DONE")


if __name__ == "__main__":
    main()
