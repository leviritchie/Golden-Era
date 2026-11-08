"""Application service layer shared by the CLI and PySide6 GUI."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from .bundle import BundleResult, create_bundle, list_library
from .catalog import ContentCatalogSnapshot
from .emitter import (
    parse_container_bytes,
    quest_localization_core_deltas,
    quest_localization_rows,
)
from .events import CounterAction, CounterTrigger, compile_mechanical_events
from .game_context import (
    discover_golden_era_context,
    resolve_catalog_core,
    resolve_generation_inputs,
)
from .generator import generate_scenario
from .installer import InstallResult, UninstallResult, install_bundle, uninstall_scenario
from .presentation import PresentationResult, apply_flavor_presentation
from .profile import ScenarioProfileV1
from .text import (
    FlavorTextCache,
    FlavorTextResult,
    OpenAICompatibleTextProvider,
    TextMode,
    generate_flavor_text,
)
from .validator import ValidationReport, validate_bundle, validate_generated_ir


@dataclass(frozen=True)
class GenerationResult:
    scenario: Any
    bundle: BundleResult
    ir_validation: ValidationReport
    bundle_validation: ValidationReport
    flavor: FlavorTextResult
    presentation: PresentationResult
    warnings: tuple[str, ...] = ()


def load_profile(path: Path | str) -> ScenarioProfileV1:
    profile_path = Path(path)
    try:
        payload = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load profile {profile_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("profile root must be an object")
    return ScenarioProfileV1.from_dict(payload).normalized()


def build_catalog(
    core_zip: Path | str | None = None,
    *,
    game_root: Path | str | None = None,
    custom_manifests: Sequence[Path | str] = (),
    allowlist: Sequence[str] = (),
) -> ContentCatalogSnapshot:
    resolved_core = resolve_catalog_core(game_root=game_root, core_zip=core_zip)
    return ContentCatalogSnapshot.from_core(
        resolved_core,
        custom_manifests=tuple(Path(path) for path in custom_manifests),
        allowlist=tuple(allowlist),
    )


def _declared_counter_sids(events: Sequence[Any]) -> tuple[str, ...]:
    sids: set[str] = set()
    for event in events:
        for row in tuple(event.triggers) + tuple(event.actions):
            if isinstance(row, (CounterTrigger, CounterAction)):
                sids.add(row.counter_sid)
    return tuple(sorted(sids))


def _text_provider(profile: ScenarioProfileV1) -> OpenAICompatibleTextProvider | None:
    settings = profile.text_provider
    if settings.mode.value == TextMode.NONE.value:
        return None
    if settings.endpoint is None or settings.model is None:
        raise ValueError("non-none text mode requires endpoint and model")
    return OpenAICompatibleTextProvider(
        endpoint=settings.endpoint,
        model=settings.model,
        api_key=os.environ.get(settings.api_key_env),
        timeout_seconds=settings.timeout_seconds,
        prompt_version=settings.prompt_version,
    )


def generate_bundle(
    profile: ScenarioProfileV1,
    *,
    core_zip: Path | str | None = None,
    donor_map: Path | str | None = None,
    game_root: Path | str | None = None,
    output_root: Path | str,
    custom_manifests: Sequence[Path | str] = (),
    allowlist: Sequence[str] = (),
    flavor_cache_root: Path | str | None = None,
    publish_by_sid: bool = False,
    catalog_snapshot: ContentCatalogSnapshot | None = None,
) -> GenerationResult:
    normalized = profile.normalized()
    inputs = resolve_generation_inputs(
        game_root=game_root,
        core_zip=core_zip,
        donor_map=donor_map,
    )
    effective_allowlist = tuple(sorted(set(allowlist) | set(normalized.content_allowlist)))
    if catalog_snapshot is None:
        catalog = build_catalog(
            inputs.core_zip,
            custom_manifests=custom_manifests,
            allowlist=effective_allowlist,
        )
    else:
        if custom_manifests:
            raise ValueError("catalog_snapshot cannot be combined with custom_manifests")
        core_hash = hashlib.sha256(inputs.core_zip.read_bytes()).hexdigest()
        if catalog_snapshot.core_hash != core_hash:
            raise ValueError(
                "catalog_snapshot Core hash does not match the generation Core"
            )
        missing_allowlist = sorted(
            set(effective_allowlist) - set(catalog_snapshot.allowlist)
        )
        if missing_allowlist:
            raise ValueError(
                "catalog_snapshot is missing requested allowlist SIDs: "
                + ", ".join(missing_allowlist)
            )
        catalog = catalog_snapshot
    donor_path = inputs.donor_map
    try:
        donor_payload = donor_path.read_bytes()
        donor_container = parse_container_bytes(donor_payload)
    except (EOFError, OSError, ValueError) as exc:
        raise ValueError(f"cannot snapshot donor map {donor_path}: {exc}") from exc
    donor_hash = hashlib.sha256(donor_payload).hexdigest()
    scenario = generate_scenario(normalized, catalog, donor_hash=donor_hash)
    ir_report = validate_generated_ir(scenario)
    ir_report.raise_for_errors()

    counters = _declared_counter_sids(scenario.events)
    compiled = compile_mechanical_events(
        scenario.events,
        declared_counter_sids=counters,
    )
    cache = (
        None
        if flavor_cache_root is None
        else FlavorTextCache(Path(flavor_cache_root))
    )
    flavor = generate_flavor_text(
        scenario.events,
        locale=normalized.locale,
        mode=normalized.text_provider.mode.value,
        provider=_text_provider(normalized),
        cache=cache,
    )
    presentation = apply_flavor_presentation(
        scenario.map_sid,
        normalized.locale,
        scenario.events,
        compiled,
        flavor,
    )
    core_deltas = list(presentation.core_deltas)
    core_deltas.extend(_seer_hut_core_deltas(scenario))
    quest_rows = quest_localization_rows(
        scenario.events,
        scenario.map_sid,
        title=getattr(scenario.profile, "title", None),
    )
    core_deltas.extend(
        quest_localization_core_deltas(scenario.map_sid, quest_rows)
    )
    requested_root = Path(output_root)
    target_root = requested_root / scenario.map_sid if publish_by_sid else requested_root
    target_root.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    staging_root = target_root.parent / f".{target_root.name}.pending-{token}"
    previous_root = target_root.parent / f".{target_root.name}.previous-{token}"
    publish_warnings: list[str] = []
    if staging_root.exists() or previous_root.exists():
        raise RuntimeError("bundle staging path collision")
    try:
        staged_bundle = create_bundle(
            scenario,
            staging_root,
            donor_container=donor_container,
            core_deltas=core_deltas,
            compiled_triggers=presentation.triggers,
            manifest_fragment=presentation.manifest_fragment,
            source_artifacts={
                artifact.source_key: artifact.payload
                for artifact in catalog.source_artifacts
            },
        )
        bundle_report = validate_bundle(staged_bundle.root)
        bundle_report.raise_for_errors()
        if target_root.exists():
            if target_root.is_symlink() or not target_root.is_dir():
                raise ValueError(f"bundle target is not a regular directory: {target_root}")
            existing_manifest = target_root / "manifest.json"
            try:
                existing = json.loads(existing_manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"existing bundle manifest is unreadable: {exc}") from exc
            if existing.get("mapSid") != scenario.map_sid:
                raise ValueError(
                    f"bundle target belongs to map {existing.get('mapSid')!r}, not {scenario.map_sid!r}"
                )
            os.replace(target_root, previous_root)
        try:
            os.replace(staging_root, target_root)
        except Exception:
            if previous_root.exists() and not target_root.exists():
                os.replace(previous_root, target_root)
            raise
        if previous_root.exists():
            try:
                shutil.rmtree(previous_root)
            except OSError as exc:
                publish_warnings.append(
                    f"published bundle is active, but prior-version cleanup failed at {previous_root}: {exc}"
                )
    finally:
        if staging_root.exists():
            shutil.rmtree(staging_root)
        if previous_root.exists() and not target_root.exists():
            os.replace(previous_root, target_root)
    emission = replace(
        staged_bundle.emission,
        map_path=target_root / "maps" / f"{scenario.map_sid}.map",
        sidecar_path=target_root / "maps" / f"{scenario.map_sid}.json",
    )
    bundle = replace(
        staged_bundle,
        root=target_root,
        manifest_path=target_root / "manifest.json",
        emission=emission,
    )
    bundle_report = replace(bundle_report, subject=str(target_root))
    return GenerationResult(
        scenario,
        bundle,
        ir_report,
        bundle_report,
        flavor,
        presentation,
        tuple(publish_warnings),
    )


def validate_generated_bundle(bundle_root: Path | str) -> ValidationReport:
    return validate_bundle(Path(bundle_root))


def _seer_hut_core_deltas(scenario: Any) -> list[dict[str, Any]]:
    """Ensure ObjectConfig + dialog rows exist for Seer hut QuestScript Dialog actions."""

    import sys
    from pathlib import Path as _Path

    campaign_root = _Path(__file__).resolve().parents[1]
    if str(campaign_root) not in sys.path:
        sys.path.insert(0, str(campaign_root))
    from seer_hut_quest import homm3_seer_hut_event_bank_doc, homm3_seer_hut_object_row

    ops: list[dict[str, Any]] = []
    triggers = tuple(getattr(scenario, "seer_script_triggers", ()) or ())
    dialogs = tuple(getattr(scenario, "seer_dialog_plans", ()) or ())
    if not triggers and not dialogs:
        return ops
    ops.append(
        {
            "operation": "upsert_array",
            "member": "DB/map/objects/4_interactables.json",
            "path": ["array"],
            "key": "id",
            "rows": [homm3_seer_hut_object_row()],
        }
    )
    ops.append(
        {
            "operation": "create_json_member",
            "member": "DB/objects_logic/event_banks/campaign_objects/homm3_seer_hut.json",
            "path": [],
            "value": homm3_seer_hut_event_bank_doc(),
        }
    )
    map_sid = str(getattr(scenario, "map_sid", "") or "")
    locale = str(getattr(getattr(scenario, "profile", None), "locale", "english") or "english")
    for plan in dialogs:
        if not isinstance(plan, dict):
            continue
        triad = (
            ("dialogFirstSid", "firstVisitText", "Seer's Hut"),
            ("dialogNextSid", "nextVisitText", "Seer's Hut"),
            ("dialogCompletedSid", "completedText", "Seer's Hut"),
        )
        for sid_key, text_key, title in triad:
            dialog_sid = str(plan.get(sid_key) or "").strip()
            body = str(plan.get(text_key) or title).strip() or title
            if not dialog_sid:
                continue
            title_sid = f"dialogue_title_{dialog_sid}"
            body_sid = f"dialogue_text_{dialog_sid}_0"
            member = f"DB/dialogs/dialogs/custom_maps/{map_sid}/{dialog_sid}.json"
            ops.append(
                {
                    "op": "create_json_member",
                    "member": member,
                    "value": {
                        "array": [
                            {
                                "id": dialog_sid,
                                "localization": True,
                                "slides": [
                                    {
                                        "id": "start",
                                        "fon": "",
                                        "avatars": [],
                                        "title": {"sid": title_sid, "position": 3},
                                        "text": body_sid,
                                        "next": "ending",
                                    },
                                    {
                                        "id": "ending",
                                        "fon": "",
                                        "text": "",
                                        "invokeOnlyActions": True,
                                        "end": True,
                                    },
                                ],
                            }
                        ]
                    },
                }
            )
            ops.append(
                {
                    "op": "upsert_array",
                    "member": f"Lang/{locale}/texts/dialogues.json",
                    "matchKey": "sid",
                    "rows": [
                        {"sid": title_sid, "text": title},
                        {"sid": body_sid, "text": body},
                    ],
                }
            )
    return ops


def install_generated_bundle(
    bundle_root: Path | str,
    *,
    game_root: Path | str,
) -> InstallResult:
    if game_root is None:
        raise ValueError("installation requires an explicit Golden Era root")
    context = discover_golden_era_context(game_root=game_root)
    return install_bundle(Path(bundle_root), game_root=context.game_root)


def uninstall_generated_scenario(
    map_sid: str,
    *,
    game_root: Path | str,
) -> UninstallResult:
    if game_root is None:
        raise ValueError("uninstall requires an explicit Golden Era root")
    context = discover_golden_era_context(game_root=game_root)
    return uninstall_scenario(map_sid, game_root=context.game_root)


def generated_library(library_root: Path | str) -> list[dict[str, Any]]:
    return list_library(Path(library_root))