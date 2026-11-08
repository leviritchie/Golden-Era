import hashlib
import io
import json
import unittest
import zipfile

from tools.validate_nexus_release_package_contract import ContractError, validate_data


CORE_ZIP_PATH = "HeroesOldenEra_Data/StreamingAssets/Core.zip"
PLUGIN_PREFIX = "BepInEx/plugins/OfflineUnlockMod"
BEPINEX_RUNTIME_FILES = [
    ".doorstop_version",
    "changelog.txt",
    "doorstop_config.ini",
    "winhttp.dll",
    "dotnet/coreclr.dll",
    "BepInEx/core/BepInEx.Core.dll",
    "BepInEx/core/BepInEx.Preloader.Core.dll",
    "BepInEx/core/BepInEx.Unity.IL2CPP.dll",
]


def make_core_zip():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "DB/data.json",
            json.dumps(
                {"fractions": ["homm3_stronghold"], "availableFractions": ["homm3_stronghold"]},
                sort_keys=True,
            ),
        )
        archive.writestr("DB/fractions/7_homm3_stronghold.json", b"{}")
    return output.getvalue()


def make_package(extra=None):
    core_zip = make_core_zip()
    files = {
        "README.md": b"Install the package into the pinned depot game root.\n",
        "manifest.json": json.dumps(
            {
                "schema": "homm3-nexus-depot-package/v2",
                "packageVersion": "test",
                "sourceCommit": "0" * 40,
                "releaseInputSha256": "0" * 64,
                "bepInExVersion": "6.0.0-be.755+3fab71a",
                "bepInExSourceUrl": "https://builds.bepinex.dev/projects/bepinex_be/755/BepInEx-Unity.IL2CPP-win-x64-6.0.0-be.755%2B3fab71a.zip",
                "bepInExPackageSha256": "3616d6a67f5f595973ec4aa7bd7edaf7f799d5bb9926f7146a6dcc7b4abf478f",
                "bepInExPackageBytes": 34323430,
                "bepInExPackageEntryCount": 233,
                "bepInExRuntimeFileCount": len(BEPINEX_RUNTIME_FILES),
                "bepInExRuntimeFiles": BEPINEX_RUNTIME_FILES,
                "thirdPartyNoticePath": "THIRD_PARTY_NOTICES.txt",
                "coreZipPath": CORE_ZIP_PATH,
                "coreZipSha256": hashlib.sha256(core_zip).hexdigest(),
                "coreZipBytes": len(core_zip),
                "coreProvenanceFormat": "hommoe-golden-era-release-overlay-v1",
                "coreProvenanceOperationCount": 1,
                "coreProvenanceSkippedDeletedMemberCount": 0,
                "coreProvenanceSkippedDeletedMembers": [],
                "coreProvenanceRequiredCoreTokens": ["homm3_stronghold"],
                "pinnedVanillaCoreZipSha256": "1" * 64,
                "pinnedVanillaCoreZipBytes": 123,
                "packageBoundary": (
                    "BepInEx 6.0.0-be.755+3fab71a runtime + "
                    "HeroesOldenEra_Data/StreamingAssets/Core.zip + "
                    "BepInEx/plugins/OfflineUnlockMod"
                ),
                "copiedPluginFiles": [
                    f"{PLUGIN_PREFIX}/OfflineLauncherConfig.json",
                    f"{PLUGIN_PREFIX}/OfflineUnlockMod.dll",
                    f"{PLUGIN_PREFIX}/OldenAiSim.dll",
                ],
                "scrubbedPluginDlls": [
                    f"{PLUGIN_PREFIX}/OfflineUnlockMod.dll",
                    f"{PLUGIN_PREFIX}/OldenAiSim.dll",
                ],
                "excludedReleaseInputFiles": [],
            },
            sort_keys=True,
        ).encode("utf-8"),
        CORE_ZIP_PATH: core_zip,
        f"{PLUGIN_PREFIX}/OfflineUnlockMod.dll": b"dll",
        f"{PLUGIN_PREFIX}/OldenAiSim.dll": b"sim",
        f"{PLUGIN_PREFIX}/OfflineLauncherConfig.json": json.dumps(
            {"releaseSafeProfile": True, "autoLaunchOnMenu": False}, sort_keys=True
        ).encode("utf-8"),
    }
    files.update({name: b"runtime" for name in BEPINEX_RUNTIME_FILES})
    files["THIRD_PARTY_NOTICES.txt"] = (
        b"BepInEx 6.0.0-be.755+3fab71a\n"
        b"BepInEx/core/\n"
        b"Microsoft .NET runtime files under dotnet/\n"
        b"https://builds.bepinex.dev/projects/bepinex_be/755/BepInEx-Unity.IL2CPP-win-x64-6.0.0-be.755%2B3fab71a.zip\n"
        b"3616d6a67f5f595973ec4aa7bd7edaf7f799d5bb9926f7146a6dcc7b4abf478f\n"
        b"https://github.com/BepInEx/BepInEx\n"
        b"https://github.com/dotnet/runtime\n"
        b"THIRD-PARTY-NOTICES\n"
    )
    extra = extra or {}
    files.update(extra)
    manifest = json.loads(files["manifest.json"].decode("utf-8"))
    for name in extra:
        if name.startswith(PLUGIN_PREFIX + "/") and name not in manifest["copiedPluginFiles"]:
            manifest["copiedPluginFiles"].append(name)
    files["manifest.json"] = json.dumps(manifest, sort_keys=True).encode("utf-8")
    files["SHA256SUMS.txt"] = "".join(
        f"{hashlib.sha256(files[name]).hexdigest()}  {name}\n" for name in sorted(files)
    ).encode("utf-8")
    return files


