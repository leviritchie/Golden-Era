#!/usr/bin/env python3
"""Small synthetic fixtures for the prepared campaign-video delivery layer."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import stage_campaign_video_dependencies as stage  # noqa: E402


SEVEN_ZIP = Path("C:/Program Files/7-Zip/7z.exe")
GOOD1 = "homm3_01_roe_castle_good1"


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def clip_row(key: str, *, subtitles: bool = False, name: str | None = None) -> dict:
    return {"key": key, "val": {
        "name": name or f"{key}.mp4", "canSkip": True, "haveSubtitles": subtitles,
        "skipByHoldingEsc": True, "playVideoShowAnimation": False,
    }}


def make_core(path: Path, *, hubs: dict[str, dict], rows: list[dict], loc: dict | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("DB/clips_info.json", json_bytes({"array": {"data": rows}}))
        for folder, story in hubs.items():
            archive.writestr(f"campaigns/{folder}/storyHub.json", json_bytes(story))
        if loc is not None:
            archive.writestr(stage.CINEMATIC_MEMBER, json_bytes(loc))
        archive.writestr("DB/data.json", b"{}\n")


def selected_hub() -> dict:
    return {"sid": GOOD1, "nested": {"nodes": [{"interactionActions": [
        {"type": "PlayVideo", "values": ["Good1a", "Good1b"]},
    ]}]}}


def other_hub() -> dict:
    return {"sid": "other", "nodes": [{"interactionActions": [
        {"type": "PlayVideo", "values": ["UnselectedClip"]},
    ]}]}


class CampaignVideoDependenciesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        scratch_root = Path(os.environ.get(
            "CAMPAIGN_VIDEO_FIXTURE_ROOT",
            str(Path(__file__).resolve().parent / ".campaign_video_fixture_tmp"),
        ))
        scratch_root.mkdir(parents=True, exist_ok=True)
        cls.temp_root = scratch_root / f"campaign_video_dependency_fixtures_{uuid.uuid4().hex}"
        cls.temp_root.mkdir()

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.temp_root)

    def make_pair(self, name: str) -> tuple[Path, Path, Path, Path]:
        base = self.temp_root / name
        source = base / "source"
        target = base / "target"
        work = base / "work"
        report = work / "report.json"
        hubs = {GOOD1: selected_hub(), "other_campaign": other_hub()}
        source_rows = [clip_row("Good1a", subtitles=True), clip_row("Good1b"),
                       clip_row("UnselectedClip"), clip_row("SourceOnly")]
        target_rows = [clip_row("NativeKeep")]
        source_loc = {"tokens": [
            {"sid": "sid.good1a.1", "text": "Prepared subtitle"},
            {"sid": "sid.unused", "text": "Must not copy"},
        ], "array": [
            {"sid": "sid.good1a.1", "text": "Prepared subtitle"},
            {"sid": "sid.unused", "text": "Must not copy"},
        ]}
        target_loc = {"tokens": [{"sid": "native.keep", "text": "Native text"}]}
        make_core(source / stage.CORE_REL, hubs=hubs, rows=source_rows, loc=source_loc)
        make_core(target / stage.CORE_REL, hubs=hubs, rows=target_rows, loc=target_loc)
        video = source / stage.VIDEO_REL
        video.mkdir(parents=True)
        (video / "Good1a.mp4").write_bytes(b"prepared-good1a-video")
        (video / "Good1a.mp4.json").write_bytes(json_bytes({"subtitles": [
            {"sid": "sid.good1a.1", "start": 0.0, "end": 2.5},
        ]}))
        (video / "Good1b.mp4").write_bytes(b"prepared-good1b-video")
        (video / "UnselectedClip.mp4").write_bytes(b"prepared-other-campaign-video")
        target_video = target / stage.VIDEO_REL
        target_video.mkdir(parents=True)
        (target_video / "native.keep").write_bytes(b"must remain")
        return source, target, work, report

    def test_source_plan_merges_only_selected_rows_and_sids(self) -> None:
        source, target, _work, _report = self.make_pair("plan")
        source_core, _ = stage._validate_root(source, target=False)
        target_core, _ = stage._validate_root(target, target=True)
        with zipfile.ZipFile(target_core) as archive:
            keys = stage._play_video_keys(stage._story_hubs(archive, GOOD1))
        clips, changed, _before, _hashes = stage._merge_core_candidates(
            target_core=target_core, source_core=source_core, keys=keys,
            source_root=source, target_root=target,
        )
        self.assertEqual(keys, ["Good1a", "Good1b"])
        self.assertEqual({clip.key for clip in clips}, set(keys))
        self.assertEqual(set(changed), {stage.CLIPS_MEMBER, stage.CINEMATIC_MEMBER})
        merged_clips = json.loads(changed[stage.CLIPS_MEMBER])
        self.assertEqual({row["key"] for row in merged_clips["array"]["data"]},
                         {"NativeKeep", "Good1a", "Good1b"})
        merged_loc = json.loads(changed[stage.CINEMATIC_MEMBER])
        self.assertEqual(set(merged_loc), {"tokens"})
        self.assertEqual({row["sid"] for row in merged_loc["tokens"]}, {"native.keep", "sid.good1a.1"})
        self.assertNotIn("UnselectedClip", {row["key"] for row in merged_clips["array"]["data"]})
        self.assertNotIn("sid.unused", {row["sid"] for row in merged_loc["tokens"]})

    def test_default_plan_unions_all_campaign_storyhubs(self) -> None:
        source, target, _work, _report = self.make_pair("all_campaigns")
        source_core, _ = stage._validate_root(source, target=False)
        target_core, _ = stage._validate_root(target, target=True)
        with zipfile.ZipFile(target_core) as archive:
            hubs = stage._story_hubs(archive, None)
        keys = stage._play_video_keys(hubs)
        self.assertEqual(set(hubs), {GOOD1, "other_campaign"})
        self.assertEqual(keys, ["Good1a", "Good1b", "UnselectedClip"])
        clips, _changed, _before, _hashes = stage._merge_core_candidates(
            target_core=target_core, source_core=source_core, keys=keys,
            source_root=source, target_root=target,
        )
        self.assertEqual({clip.key for clip in clips}, set(keys))

    def test_candidate_may_add_only_missing_cinematic_member(self) -> None:
        source, target, work, report = self.make_pair("missing_target_cinematic")
        make_core(target / stage.CORE_REL,
                  hubs={GOOD1: selected_hub(), "other_campaign": other_hub()},
                  rows=[clip_row("NativeKeep")], loc=None)
        fake_seven_zip = work / "fake-7z.exe"
        work.mkdir(parents=True, exist_ok=True)
        fake_seven_zip.write_bytes(b"test stub")

        def update_candidate(_executable: Path, candidate: Path, stage_root: Path, members: list[str]) -> None:
            rewritten = candidate.with_suffix(".fixture.zip")
            with zipfile.ZipFile(candidate, "r") as original:
                content = {info.filename: (info, original.read(info.filename)) for info in original.infolist()}
            for member in members:
                content[member] = (None, stage_root.joinpath(*member.split("/")).read_bytes())
            with zipfile.ZipFile(rewritten, "w", compression=zipfile.ZIP_DEFLATED) as output:
                for name, (info, data) in content.items():
                    output.writestr(info if info is not None else name, data)
            rewritten.replace(candidate)

        with mock.patch.object(stage, "_seven_zip_update", side_effect=update_candidate), \
                mock.patch.object(stage, "assert_no_running_game_process"):
            result = stage.stage_campaign_video_dependencies(
                source_game_root=source, game_root=target, hub=GOOD1,
                work=work, report_path=report, seven_zip=fake_seven_zip,
            )
        self.assertEqual(result["status"], "staged")
        with zipfile.ZipFile(target / stage.CORE_REL) as archive:
            self.assertIn(stage.CINEMATIC_MEMBER, archive.namelist())
            merged_loc = json.loads(archive.read(stage.CINEMATIC_MEMBER))
        self.assertEqual({row["sid"] for row in merged_loc["tokens"]},
                         {"sid.good1a.1"})
        check = stage.stage_campaign_video_dependencies(
            game_root=target, work=work, report_path=work / "check.json",
            hub=GOOD1, check_only=True,
        )
        self.assertEqual(check["status"], "checked")

    def test_secondary_loc_sections_are_optional_but_checked_when_populated(self) -> None:
        source, target, _work, _report = self.make_pair("optional_source_array")
        self.rewrite_core_json(source / stage.CORE_REL, stage.CINEMATIC_MEMBER,
                               lambda doc: doc["array"].clear())
        self.plan(source, target)

        source, target, _work, _report = self.make_pair("source_array_mismatch")
        self.rewrite_core_json(source / stage.CORE_REL, stage.CINEMATIC_MEMBER,
                               lambda doc: doc["array"][0].update(text="different"))
        with self.assertRaisesRegex(stage.DependencyError, "disagrees between tokens and array"):
            self.plan(source, target)

        source, target, _work, _report = self.make_pair("target_array_merge")
        self.rewrite_core_json(target / stage.CORE_REL, stage.CINEMATIC_MEMBER,
                               lambda doc: doc.update(array=[]))
        _clips, changed, _before, _hashes = self.plan_with_result(source, target)
        self.assertIn(stage.CINEMATIC_MEMBER, changed)
        merged_loc = json.loads(changed[stage.CINEMATIC_MEMBER])
        self.assertIn("array", merged_loc)
        self.assertIn("sid.good1a.1", {row["sid"] for row in merged_loc["array"]})

    def test_game_process_name_match_is_exact_and_case_insensitive(self) -> None:
        self.assertTrue(stage._is_running_game_row("HeroesOldenEra.exe"))
        self.assertTrue(stage._is_running_game_row("heroesoldenERA.EXE"))
        self.assertFalse(stage._is_running_game_row("OtherGame.exe"))

    def test_outputs_cannot_target_steam_or_escape_work(self) -> None:
        _source, target, work, _report = self.make_pair("output_paths")
        steam_work = Path("V:/SteamLibrary/steamapps/common/fixture-output")
        with self.assertRaisesRegex(stage.DependencyError, "Steam steamapps/common"):
            stage.stage_campaign_video_dependencies(
                game_root=target, hub=GOOD1, check_only=True, work=steam_work,
                report_path=steam_work / "report.json",
            )
        with self.assertRaisesRegex(stage.DependencyError, "inside --work"):
            stage.stage_campaign_video_dependencies(
                game_root=target, hub=GOOD1, check_only=True, work=work,
                report_path=work.parent / "outside-report.json",
            )

    def test_output_layout_cannot_overwrite_donor_or_target(self) -> None:
        source, target, work, _report = self.make_pair("layout")
        core = target / stage.CORE_REL
        original = stage.sha256_file(core)
        with self.assertRaisesRegex(stage.DependencyError, "inside prepared source"):
            stage.stage_campaign_video_dependencies(
                source_game_root=source, game_root=target, hub=GOOD1,
                work=source / "scratch", report_path=work / "report.json",
            )
        with self.assertRaisesRegex(stage.DependencyError, "report.*inside target"):
            stage.stage_campaign_video_dependencies(
                game_root=target, hub=GOOD1, check_only=True,
                work=work, report_path=core,
            )
        self.assertEqual(stage.sha256_file(core), original)

    def test_prepared_asset_only_delivery_and_check_only(self) -> None:
        source, target, work, report = self.make_pair("asset_only")
        self.prepare_existing_core_closure(source, target)
        core = target / stage.CORE_REL
        core_before = stage.sha256_file(core)
        result = stage.stage_campaign_video_dependencies(
            source_game_root=source, game_root=target, hub=GOOD1, work=work, report_path=report,
        )
        self.assertEqual(result["status"], "staged")
        self.assertEqual(result["changedMembers"], [])
        self.assertEqual(stage.sha256_file(core), core_before)
        self.assertEqual({Path(item).name for item in result["changedFiles"]},
                         {"Good1a.mp4", "Good1a.mp4.json", "Good1b.mp4"})
        check = stage.stage_campaign_video_dependencies(
            game_root=target, work=work, report_path=work / "check.json", hub=GOOD1, check_only=True,
        )
        self.assertEqual(check["status"], "checked")

    def test_running_game_guard_prevents_target_writes(self) -> None:
        source, target, work, report = self.make_pair("process_guard")
        self.prepare_existing_core_closure(source, target)
        core_before = stage.sha256_file(target / stage.CORE_REL)
        with mock.patch.object(stage, "assert_no_running_game_process",
                               side_effect=stage.DependencyError("game process present")):
            with self.assertRaisesRegex(stage.DependencyError, "game process present"):
                stage.stage_campaign_video_dependencies(
                    source_game_root=source, game_root=target, hub=GOOD1, work=work, report_path=report,
                )
        self.assertEqual(stage.sha256_file(target / stage.CORE_REL), core_before)
        self.assertEqual(sorted(path.name for path in (target / stage.VIDEO_REL).iterdir()), ["native.keep"])

    def test_created_video_directory_is_reported_on_later_guard_failure(self) -> None:
        source, target, work, report = self.make_pair("created_video_dir")
        self.prepare_existing_core_closure(source, target)
        target_video = target / stage.VIDEO_REL
        shutil.rmtree(target_video)
        guard = mock.Mock(side_effect=[None, None, stage.DependencyError("game started during staging")])
        with mock.patch.object(stage, "assert_no_running_game_process", guard):
            with self.assertRaisesRegex(stage.DependencyError, "game started during staging"):
                stage.stage_campaign_video_dependencies(
                    source_game_root=source, game_root=target, hub=GOOD1, work=work, report_path=report,
                )
        result = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "partial_failure")
        self.assertEqual(result["mutatedPaths"], [str(target_video)])
        self.assertTrue(target_video.is_dir())

    def test_missing_row_video_sidecar_or_sid_fails_before_target_mutation(self) -> None:
        for fault in ("row", "video", "sidecar", "sid"):
            with self.subTest(fault=fault):
                source, target, work, report = self.make_pair(f"missing_{fault}")
                source_core = source / stage.CORE_REL
                if fault == "row":
                    self.rewrite_core_json(source_core, stage.CLIPS_MEMBER,
                                           lambda doc: doc["array"]["data"].remove(
                                               next(row for row in doc["array"]["data"] if row["key"] == "Good1a")))
                elif fault == "video":
                    (source / stage.VIDEO_REL / "Good1a.mp4").unlink()
                elif fault == "sidecar":
                    (source / stage.VIDEO_REL / "Good1a.mp4.json").unlink()
                else:
                    self.rewrite_core_json(source_core, stage.CINEMATIC_MEMBER,
                                           lambda doc: doc["tokens"].clear())
                before_core = stage.sha256_file(target / stage.CORE_REL)
                before_target_files = sorted(str(path.relative_to(target)) for path in target.rglob("*"))
                with self.assertRaises(stage.DependencyError):
                    stage.stage_campaign_video_dependencies(
                        source_game_root=source, game_root=target, hub=GOOD1,
                        work=work, report_path=report,
                    )
                self.assertEqual(stage.sha256_file(target / stage.CORE_REL), before_core)
                self.assertEqual(sorted(str(path.relative_to(target)) for path in target.rglob("*")), before_target_files)

    def test_traversal_duplicate_and_conflicting_rows_fail_closed(self) -> None:
        source, target, _work, _report = self.make_pair("invalid_rows")
        source_core = source / stage.CORE_REL
        self.rewrite_core_json(source_core, stage.CLIPS_MEMBER, lambda doc: next(
            row for row in doc["array"]["data"] if row["key"] == "Good1a")["val"].update(name="../escape.mp4"))
        with self.assertRaisesRegex(stage.DependencyError, "safe basename"):
            self.plan(source, target)

        source, target, _work, _report = self.make_pair("duplicate_rows")
        self.rewrite_core_json(source / stage.CORE_REL, stage.CLIPS_MEMBER, lambda doc:
                               doc["array"]["data"].append(clip_row("Good1a", subtitles=True)))
        with self.assertRaisesRegex(stage.DependencyError, "duplicate clip key"):
            self.plan(source, target)

        source, target, _work, _report = self.make_pair("conflicting_rows")
        self.rewrite_core_json(target / stage.CORE_REL, stage.CLIPS_MEMBER, lambda doc:
                               doc["array"]["data"].append(clip_row("Good1a", name="different.mp4")))
        with self.assertRaisesRegex(stage.DependencyError, "conflicting selected row"):
            self.plan(source, target)

    def test_check_only_fails_when_selected_closure_is_missing(self) -> None:
        _source, target, work, report = self.make_pair("check_missing")
        before = stage.sha256_file(target / stage.CORE_REL)
        with self.assertRaisesRegex(stage.DependencyError, "no row for PlayVideo key"):
            stage.stage_campaign_video_dependencies(
                game_root=target, work=work, report_path=report, hub=GOOD1, check_only=True,
            )
        self.assertEqual(stage.sha256_file(target / stage.CORE_REL), before)
        self.assertTrue(report.is_file())

    @unittest.skipUnless(os.environ.get("RUN_CAMPAIGN_VIDEO_7Z_FIXTURE") == "1" and SEVEN_ZIP.is_file(),
                        "opt-in fixture; ordinary contract runs keep external 7-Zip out of the test path")
    def test_seven_zip_staging_and_readback_once(self) -> None:
        source, target, work, report = self.make_pair("seven_zip")
        t0 = time.perf_counter()
        result = stage.stage_campaign_video_dependencies(
            source_game_root=source, game_root=target, work=work,
            report_path=report, seven_zip=SEVEN_ZIP,
        )
        elapsed = time.perf_counter() - t0
        self.assertEqual(result["status"], "staged")
        self.assertEqual(set(result["changedMembers"]), {stage.CLIPS_MEMBER, stage.CINEMATIC_MEMBER})
        self.assertEqual({Path(item).name for item in result["changedFiles"]},
                         {"Good1a.mp4", "Good1a.mp4.json", "Good1b.mp4", "UnselectedClip.mp4"})
        self.assertTrue((target / stage.VIDEO_REL / "native.keep").is_file())
        self.assertTrue((target / stage.VIDEO_REL / "UnselectedClip.mp4").is_file())
        check = stage.stage_campaign_video_dependencies(
            game_root=target, work=work, report_path=work / "check.json", check_only=True,
        )
        self.assertEqual(check["status"], "checked")
        self.assertEqual({item["key"] for item in check["clips"]}, {"Good1a", "Good1b", "UnselectedClip"})
        sys.stderr.write(
            f"fixture 7z staging elapsed={elapsed:.3f}s; processMemory={result['processMemory']}; "
            f"source={result['sourceCoreSha256']} target={result['coreSha256After']}\n"
        )

    def plan(self, source: Path, target: Path) -> None:
        self.plan_with_result(source, target)

    def plan_with_result(self, source: Path, target: Path):
        source_core, _ = stage._validate_root(source, target=False)
        target_core, _ = stage._validate_root(target, target=True)
        with zipfile.ZipFile(target_core) as archive:
            keys = stage._play_video_keys(stage._story_hubs(archive, GOOD1))
        return stage._merge_core_candidates(target_core=target_core, source_core=source_core, keys=keys,
                                            source_root=source, target_root=target)

    @staticmethod
    def prepare_existing_core_closure(source: Path, target: Path) -> None:
        source_core = source / stage.CORE_REL
        with zipfile.ZipFile(source_core) as archive:
            source_clips = json.loads(archive.read(stage.CLIPS_MEMBER))
            source_loc = json.loads(archive.read(stage.CINEMATIC_MEMBER))
        selected_rows = [row for row in source_clips["array"]["data"] if row["key"] in {"Good1a", "Good1b"}]
        (target / stage.CORE_REL).parent.mkdir(parents=True, exist_ok=True)
        CampaignVideoDependenciesTest.rewrite_core_json(
            target / stage.CORE_REL, stage.CLIPS_MEMBER,
            lambda doc: doc["array"]["data"].extend(selected_rows),
        )
        referenced_sid = "sid.good1a.1"
        source_token = next(row for row in source_loc["tokens"] if row["sid"] == referenced_sid)
        CampaignVideoDependenciesTest.rewrite_core_json(
            target / stage.CORE_REL, stage.CINEMATIC_MEMBER,
            lambda doc: doc["tokens"].append(source_token),
        )

    @staticmethod
    def rewrite_core_json(core: Path, member: str, mutate) -> None:
        temp = core.with_suffix(".rewrite.zip")
        with zipfile.ZipFile(core) as original, zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as changed:
            for info in original.infolist():
                content = original.read(info.filename)
                if info.filename == member:
                    doc = json.loads(content.decode("utf-8"))
                    mutate(doc)
                    content = json_bytes(doc)
                changed.writestr(info.filename, content)
        temp.replace(core)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract-fast", action="store_true",
                        help="run synthetic fixtures only; never invoke the 7-Zip executable")
    parser.add_argument("--scratch-root", type=Path,
                        help="temporary fixture parent; defaults to a repo-local V: path")
    options, unittest_args = parser.parse_known_args()
    if options.scratch_root is not None:
        os.environ["CAMPAIGN_VIDEO_FIXTURE_ROOT"] = str(options.scratch_root.resolve())
    if options.contract_fast:
        os.environ.pop("RUN_CAMPAIGN_VIDEO_7Z_FIXTURE", None)
    unittest.main(argv=[sys.argv[0], *unittest_args], verbosity=2)
