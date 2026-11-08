"""Fail-closed discovery of the installed Golden Era runtime inputs."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


STEAM_APP_ID = "3105440"
GAME_ROOT_ENV = "OLDEN_GOLDEN_ERA_ROOT"
MOD_SUFFIX = " - Golden Era"
MAPS_REL = Path("HeroesOldenEra_Data") / "StreamingAssets" / "maps"
CORE_REL = Path("HeroesOldenEra_Data") / "StreamingAssets" / "Core.zip"
DONOR_REL = MAPS_REL / "Thirst_for_Power.map"
GAME_EXE_REL = Path("HeroesOldenEra.exe")
MOD_ROOT_REL = Path("BepInEx") / "plugins" / "OfflineUnlockMod"
MOD_DLL_REL = MOD_ROOT_REL / "OfflineUnlockMod.dll"


class GameContextError(RuntimeError):
    pass


@dataclass(frozen=True)
class GoldenEraContext:
    game_root: Path
    core_zip: Path
    maps_root: Path
    donor_map: Path
    mod_root: Path
    source: str


@dataclass(frozen=True)
class GenerationInputs:
    core_zip: Path
    donor_map: Path
    game_root: Path | None
    source: str


def _decode_vdf_string(raw: str) -> str:
    out: list[str] = []
    index = 0
    while index < len(raw):
        char = raw[index]
        if char == "\\" and index + 1 < len(raw) and raw[index + 1] in {'\\', '"'}:
            index += 1
            char = raw[index]
        out.append(char)
        index += 1
    return "".join(out)


def _vdf_tokens(text: str) -> tuple[str, ...]:
    tokens: list[str] = []
    position = 0
    pattern = re.compile(r'\s*(?:"((?:\\.|[^"\\])*)"|([{}]))', re.DOTALL)
    while position < len(text):
        match = pattern.match(text, position)
        if match is None:
            if text[position:].strip():
                raise GameContextError(
                    f"invalid Valve VDF syntax near character {position}"
                )
            break
        quoted, brace = match.groups()
        tokens.append(brace if brace is not None else _decode_vdf_string(quoted))
        position = match.end()
    return tuple(tokens)


def _parse_vdf_object(
    tokens: tuple[str, ...],
    index: int,
    *,
    require_close: bool,
) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    while index < len(tokens):
        token = tokens[index]
        if token == "}":
            if not require_close:
                raise GameContextError("unexpected closing brace in Valve VDF")
            return result, index + 1
        if token == "{":
            raise GameContextError("Valve VDF object is missing a key")
        key = token
        index += 1
        if index >= len(tokens):
            raise GameContextError(f"Valve VDF key {key!r} has no value")
        value_token = tokens[index]
        if value_token == "{":
            value, index = _parse_vdf_object(tokens, index + 1, require_close=True)
        elif value_token == "}":
            raise GameContextError(f"Valve VDF key {key!r} has no value")
        else:
            value = value_token
            index += 1
        if key in result:
            raise GameContextError(f"duplicate Valve VDF key {key!r}")
        result[key] = value
    if require_close:
        raise GameContextError("unterminated Valve VDF object")
    return result, index


def parse_vdf(text: str) -> dict[str, Any]:
    tokens = _vdf_tokens(text)
    document, index = _parse_vdf_object(tokens, 0, require_close=False)
    if index != len(tokens):
        raise GameContextError("Valve VDF contains trailing tokens")
    return document


def _read_vdf(path: Path) -> dict[str, Any]:
    try:
        payload = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise GameContextError(f"cannot read Steam metadata {path}: {exc}") from exc
    return parse_vdf(payload)


def _casefold_get(document: Mapping[str, Any], key: str) -> Any:
    matches = [
        value
        for name, value in document.items()
        if name.casefold() == key.casefold()
    ]
    if len(matches) != 1:
        raise GameContextError(f"Steam metadata requires exactly one {key!r} field")
    return matches[0]


def _registry_steam_home() -> Path:
    if os.name != "nt":
        raise GameContextError(
            f"automatic Steam discovery is only supported on Windows; set {GAME_ROOT_ENV}"
        )
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            value, _kind = winreg.QueryValueEx(key, "SteamPath")
    except (OSError, ImportError) as exc:
        raise GameContextError(
            f"SteamPath is unavailable; set {GAME_ROOT_ENV} or pass --game-root"
        ) from exc
    if not isinstance(value, str) or not value.strip():
        raise GameContextError("SteamPath registry value is empty")
    return Path(value)


def steam_library_roots(steam_home: Path | None = None) -> tuple[Path, ...]:
    home = Path(steam_home) if steam_home is not None else _registry_steam_home()
    document = _read_vdf(home / "steamapps" / "libraryfolders.vdf")
    folders = _casefold_get(document, "libraryfolders")
    if not isinstance(folders, Mapping):
        raise GameContextError("Steam libraryfolders root must be an object")
    roots = {home.resolve()}
    for key, value in folders.items():
        if not str(key).isdigit() or not isinstance(value, Mapping):
            continue
        raw_path = value.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise GameContextError(f"Steam library {key!r} has no path")
        roots.add(Path(raw_path).resolve())
    return tuple(sorted(roots, key=lambda path: str(path).casefold()))


def validate_golden_era_root(
    game_root: Path | str,
    *,
    source: str = "explicit",
) -> GoldenEraContext:
    root = Path(game_root).expanduser().resolve()
    required = {
        "Golden Era root": (root, "directory"),
        "game executable": (root / GAME_EXE_REL, "file"),
        "active Core": (root / CORE_REL, "file"),
        "maps directory": (root / MAPS_REL, "directory"),
        "native schema map": (root / DONOR_REL, "file"),
        "OfflineUnlockMod.dll": (root / MOD_DLL_REL, "file"),
    }
    missing = [
        label
        for label, (path, kind) in required.items()
        if (kind == "file" and not path.is_file())
        or (kind == "directory" and not path.is_dir())
    ]
    if missing:
        raise GameContextError(
            f"{root} is not a usable Golden Era installation; missing {', '.join(missing)}"
        )
    return GoldenEraContext(
        game_root=root,
        core_zip=root / CORE_REL,
        maps_root=root / MAPS_REL,
        donor_map=root / DONOR_REL,
        mod_root=root / MOD_ROOT_REL,
        source=source,
    )


def _steam_candidates(library_roots: Sequence[Path]) -> tuple[Path, ...]:
    candidates: set[Path] = set()
    for library_root in library_roots:
        library = Path(library_root).resolve()
        manifest_path = library / "steamapps" / f"appmanifest_{STEAM_APP_ID}.acf"
        if not manifest_path.is_file():
            continue
        manifest = _read_vdf(manifest_path)
        app_state = _casefold_get(manifest, "AppState")
        if not isinstance(app_state, Mapping):
            raise GameContextError(f"Steam app manifest is malformed: {manifest_path}")
        app_id = _casefold_get(app_state, "appid")
        install_dir = _casefold_get(app_state, "installdir")
        if app_id != STEAM_APP_ID or not isinstance(install_dir, str) or not install_dir:
            raise GameContextError(f"Steam app manifest has invalid identity: {manifest_path}")
        if (
            Path(install_dir).is_absolute()
            or install_dir in {".", ".."}
            or "/" in install_dir
            or "\\" in install_dir
        ):
            raise GameContextError(
                f"Steam app manifest has unsafe installdir: {manifest_path}"
            )
        stock_root = library / "steamapps" / "common" / install_dir
        candidates.add(stock_root.resolve())
        candidates.add(stock_root.with_name(stock_root.name + MOD_SUFFIX).resolve())
    return tuple(sorted(candidates, key=lambda path: str(path).casefold()))


def discover_golden_era_context(
    *,
    game_root: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
    library_roots: Sequence[Path] | None = None,
    steam_home: Path | None = None,
) -> GoldenEraContext:
    if game_root is not None:
        return validate_golden_era_root(game_root, source="explicit")
    environment = os.environ if environ is None else environ
    configured = environment.get(GAME_ROOT_ENV, "").strip()
    if configured:
        return validate_golden_era_root(configured, source=f"environment:{GAME_ROOT_ENV}")
    roots = (
        tuple(Path(path) for path in library_roots)
        if library_roots is not None
        else steam_library_roots(steam_home)
    )
    candidates = _steam_candidates(roots)
    valid: list[GoldenEraContext] = []
    for candidate in candidates:
        try:
            valid.append(validate_golden_era_root(candidate, source="steam"))
        except GameContextError:
            continue
    if not valid:
        raise GameContextError(
            "no Golden Era installation with OfflineUnlockMod, Core.zip, and the native schema map was found; "
            f"set {GAME_ROOT_ENV} or pass --game-root"
        )
    if len(valid) != 1:
        roots_text = ", ".join(str(item.game_root) for item in valid)
        raise GameContextError(
            f"multiple Golden Era installations were found; choose one explicitly: {roots_text}"
        )
    return valid[0]


def resolve_catalog_core(
    *,
    game_root: Path | str | None = None,
    core_zip: Path | str | None = None,
) -> Path:
    if core_zip is not None:
        if game_root is not None:
            raise GameContextError("do not combine --game-root with a --core override")
        core = Path(core_zip).expanduser().resolve()
        if not core.is_file():
            raise GameContextError(f"advanced Core.zip override is not a file: {core}")
        return core
    return discover_golden_era_context(game_root=game_root).core_zip


def resolve_generation_inputs(
    *,
    game_root: Path | str | None = None,
    core_zip: Path | str | None = None,
    donor_map: Path | str | None = None,
) -> GenerationInputs:
    explicit_sources = core_zip is not None or donor_map is not None
    if explicit_sources:
        if core_zip is None or donor_map is None:
            raise GameContextError(
                "advanced source override requires both Core.zip and donor map"
            )
        if game_root is not None:
            raise GameContextError(
                "do not combine --game-root with --core/--donor overrides"
            )
        core = Path(core_zip).expanduser().resolve()
        donor = Path(donor_map).expanduser().resolve()
        if not core.is_file() or not donor.is_file():
            raise GameContextError(
                "advanced Core.zip and donor overrides must both be files"
            )
        return GenerationInputs(core, donor, None, "advanced-override")
    context = discover_golden_era_context(game_root=game_root)
    return GenerationInputs(
        context.core_zip,
        context.donor_map,
        context.game_root,
        context.source,
    )