class NexusReleasePackageContractTests(unittest.TestCase):
    def test_minimal_package_passes(self):
        self.assertEqual(validate_data(make_package()), 16)

    def test_pinned_bepinex_identity_is_enforced(self):
        files = make_package()
        manifest = json.loads(files["manifest.json"].decode("utf-8"))
        manifest["bepInExPackageSha256"] = "2" * 64
        files["manifest.json"] = json.dumps(manifest, sort_keys=True).encode("utf-8")
        files["SHA256SUMS.txt"] = "".join(
            f"{hashlib.sha256(files[name]).hexdigest()}  {name}\n"
            for name in sorted(name for name in files if name != "SHA256SUMS.txt")
        ).encode("utf-8")
        with self.assertRaisesRegex(ContractError, "pinned official package"):
            validate_data(files)

    def test_third_party_notice_is_required(self):
        files = make_package()
        del files["THIRD_PARTY_NOTICES.txt"]
        with self.assertRaisesRegex(ContractError, "missing required file"):
            validate_data(files)

    def test_third_party_notice_attribution_is_enforced(self):
        files = make_package()
        files["THIRD_PARTY_NOTICES.txt"] = b"BepInEx only\n"
        files["SHA256SUMS.txt"] = "".join(
            f"{hashlib.sha256(files[name]).hexdigest()}  {name}\n"
            for name in sorted(name for name in files if name != "SHA256SUMS.txt")
        ).encode("utf-8")
        with self.assertRaisesRegex(ContractError, "required attribution marker"):
            validate_data(files)

    def test_manifest_runtime_provenance_must_cover_all_shipped_files(self):
        files = make_package()
        manifest = json.loads(files["manifest.json"].decode("utf-8"))
        manifest["bepInExRuntimeFiles"].remove("dotnet/coreclr.dll")
        manifest["bepInExRuntimeFileCount"] -= 1
        files["manifest.json"] = json.dumps(manifest, sort_keys=True).encode("utf-8")
        files["SHA256SUMS.txt"] = "".join(
            f"{hashlib.sha256(files[name]).hexdigest()}  {name}\n"
            for name in sorted(name for name in files if name != "SHA256SUMS.txt")
        ).encode("utf-8")
        with self.assertRaisesRegex(ContractError, "does not cover the shipped BepInEx runtime exactly"):
            validate_data(files)

    def test_manifest_package_boundary_must_match_depot_paths(self):
        files = make_package()
        manifest = json.loads(files["manifest.json"].decode("utf-8"))
        manifest["packageBoundary"] = "HeroesOldEra_Data/StreamingAssets/Core.zip + BepInEx/plugins/OfflineUnlockMod"
        files["manifest.json"] = json.dumps(manifest, sort_keys=True).encode("utf-8")
        files["SHA256SUMS.txt"] = "".join(
            f"{hashlib.sha256(files[name]).hexdigest()}  {name}\n"
            for name in sorted(name for name in files if name != "SHA256SUMS.txt")
        ).encode("utf-8")
        with self.assertRaisesRegex(ContractError, "packageBoundary must be"):
            validate_data(files)

    def test_bootstrap_and_nested_archive_are_rejected(self):
        with self.assertRaisesRegex(ContractError, "game-root/bootstrap"):
            validate_data(make_package({f"{PLUGIN_PREFIX}/winhttp.dll": b"bootstrap"}))
        with self.assertRaisesRegex(ContractError, "nested archive"):
            validate_data(make_package({f"{PLUGIN_PREFIX}/payload.zip": b"nested"}))
        with self.assertRaisesRegex(ContractError, "nested archive"):
            validate_data(make_package({"dotnet/payload.zip": b"nested"}))
        with self.assertRaisesRegex(ContractError, "executable or script"):
            validate_data(make_package({"dotnet/payload.ps1": b"script"}))

    def test_stale_suffix_artifacts_are_rejected(self):
        with self.assertRaisesRegex(ContractError, "stale suffix"):
            validate_data(make_package({f"{PLUGIN_PREFIX}/asset.bin.force_win_game_pending": b"stale"}))
        with self.assertRaisesRegex(ContractError, "stale suffix"):
            validate_data(make_package({f"{PLUGIN_PREFIX}/map.broken_fp_spawn_stack_20260709": b"stale"}))

    def test_legitimate_pdb_named_dependency_is_allowed(self):
        self.assertEqual(
            validate_data(make_package({f"{PLUGIN_PREFIX}/Mono.Cecil.Pdb.dll": b"dependency"})),
            17,
        )

    def test_core_zip_must_identify_stronghold(self):
        invalid_core = io.BytesIO()
        with zipfile.ZipFile(invalid_core, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("DB/data.json", b'{"fractions": ["castle"]}')
            archive.writestr("DB/fractions/7_homm3_stronghold.json", b"{}")
        with self.assertRaisesRegex(ContractError, "does not identify the Stronghold"):
            validate_data(make_package({CORE_ZIP_PATH: invalid_core.getvalue()}))

    def test_manifest_plugin_provenance_must_cover_all_shipped_files(self):
        files = make_package()
        manifest = json.loads(files["manifest.json"].decode("utf-8"))
        manifest["copiedPluginFiles"].remove(f"{PLUGIN_PREFIX}/OldenAiSim.dll")
        files["manifest.json"] = json.dumps(manifest, sort_keys=True).encode("utf-8")
        files["SHA256SUMS.txt"] = "".join(
            f"{hashlib.sha256(files[name]).hexdigest()}  {name}\n"
            for name in sorted(name for name in files if name != "SHA256SUMS.txt")
        ).encode("utf-8")
        with self.assertRaisesRegex(ContractError, "does not cover the shipped plugin files exactly"):
            validate_data(files)

    def test_manifest_scrub_provenance_must_name_expected_dlls(self):
        files = make_package()
        manifest = json.loads(files["manifest.json"].decode("utf-8"))
        manifest["scrubbedPluginDlls"] = [f"{PLUGIN_PREFIX}/OfflineUnlockMod.dll"]
        files["manifest.json"] = json.dumps(manifest, sort_keys=True).encode("utf-8")
        files["SHA256SUMS.txt"] = "".join(
            f"{hashlib.sha256(files[name]).hexdigest()}  {name}\n"
            for name in sorted(name for name in files if name != "SHA256SUMS.txt")
        ).encode("utf-8")
        with self.assertRaisesRegex(ContractError, "does not identify the expected scrubbed DLLs"):
            validate_data(files)


if __name__ == "__main__":
    unittest.main()
