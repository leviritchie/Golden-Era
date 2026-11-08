from __future__ import annotations

import hashlib
import json
import shutil
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from experiments.campaign_port_poc.procedural_scenarios.bundle import (
    BUNDLE_SCHEMA,
    verify_source_artifacts,
    write_source_artifacts,
)
from experiments.campaign_port_poc.procedural_scenarios.catalog import _manifest_entries
from experiments.campaign_port_poc.procedural_scenarios.installer import (
    InstallationError,
    _assert_bundled_source_artifacts,
)
from experiments.campaign_port_poc.procedural_scenarios.validator import validate_bundle


@contextmanager
def _temporary_root():
    root = Path("build") / "procedural_source_contract_tests" / uuid.uuid4().hex
    root.mkdir(parents=True)
    try:
        yield root
    finally:
        shutil.rmtree(root)


class SourceArtifactContractTests(unittest.TestCase):
    def test_custom_sources_are_read_once_and_captured_as_exact_bytes(self) -> None:
        with _temporary_root() as root:
            asset = root / "asset.bin"
            asset_payload = b"custom-content-payload\x00\xff"
            asset.write_bytes(asset_payload)
            manifest = root / "custom.json"
            manifest_payload = json.dumps(
                {
                    "schema": "homm3.procedural_content_manifest.v1",
                    "files": {
                        "asset.bin": hashlib.sha256(asset_payload).hexdigest()
                    },
                    "content": [
                        {
                            "sid": "custom_reward",
                            "kind": "reward",
                            "footprint": {
                                "width": 1,
                                "height": 1,
                                "occupied": [[0, 0]],
                            },
                        }
                    ],
                },
                sort_keys=True,
            ).encode("utf-8")
            manifest.write_bytes(manifest_payload)

            path_type = type(manifest)
            original_read_bytes = path_type.read_bytes
            reads: list[Path] = []

            def tracked_read_bytes(path: Path) -> bytes:
                reads.append(path.resolve())
                return original_read_bytes(path)

            with mock.patch.object(
                path_type,
                "read_bytes",
                autospec=True,
                side_effect=tracked_read_bytes,
            ):
                _, hashes, artifacts = _manifest_entries(
                    manifest,
                    allowlist=frozenset(),
                )

            self.assertEqual(1, reads.count(manifest.resolve()))
            self.assertEqual(1, reads.count(asset.resolve()))
            artifact_by_hash = {artifact.sha256: artifact.payload for artifact in artifacts}
            self.assertEqual(manifest_payload, artifact_by_hash[hashlib.sha256(manifest_payload).hexdigest()])
            self.assertEqual(asset_payload, artifact_by_hash[hashlib.sha256(asset_payload).hexdigest()])
            self.assertEqual(
                {artifact.sha256 for artifact in artifacts},
                {digest for _, digest in hashes},
            )

    def test_writer_rejects_hostile_hash_before_any_escape_write(self) -> None:
        with _temporary_root() as root:
            escape_path = root.parent / f"escape_{uuid.uuid4().hex}"
            source_key = "custom-manifest/hostile"
            hostile_hash = f"../../{escape_path.name}"
            with self.assertRaisesRegex(ValueError, "lowercase sha256"):
                write_source_artifacts(
                    root,
                    {"core": "a" * 64, source_key: hostile_hash},
                    {source_key: b"must not escape"},
                )
            self.assertFalse(escape_path.exists())
    def test_bundled_source_evidence_verifies_and_tampering_fails_closed(self) -> None:
        with _temporary_root() as root:
            payload = b"immutable custom source"
            digest = hashlib.sha256(payload).hexdigest()
            source_key = "custom-manifest/" + digest
            source_hashes = {"core": "a" * 64, source_key: digest}
            bindings, files = write_source_artifacts(
                root,
                source_hashes,
                {source_key: payload},
            )
            manifest = {
                "sourceHashes": source_hashes,
                "sourceArtifacts": bindings,
                "files": files,
            }

            self.assertEqual((source_key,), verify_source_artifacts(manifest, root))
            self.assertEqual(
                (source_key,),
                _assert_bundled_source_artifacts(manifest, root),
            )

            (root / bindings[source_key]).write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                verify_source_artifacts(manifest, root)
            with self.assertRaisesRegex(InstallationError, "source evidence is invalid"):
                _assert_bundled_source_artifacts(manifest, root)

    def test_non_core_source_hash_without_bundled_evidence_is_rejected(self) -> None:
        digest = hashlib.sha256(b"missing").hexdigest()
        manifest = {
            "sourceHashes": {
                "core": "b" * 64,
                "custom-manifest/" + digest: digest,
            },
            "files": {},
        }
        with _temporary_root() as root:
            with self.assertRaisesRegex(ValueError, "sourceArtifacts"):
                verify_source_artifacts(manifest, root)

    def test_hostile_and_extra_source_bindings_are_rejected(self) -> None:
        digest = hashlib.sha256(b"hostile").hexdigest()
        source_key = "custom-manifest/" + digest
        with _temporary_root() as root:
            traversal = {
                "sourceHashes": {"core": "d" * 64, source_key: digest},
                "sourceArtifacts": {source_key: "sources/../outside"},
                "files": {"sources/../outside": digest},
            }
            with self.assertRaisesRegex(ValueError, "unsafe bundled source"):
                verify_source_artifacts(traversal, root)

            alias = {
                "sourceHashes": {"core": "d" * 64, source_key: digest},
                "sourceArtifacts": {source_key: "sources/not-content-addressed"},
                "files": {"sources/not-content-addressed": digest},
            }
            with self.assertRaisesRegex(ValueError, "content-addressed path"):
                verify_source_artifacts(alias, root)

            extra = {
                "sourceHashes": {"core": "d" * 64},
                "sourceArtifacts": {source_key: "sources/" + digest},
                "files": {"sources/" + digest: digest},
            }
            with self.assertRaisesRegex(ValueError, "extra"):
                verify_source_artifacts(extra, root)

            malformed = {
                "sourceHashes": {1: digest},
                "sourceArtifacts": {},
                "files": {},
            }
            with self.assertRaisesRegex(ValueError, "entries must be strings"):
                verify_source_artifacts(malformed, root)


    def test_bundle_validator_reports_missing_non_core_evidence(self) -> None:
        digest = hashlib.sha256(b"missing").hexdigest()
        source_hashes = {
            "core": "c" * 64,
            "custom-manifest/" + digest: digest,
        }
        manifest = {
            "schema": BUNDLE_SCHEMA,
            "mapSid": "proc_source_contract",
            "sourceHashes": source_hashes,
            "provenance": {"sourceHashes": source_hashes},
            "files": {},
        }
        with _temporary_root() as root:
            (root / "manifest.json").write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )
            report = validate_bundle(root)
        self.assertIn(
            "source_artifact_contract",
            {issue.code for issue in report.issues},
        )

if __name__ == "__main__":
    unittest.main()