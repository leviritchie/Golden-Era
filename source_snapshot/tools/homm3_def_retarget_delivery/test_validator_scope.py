"""Focused tests for delivery-validator selection scoping and bundle integrity.

    python tools/homm3_def_retarget_delivery/test_validator_scope.py
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import validate_custom_faction_manifests as manifests  # noqa: E402
import validate_homm3_def_retarget_delivery_contract as delivery  # noqa: E402


class BoundedReadStream(io.BytesIO):
    MAX_READ = 1 << 20

    def __init__(self, payload: bytes):
        super().__init__(payload)
        self.read_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        if size <= 0 or size > self.MAX_READ:
            raise AssertionError(f"bundle read must be bounded to {self.MAX_READ} bytes; got {size}")
        self.read_sizes.append(size)
        return super().read(size)


class DeliverySelectionScope(unittest.TestCase):
    def run_main(self, *args: str, selection_checks=None) -> tuple[int, str, list[str], list[str]]:
        checked: list[str] = []
        global_checks: list[str] = []

        def record_selection(_root, path, _require_installed, _errors):
            checked.append(path.name)
            return "fixture"

        def record_static(_root, _errors):
            global_checks.append("static")

        def record_repin(_root, _errors):
            global_checks.append("repin")

        with (
            mock.patch.object(delivery, "static_checks", side_effect=record_static),
            mock.patch.object(delivery, "repin_checks", side_effect=record_repin),
            mock.patch.object(delivery, "selection_checks", side_effect=selection_checks or record_selection),
            mock.patch.object(sys, "argv", ["validator", "--repo-root", str(ROOT), *args]),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            result = delivery.main()
        return result, output.getvalue(), checked, global_checks

    def test_default_checks_every_selection(self):
        result, output, checked, global_checks = self.run_main()
        expected = sorted(path.name for path in (ROOT / "tools/homm3_def_retarget_delivery").glob("*.json"))

        self.assertEqual(result, 0)
        self.assertEqual(checked, expected)
        self.assertEqual(global_checks, ["static", "repin"])
        self.assertIn(f"scope=all ({len(expected)}/{len(expected)})", output)

    def test_explicit_selection_checks_only_exact_basename(self):
        selections = sorted((ROOT / "tools/homm3_def_retarget_delivery").glob("*.json"))
        selected = selections[0].name
        result, output, checked, global_checks = self.run_main("--selection", selected)

        self.assertEqual(result, 0)
        self.assertEqual(checked, [selected])
        self.assertEqual(global_checks, ["static", "repin"])
        self.assertIn(f"scope=selected (1/{len(selections)}: {selected})", output)

    def test_selection_flag_is_repeatable(self):
        selections = sorted((ROOT / "tools/homm3_def_retarget_delivery").glob("*.json"))[:2]
        names = [path.name for path in selections]
        args = [item for name in names for item in ("--selection", name)]
        result, output, checked, _global_checks = self.run_main(*args)

        self.assertEqual(result, 0)
        self.assertEqual(checked, names)
        self.assertIn(f"scope=selected (2/", output)

    def test_unknown_selection_fails_closed_without_running_selection_checks(self):
        selected = sorted((ROOT / "tools/homm3_def_retarget_delivery").glob("*.json"))[0].name
        result, output, checked, global_checks = self.run_main("--selection", selected, "--selection", "..\\a_slice.json")

        self.assertEqual(result, 1)
        self.assertEqual(checked, [])
        self.assertEqual(global_checks, ["static", "repin"])
        self.assertIn("unknown delivery selection(s)", output)
        self.assertIn("scope=invalid", output)

    def test_empty_selection_directory_fails_closed(self):
        selected, available, scope, errors = delivery.resolve_selection_scope(
            ROOT / "validator_scope_missing_fixture",
            None,
        )

        self.assertEqual(selected, [])
        self.assertEqual(available, [])
        self.assertEqual(scope, "all (0/0)")
        self.assertTrue(any("no delivery selection JSON files found" in error for error in errors))


class ManifestValidationPerformance(unittest.TestCase):
    def test_generator_overlay_is_parsed_once_per_validation(self):
        validation = manifests.Validation()
        with mock.patch.object(manifests.ast, "parse", wraps=manifests.ast.parse) as parse:
            manifests.validate_fortress_core_generator_toa_overlay(validation)

        self.assertEqual(parse.call_count, 1)
        self.assertEqual(validation.errors, [])

    def test_bundle_hashing_streams_and_keeps_source_and_installed_evidence_separate(self):
        bundle_name = "custom_units_fixture.bundle"
        source_payload = bytes(range(256)) * 4097
        installed_payload = source_payload[:-1] + bytes((source_payload[-1] ^ 1,))
        source_root = Path("source")
        installed_root = Path("installed")
        source_dir = source_root / "homm3_bundles"
        installed_dir = installed_root / "homm3_bundles"
        source_bundle = source_dir / bundle_name
        installed_bundle = installed_dir / bundle_name
        payloads = {source_bundle: source_payload, installed_bundle: installed_payload}
        opened_streams: list[BoundedReadStream] = []
        contract = {
            bundle_name: {
                "length": len(source_payload),
                "sha256": hashlib.sha256(source_payload).hexdigest().upper(),
            }
        }

        def is_file(path):
            return path in payloads

        def is_dir(path):
            return path in {source_dir, installed_dir}

        def stat(path):
            return SimpleNamespace(st_size=len(payloads[path]))

        def open_payload(path, mode="r", **_kwargs):
            if mode != "rb":
                raise AssertionError(f"unexpected bundle open mode: {mode}")
            stream = BoundedReadStream(payloads[path])
            opened_streams.append(stream)
            return stream

        def iterdir(path):
            if path == source_dir:
                return iter([source_bundle])
            if path == installed_dir:
                return iter([installed_bundle])
            raise AssertionError(f"unexpected directory scan: {path}")

        source_validation = manifests.Validation()
        installed_validation = manifests.Validation()
        with (
            mock.patch.object(manifests, "load_homm3_bundle_payload_contract", return_value=contract),
            mock.patch.object(Path, "is_file", autospec=True, side_effect=is_file),
            mock.patch.object(Path, "is_dir", autospec=True, side_effect=is_dir),
            mock.patch.object(Path, "stat", autospec=True, side_effect=stat),
            mock.patch.object(Path, "open", autospec=True, side_effect=open_payload),
            mock.patch.object(Path, "iterdir", autospec=True, side_effect=iterdir),
            mock.patch.object(Path, "read_bytes", side_effect=AssertionError("bundle hashing must stream")),
        ):
            manifests.validate_homm3_bundle_payload_contract(
                {"unit": {"bundleName": bundle_name}},
                source_validation,
                plugin_root=source_root,
            )
            manifests.validate_homm3_bundle_payload_contract(
                {"unit": {"bundleName": bundle_name}},
                installed_validation,
                plugin_root=installed_root,
            )

        self.assertEqual(source_validation.errors, [])
        self.assertEqual(len(installed_validation.errors), 1)
        self.assertIn("sha256 mismatch", installed_validation.errors[0])
        self.assertEqual(len(opened_streams), 2)
        self.assertTrue(all(stream.read_sizes for stream in opened_streams))
        self.assertTrue(all(max(stream.read_sizes) <= BoundedReadStream.MAX_READ for stream in opened_streams))
        self.assertTrue(all(len(stream.read_sizes) > 1 for stream in opened_streams))


if __name__ == "__main__":
    unittest.main()
