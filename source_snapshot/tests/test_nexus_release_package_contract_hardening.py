import hashlib
import json
import unittest
import zipfile
from pathlib import Path

from tests.test_nexus_release_package_contract import make_package
from tools.validate_nexus_release_package_contract import ContractError, validate_data, validate_zip


class NexusReleasePackageContractHardeningTests(unittest.TestCase):
    def test_case_only_root_collision_is_rejected(self):
        files = make_package({"readme.md": b"collision"})
        with self.assertRaisesRegex(ContractError, "case-insensitive duplicate"):
            validate_data(files)

    def test_case_only_zip_collision_is_rejected(self):
        files = make_package()
        archive_path = Path("dist/_nexus_contract_collision_test.zip")
        try:
            with zipfile.ZipFile(archive_path, "w") as archive:
                for name, content in files.items():
                    archive.writestr(name, content)
                archive.writestr("readme.md", b"collision")
            with self.assertRaisesRegex(ContractError, "case-insensitive duplicate ZIP"):
                validate_zip(archive_path)
        finally:
            if archive_path.exists():
                archive_path.unlink()

    def test_unknown_source_commit_is_rejected(self):
        files = make_package()
        manifest = json.loads(files["manifest.json"].decode("utf-8"))
        manifest["sourceCommit"] = "unknown"
        files["manifest.json"] = json.dumps(manifest, sort_keys=True).encode("utf-8")
        files["SHA256SUMS.txt"] = "".join(
            f"{hashlib.sha256(files[name]).hexdigest()}  {name}\n"
            for name in sorted(name for name in files if name != "SHA256SUMS.txt")
        ).encode("utf-8")
        with self.assertRaisesRegex(ContractError, "40-character Git commit"):
            validate_data(files)


if __name__ == "__main__":
    unittest.main()
