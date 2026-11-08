from __future__ import annotations

import io
import shutil
import unittest
import uuid
from contextlib import redirect_stderr
from pathlib import Path

from experiments.campaign_port_poc.procedural_scenarios.cli import build_parser
from experiments.campaign_port_poc.procedural_scenarios.service import (
    install_generated_bundle,
    uninstall_generated_scenario,
)
from experiments.campaign_port_poc.procedural_scenarios.game_context import (
    CORE_REL,
    DONOR_REL,
    GAME_EXE_REL,
    GAME_ROOT_ENV,
    MOD_DLL_REL,
    GameContextError,
    discover_golden_era_context,
    parse_vdf,
    resolve_catalog_core,
    resolve_generation_inputs,
    steam_library_roots,
    validate_golden_era_root,
)


class GameContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "build" / f".game_context_test-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True)

    def tearDown(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root)

    def _make_game(self, root: Path) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        (root / GAME_EXE_REL).write_bytes(b"exe")
        (root / CORE_REL).parent.mkdir(parents=True, exist_ok=True)
        (root / CORE_REL).write_bytes(b"core")
        (root / DONOR_REL).parent.mkdir(parents=True, exist_ok=True)
        (root / DONOR_REL).write_bytes(b"map")
        (root / MOD_DLL_REL).parent.mkdir(parents=True, exist_ok=True)
        (root / MOD_DLL_REL).write_bytes(b"mod")
        return root

    def _make_steam_library(self, name: str = "Heroes Olden Era") -> tuple[Path, Path]:
        library = self.root / f"library-{uuid.uuid4().hex}"
        manifest = library / "steamapps" / "appmanifest_3105440.acf"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            '"AppState"\n{\n'
            '    "appid" "3105440"\n'
            f'    "installdir" "{name}"\n'
            '}\n',
            encoding="utf-8",
        )
        game = self._make_game(library / "steamapps" / "common" / f"{name} - Golden Era")
        return library, game

    def test_parse_vdf_is_structured_and_fail_closed(self) -> None:
        parsed = parse_vdf(
            '"libraryfolders" { "0" { "path" "V:\\\\Games" } }'
        )
        self.assertEqual("V:\\Games", parsed["libraryfolders"]["0"]["path"])
        with self.assertRaisesRegex(GameContextError, "duplicate"):
            parse_vdf('"x" "1" "x" "2"')
        with self.assertRaisesRegex(GameContextError, "invalid Valve VDF syntax"):
            parse_vdf('"x" nope')

    def test_libraryfolders_metadata_yields_steam_roots(self) -> None:
        steam_home = self.root / "Steam"
        library = self.root / "Other Library"
        metadata = steam_home / "steamapps" / "libraryfolders.vdf"
        metadata.parent.mkdir(parents=True)
        escaped_library = str(library).replace("\\", "\\\\")
        metadata.write_text(
            f'"libraryfolders" {{ "0" {{ "path" "{escaped_library}" }} }}',
            encoding="utf-8",
        )
        roots = steam_library_roots(steam_home)
        self.assertEqual(
            {steam_home.resolve(), library.resolve()},
            set(roots),
        )

    def test_explicit_root_derives_canonical_inputs(self) -> None:
        game = self._make_game(self.root / "Golden Era")
        context = validate_golden_era_root(game)
        self.assertEqual(game.resolve(), context.game_root)
        self.assertEqual(game.resolve() / CORE_REL, context.core_zip)
        self.assertEqual(game.resolve() / DONOR_REL, context.donor_map)
        self.assertEqual((game.resolve() / MOD_DLL_REL).parent, context.mod_root)

    def test_explicit_invalid_root_never_falls_back(self) -> None:
        library, _game = self._make_steam_library()
        invalid = self.root / "invalid"
        invalid.mkdir()
        with self.assertRaisesRegex(GameContextError, "missing"):
            discover_golden_era_context(game_root=invalid, library_roots=(library,))

    def test_steam_discovery_requires_exactly_one_valid_modded_install(self) -> None:
        library, game = self._make_steam_library()
        context = discover_golden_era_context(environ={}, library_roots=(library,))
        self.assertEqual(game.resolve(), context.game_root)
        self.assertEqual("steam", context.source)

        second_name = "Second Olden Era"
        second_manifest = self.root / "second-library" / "steamapps" / "appmanifest_3105440.acf"
        second_manifest.parent.mkdir(parents=True)
        second_manifest.write_text(
            f'"AppState" {{ "appid" "3105440" "installdir" "{second_name}" }}',
            encoding="utf-8",
        )
        self._make_game(
            second_manifest.parent / "common" / f"{second_name} - Golden Era"
        )
        with self.assertRaisesRegex(GameContextError, "multiple Golden Era installations"):
            discover_golden_era_context(
                environ={},
                library_roots=(library, second_manifest.parents[1]),
            )

    def test_discovery_reports_no_usable_install(self) -> None:
        library = self.root / "empty-library"
        library.mkdir()
        with self.assertRaisesRegex(GameContextError, "no Golden Era installation"):
            discover_golden_era_context(environ={}, library_roots=(library,))

    def test_environment_root_is_authoritative(self) -> None:
        library, game = self._make_steam_library()
        context = discover_golden_era_context(
            environ={GAME_ROOT_ENV: str(game)},
            library_roots=(library,),
        )
        self.assertEqual(f"environment:{GAME_ROOT_ENV}", context.source)

        invalid = self.root / "invalid-env"
        invalid.mkdir()
        with self.assertRaisesRegex(GameContextError, "missing"):
            discover_golden_era_context(
                environ={GAME_ROOT_ENV: str(invalid)},
                library_roots=(library,),
            )

    def test_advanced_overrides_are_explicit_and_paired(self) -> None:
        core = self.root / "Core.zip"
        donor = self.root / "schema.map"
        core.write_bytes(b"core")
        donor.write_bytes(b"map")
        inputs = resolve_generation_inputs(core_zip=core, donor_map=donor)
        self.assertEqual("advanced-override", inputs.source)
        self.assertIsNone(inputs.game_root)
        with self.assertRaisesRegex(GameContextError, "requires both"):
            resolve_generation_inputs(core_zip=core)
        with self.assertRaisesRegex(GameContextError, "do not combine"):
            resolve_generation_inputs(
                game_root=self.root,
                core_zip=core,
                donor_map=donor,
            )
        with self.assertRaisesRegex(GameContextError, "do not combine"):
            resolve_catalog_core(game_root=self.root, core_zip=core)

    def test_normal_cli_does_not_require_internal_source_paths(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            ["generate", "--profile", "profile.json", "--output", "library"]
        )
        self.assertIsNone(args.game_root)
        self.assertIsNone(args.core)
        self.assertIsNone(args.donor)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["install", "bundle"])
        install = parser.parse_args(
            ["install", "bundle", "--game-root", "Golden Era"]
        )
        self.assertEqual(Path("Golden Era"), install.game_root)
        with self.assertRaisesRegex(ValueError, "explicit Golden Era root"):
            install_generated_bundle(self.root, game_root=None)
        with self.assertRaisesRegex(ValueError, "explicit Golden Era root"):
            uninstall_generated_scenario("proc_test", game_root=None)


if __name__ == "__main__":
    unittest.main()