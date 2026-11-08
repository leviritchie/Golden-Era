from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import zipfile
import sys
import uuid
from contextlib import redirect_stderr
from dataclasses import replace
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from procedural_scenarios import service as scenario_service
from procedural_scenarios.bundle import (
    normalize_core_deltas,
    verify_source_artifacts,
    write_source_artifacts,
)
from procedural_scenarios.catalog import ContentCatalogSnapshot, ContentKind
from procedural_scenarios.cli import build_parser as build_cli_parser
from procedural_scenarios.emitter import (
    NATIVE_OBJECT_PROPERTY_KEYS,
    NativeMapContainer,
    parse_container_bytes,
    serialize_container,
)
from procedural_scenarios.events import (
    CounterAction,
    CounterTrigger,
    MechanicalEventSpec,
    TurnTrigger,
    VictoryAction,
    compile_mechanical_events,
)
from procedural_scenarios.game_context import (
    CORE_REL,
    DONOR_REL,
    GAME_EXE_REL,
    MOD_DLL_REL,
    validate_golden_era_root,
)
from procedural_scenarios.generator import generate_scenario
from procedural_scenarios.installer import apply_core_delta_document
from procedural_scenarios.model import Archetype, Difficulty
from procedural_scenarios.preflight import run_preflight
from procedural_scenarios.profile import (
    DensitySettings,
    EconomySettings,
    EventPolicy,
    ScenarioProfileV1,
    TopologySettings,
)
from procedural_scenarios.validator import validate_bundle, validate_generated_ir


DEFAULT_PROFILE = REPO_ROOT / "scenarios" / "procedural" / "default.profile.json"
REQUIRED_FILES = (
    REPO_ROOT / "procedural_scenarios" / "__init__.py",
    REPO_ROOT
    / "experiments"
    / "campaign_port_poc"
    / "procedural_scenarios"
    / "game_context.py",
    REPO_ROOT / "experiments" / "campaign_port_poc" / "procedural_scenarios" / "gui.py",
    REPO_ROOT / "experiments" / "campaign_port_poc" / "procedural_scenarios" / "native_properties.py",
    REPO_ROOT / "tools" / "audit_procedural_native_parity.py",
    REPO_ROOT / "tools" / "procedural_scenario_gui" / "OldenProceduralScenarios.spec",
    REPO_ROOT / "tools" / "procedural_scenario_gui" / "requirements.txt",
)

DIVERSITY_FINGERPRINTS = (
    "topology",
    "layout",
    "biome",
    "route",
    "encounter",
    "objective",
)
PROFILE_EXTREME_NAMES = (
    "density_sparse_spacing_10",
    "density_dense_spacing_6",
    "ai_none",
    "ai_max_7",
    "topology_no_loops_no_risk",
    "topology_max_loops_and_risk",
    "biome_single_roads_off",
    "biome_all_surface",
    "economy_min_easy",
    "economy_high_expert",
    "events_minimal_objective_only",
)
DENSE_OPTIONAL_GAMEPLAY_PER_ZONE = 5.0
PACKAGED_PREFLIGHT_IMPORTS = (
    "port_homecoming_poc",
    "campaign_runtime_script",
    "object_property_namespaces",
    "scenario_menu_shell",
    "surface_emit",
    "dialog_portrait_plan",
    "h3m_hero_sid",
    "campaign_starting_bonus",
)


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _load_default_profile() -> ScenarioProfileV1:
    raw = json.loads(DEFAULT_PROFILE.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("default procedural profile must be an object")
    return ScenarioProfileV1.from_dict(raw).normalized()


def run_cheap_contract() -> dict[str, Any]:
    missing = [str(path.relative_to(REPO_ROOT)) for path in REQUIRED_FILES if not path.is_file()]
    if missing:
        raise ValueError(f"procedural package files are missing: {missing}")
    profile = _load_default_profile()
    if len(NATIVE_OBJECT_PROPERTY_KEYS) != len(set(NATIVE_OBJECT_PROPERTY_KEYS)):
        raise ValueError("native serialized object property schema contains duplicate keys")
    if "propRandomSquads" not in NATIVE_OBJECT_PROPERTY_KEYS or "propQuestMarkers" not in NATIVE_OBJECT_PROPERTY_KEYS:
        raise ValueError("native serialized object property schema is incomplete")
    if profile.density.scenery_per_100_tiles < 30.0:
        raise ValueError(
            "default procedural scenery density must remain within the native-map range"
        )
    if profile.density.optional_gameplay_per_zone < 2.0:
        raise ValueError(
            "default procedural gameplay density must not regress to sparse zones"
        )
    cli_parser = build_cli_parser()
    normal_generate = cli_parser.parse_args(
        ["generate", "--profile", str(DEFAULT_PROFILE), "--output", "bundle"]
    )
    if any(
        getattr(normal_generate, name) is not None
        for name in ("game_root", "core", "donor")
    ):
        raise ValueError("normal CLI generation must derive internal source paths")
    try:
        with redirect_stderr(io.StringIO()):
            cli_parser.parse_args(["install", "bundle"])
    except SystemExit:
        pass
    else:
        raise ValueError("CLI deployment must require an explicit Golden Era root")
    if profile.map_size != 64 or profile.text_provider.mode.value != "none":
        raise ValueError("default profile must be 64x64 and textless")
    if profile.density.decision_spacing_min < 6 or profile.density.decision_spacing_max > 10:
        raise ValueError("default decision spacing must stay in the 6-10 contract")
    expected_fingerprints = (
        "topology",
        "layout",
        "biome",
        "route",
        "encounter",
        "objective",
    )
    if DIVERSITY_FINGERPRINTS != expected_fingerprints:
        raise ValueError("expensive audit diversity fingerprint contract drifted")
    expected_extremes = (
        "density_sparse_spacing_10",
        "density_dense_spacing_6",
        "ai_none",
        "ai_max_7",
        "topology_no_loops_no_risk",
        "topology_max_loops_and_risk",
        "biome_single_roads_off",
        "biome_all_surface",
        "economy_min_easy",
        "economy_high_expert",
        "events_minimal_objective_only",
    )
    if PROFILE_EXTREME_NAMES != expected_extremes:
        raise ValueError("expensive audit profile-extreme matrix drifted")
    if DENSE_OPTIONAL_GAMEPLAY_PER_ZONE > 5:
        raise ValueError("dense audit extreme exceeds supported optional gameplay density")
    spec_text = (REPO_ROOT / "tools" / "procedural_scenario_gui" / "OldenProceduralScenarios.spec").read_text(
        encoding="utf-8"
    )
    missing_packaged_imports = [
        name for name in PACKAGED_PREFLIGHT_IMPORTS if f'"{name}"' not in spec_text
    ]
    if missing_packaged_imports:
        raise ValueError(
            f"GUI package is missing preflight hidden imports: {missing_packaged_imports}"
        )
    install_probe_root = (
        REPO_ROOT
        / "build"
        / f".procedural_install_context_probe-{uuid.uuid4().hex}"
    )
    if install_probe_root.exists():
        raise ValueError(f"install-context probe path already exists: {install_probe_root}")
    try:
        (install_probe_root / GAME_EXE_REL).parent.mkdir(parents=True)
        (install_probe_root / GAME_EXE_REL).write_bytes(b"exe")
        (install_probe_root / CORE_REL).parent.mkdir(parents=True, exist_ok=True)
        (install_probe_root / CORE_REL).write_bytes(b"core")
        (install_probe_root / DONOR_REL).parent.mkdir(parents=True, exist_ok=True)
        (install_probe_root / DONOR_REL).write_bytes(b"map")
        (install_probe_root / MOD_DLL_REL).parent.mkdir(parents=True, exist_ok=True)
        (install_probe_root / MOD_DLL_REL).write_bytes(b"mod")
        context = validate_golden_era_root(install_probe_root, source="contract-probe")
        if (
            context.core_zip != install_probe_root.resolve() / CORE_REL
            or context.donor_map != install_probe_root.resolve() / DONOR_REL
            or context.source != "contract-probe"
        ):
            raise ValueError("Golden Era context did not derive canonical generation inputs")
    finally:
        if install_probe_root.exists():
            shutil.rmtree(install_probe_root)
    events = (
        MechanicalEventSpec(
            "proc_contract_counter",
            triggers=(TurnTrigger(1),),
            actions=(CounterAction("proc_contract_counter_sid", 1),),
        ),
        MechanicalEventSpec(
            "proc_contract_victory",
            triggers=(CounterTrigger("proc_contract_counter_sid", 1),),
            actions=(VictoryAction("proc_contract_victory"),),
        ),
    )
    compiled = compile_mechanical_events(
        events,
        declared_counter_sids=("proc_contract_counter_sid",),
    )
    victory_count = sum(
        action.get("a") == "GameVictory"
        for trigger in compiled
        for action in trigger["actions"]
    )
    if victory_count != 1:
        raise ValueError("event compiler no longer emits exactly one explicit victory")
    delta = normalize_core_deltas(
        ({
            "member": "DB/dialogs/dialogs/custom_maps/proc_contract/dialog.json",
            "operation": "create_json_member",
            "path": [],
            "value": {"array": []},
        },),
        map_sid="proc_contract",
    )
    if [row["operation"] for row in delta["operations"]] != [
        "append_unique", "create_json_member"
    ]:
        raise ValueError("Core delta normalization lost required operations")
    source_payload = b"procedural-source-contract"
    source_digest = hashlib.sha256(source_payload).hexdigest()
    source_key = f"custom-manifest/{source_digest}"
    source_probe_root = (
        REPO_ROOT
        / "build"
        / f".procedural_source_contract_probe-{uuid.uuid4().hex}"
    )
    if source_probe_root.exists():
        raise ValueError(f"source-evidence probe path already exists: {source_probe_root}")
    try:
        bindings, source_files = write_source_artifacts(
            source_probe_root,
            {"core": "0" * 64, source_key: source_digest},
            {source_key: source_payload},
        )
        source_manifest = {
            "sourceHashes": {"core": "0" * 64, source_key: source_digest},
            "sourceArtifacts": bindings,
            "files": source_files,
        }
        if verify_source_artifacts(source_manifest, source_probe_root) != (source_key,):
            raise ValueError("self-contained source evidence did not verify exactly")
        (source_probe_root / bindings[source_key]).write_bytes(b"tampered")
        try:
            verify_source_artifacts(source_manifest, source_probe_root)
        except ValueError:
            pass
        else:
            raise ValueError("tampered source evidence did not fail closed")
    finally:
        if source_probe_root.exists():
            shutil.rmtree(source_probe_root)
    donor = NativeMapContainer("1.0", b"\0\0", ({}, {}, {}, {}))
    payload_a = serialize_container(donor, hashlib.md5(b"contract").hexdigest())
    payload_b = serialize_container(donor, hashlib.md5(b"contract").hexdigest())
    if payload_a != payload_b or payload_a[4:8] != b"\0\0\0\0":
        raise ValueError("Olden container serialization is not deterministic")
    return {
        "ok": True,
        "mode": "cheap",
        "profileHash": profile.fingerprint,
        "checks": [
            "package_files",
            "default_profile",
            "native_density_floor",
            "source_free_normal_cli",
            "explicit_deployment_root",
            "packaged_preflight_imports",
            "decision_spacing",
            "acceptance_audit_matrix",
            "automatic_install_context",
            "single_victory",
            "composable_core_deltas",
            "self_contained_source_evidence",
            "deterministic_container",
        ],
    }


def _fingerprints(scenario: Any) -> dict[str, str]:
    value = scenario.to_dict()
    encounter_rows = [
        row for row in value["placements"] if row["kind"] == "encounter"
    ]
    objective_rows = [
        row for row in value["placements"] if row["kind"] in {"objective", "ai_settlement"}
    ]
    return {
        "topology": _canonical_hash(value["topology"]),
        "layout": _canonical_hash(value["layout"]),
        "biome": _canonical_hash(value["terrain"]["biomeMap"]),
        "route": _canonical_hash(value["layout"]["routes"]),
        "encounter": _canonical_hash(encounter_rows),
        "objective": _canonical_hash(objective_rows),
    }


def _generate_representative(
    profile: ScenarioProfileV1,
    *,
    core: Path,
    donor: Path,
    bundle_root: Path,
    catalog: ContentCatalogSnapshot,
) -> Any:
    """Generate a representative through the same service path as the CLI/GUI."""

    result = scenario_service.generate_bundle(
        profile,
        core_zip=core,
        donor_map=donor,
        output_root=bundle_root,
        catalog_snapshot=catalog,
    )
    presentation = result.presentation.manifest_fragment.get("presentation")
    if not isinstance(presentation, dict):
        raise ValueError("service representative lacks presentation manifest evidence")
    if presentation.get("status") != "textless" or presentation.get("dialogCount") != 0:
        raise ValueError("default service representative must remain explicitly textless")
    return result


def _stage_effective_core_and_preflight(
    *,
    source_core: Path,
    bundle_root: Path,
    map_sid: str,
    stage_root: Path,
    expected_core_hash: str,
) -> dict[str, Any]:
    """Apply the bundle delta to a staged Core and run the real map-load preflight."""

    source_core_hash = hashlib.sha256(source_core.read_bytes()).hexdigest()
    if source_core_hash != expected_core_hash:
        raise ValueError("source Core changed while the expensive audit was running")
    delta_path = bundle_root / "core_deltas.json"
    delta_document = json.loads(delta_path.read_text(encoding="utf-8-sig"))
    if not isinstance(delta_document, dict):
        raise ValueError("representative Core delta document must be an object")
    candidate_map = bundle_root / "maps" / f"{map_sid}.map"
    if not candidate_map.is_file():
        raise ValueError(f"representative map payload is missing: {candidate_map}")
    stage_root.mkdir(parents=True, exist_ok=True)
    candidate_core = stage_root / "Core.zip"
    merged_members = apply_core_delta_document(
        source_core,
        delta_document,
        candidate_core,
    )
    checks = tuple(run_preflight(candidate_core, candidate_map, map_sid))
    return {
        "effectiveCore": str(candidate_core),
        "effectiveCoreHash": hashlib.sha256(candidate_core.read_bytes()).hexdigest(),
        "mergedCoreMembers": list(merged_members),
        "preflightChecks": list(checks),
    }


def _extreme_faction_sids(catalog: ContentCatalogSnapshot) -> tuple[str, ...]:
    viable: list[str] = []
    for entry in catalog.eligible(ContentKind.FACTION):
        faction_sid = entry.sid
        settlements = catalog.entries_for_faction(
            ContentKind.SETTLEMENT,
            faction_sid,
        )
        heroes = catalog.entries_for_faction(ContentKind.HERO, faction_sid)
        units = catalog.entries_for_faction(ContentKind.UNIT, faction_sid)
        valued_units = tuple(
            unit
            for unit in units
            if isinstance(unit.metadata_value("squadValue"), (int, float))
            and float(unit.metadata_value("squadValue")) > 0
        )
        if settlements and heroes and valued_units:
            viable.append(faction_sid)
    result = tuple(sorted(set(viable)))
    if len(result) < 8:
        raise ValueError(
            "max-AI acceptance profile requires eight factions with eligible "
            f"city, hero, and valued-unit content; found {len(result)}"
        )
    return result


def _extreme_biome_sids(catalog: ContentCatalogSnapshot) -> tuple[str, ...]:
    counts: dict[str, int] = {}
    for entry in catalog.eligible(ContentKind.TERRAIN):
        for biome in entry.biomes:
            counts[biome] = counts.get(biome, 0) + 1
    result = tuple(
        sorted(
            biome
            for biome, count in counts.items()
            if count == 1 and biome != "water"
        )
    )
    if not result:
        raise ValueError("acceptance audit found no unambiguous surface biomes")
    return result


def _profile_extremes(
    profile: ScenarioProfileV1,
    *,
    faction_sids: tuple[str, ...],
    biome_sids: tuple[str, ...],
) -> tuple[tuple[str, ScenarioProfileV1], ...]:
    if len(faction_sids) < 8:
        raise ValueError("profile-extreme matrix requires at least eight faction SIDs")
    if not biome_sids:
        raise ValueError("profile-extreme matrix requires at least one biome SID")
    road_biome = "dirt" if "dirt" in biome_sids else biome_sids[0]
    profiles = (
        (
            "density_sparse_spacing_10",
            replace(
                profile,
                seed=20_001,
                density=DensitySettings(
                    decision_spacing_min=10,
                    decision_spacing_max=10,
                    scenery_per_100_tiles=0.0,
                    optional_gameplay_per_zone=0,
                ),
            ),
        ),
        (
            "density_dense_spacing_6",
            replace(
                profile,
                seed=20_002,
                density=DensitySettings(
                    decision_spacing_min=6,
                    decision_spacing_max=6,
                    scenery_per_100_tiles=20.0,
                    optional_gameplay_per_zone=DENSE_OPTIONAL_GAMEPLAY_PER_ZONE,
                ),
            ),
        ),
        (
            "ai_none",
            replace(
                profile,
                seed=20_003,
                archetype=Archetype.EXPLORATION,
                ai_factions=(),
                ai_count=0,
            ),
        ),
        (
            "ai_max_7",
            replace(
                profile,
                seed=20_004,
                archetype=Archetype.CONQUEST,
                player_faction=faction_sids[0],
                ai_factions=tuple(faction_sids[1:8]),
                ai_count=7,
            ),
        ),
        (
            "topology_no_loops_no_risk",
            replace(
                profile,
                seed=20_005,
                topology=TopologySettings(
                    zone_count=5,
                    optional_loops_enabled=False,
                    high_risk_side_areas_enabled=False,
                    high_risk_side_area_count=0,
                ),
            ),
        ),
        (
            "topology_max_loops_and_risk",
            replace(
                profile,
                seed=20_006,
                topology=TopologySettings(
                    zone_count=30,
                    optional_loops_enabled=True,
                    high_risk_side_areas_enabled=True,
                    high_risk_side_area_count=5,
                ),
            ),
        ),
        (
            "biome_single_roads_off",
            replace(
                profile,
                seed=20_007,
                biomes=(biome_sids[0],),
                terrain=replace(
                    profile.terrain,
                    roads_enabled=False,
                    road_biome=road_biome,
                ),
            ),
        ),
        (
            "biome_all_surface",
            replace(
                profile,
                seed=20_008,
                biomes=biome_sids,
                terrain=replace(profile.terrain, road_biome=road_biome),
            ),
        ),
        (
            "economy_min_easy",
            replace(
                profile,
                seed=20_009,
                difficulty=Difficulty.EASY,
                economy=EconomySettings(
                    starting_gold=0,
                    starting_wood=0,
                    starting_ore=0,
                    reward_multiplier=0.1,
                    recurring_income_enabled=False,
                    recurring_income_interval=1,
                    recurring_income_gold=0,
                ),
            ),
        ),
        (
            "economy_high_expert",
            replace(
                profile,
                seed=20_010,
                difficulty=Difficulty.EXPERT,
                economy=EconomySettings(
                    starting_gold=1_000_000,
                    starting_wood=1_000,
                    starting_ore=1_000,
                    reward_multiplier=10.0,
                    recurring_income_enabled=False,
                    recurring_income_interval=1,
                    recurring_income_gold=100_000,
                ),
            ),
        ),
        (
            "events_minimal_objective_only",
            replace(
                profile,
                seed=20_011,
                archetype=Archetype.EXPLORATION,
                event_policy=EventPolicy(
                    turn_schedules_enabled=False,
                    visit_events_enabled=True,
                    squad_defeat_events_enabled=False,
                    capture_events_enabled=False,
                    resource_rewards_enabled=False,
                    objective_progress_enabled=True,
                ),
            ),
        ),
    )
    names = tuple(name for name, _candidate in profiles)
    if names != PROFILE_EXTREME_NAMES:
        raise ValueError("profile-extreme construction drifted from its contract")
    return profiles

def _snapshot_audit_inputs(
    core: Path,
    donor: Path,
    output: Path,
) -> tuple[Path, Path, str, str]:
    source_core = Path(core).resolve()
    source_donor = Path(donor).resolve()
    core_bytes = source_core.read_bytes()
    with zipfile.ZipFile(io.BytesIO(core_bytes), "r") as archive:
        corrupt_member = archive.testzip()
        if corrupt_member is not None:
            raise ValueError(f"selected Core.zip has a corrupt member: {corrupt_member}")
    donor_bytes = source_donor.read_bytes()
    parse_container_bytes(donor_bytes)
    snapshot_root = output / "input_snapshot"
    snapshot_root.mkdir(parents=True, exist_ok=True)
    core_snapshot = snapshot_root / "Core.zip"
    donor_snapshot = snapshot_root / "donor.map"
    core_snapshot.write_bytes(core_bytes)
    donor_snapshot.write_bytes(donor_bytes)
    return (
        core_snapshot,
        donor_snapshot,
        hashlib.sha256(core_bytes).hexdigest(),
        hashlib.sha256(donor_bytes).hexdigest(),
    )

def run_expensive_audit(
    *,
    core: Path,
    donor: Path,
    output: Path,
    seeds_per_archetype: int,
) -> dict[str, Any]:
    if seeds_per_archetype < 20:
        raise ValueError("expensive acceptance audit requires at least 20 seeds per archetype")
    output.mkdir(parents=True, exist_ok=True)
    source_core = Path(core).resolve()
    source_donor = Path(donor).resolve()
    core, donor, snapshotted_core_hash, donor_hash = _snapshot_audit_inputs(
        source_core,
        source_donor,
        output,
    )
    profile = _load_default_profile()
    catalog = ContentCatalogSnapshot.from_core(
        core,
        allowlist=profile.content_allowlist,
    )
    if catalog.core_hash != snapshotted_core_hash:
        raise ValueError("catalog Core hash differs from the immutable audit snapshot")
    failures: list[dict[str, Any]] = []
    archetype_reports: dict[str, Any] = {}
    representatives: dict[str, Any] = {}
    fixed_seed_artifacts: dict[str, list[dict[str, Any]]] = {}
    scratch_root = output / ".preflight_scratch"
    for archetype in Archetype:
        fingerprints = {key: set() for key in DIVERSITY_FINGERPRINTS}
        successes = 0
        seed_artifacts: list[dict[str, Any]] = []
        for seed in range(1, seeds_per_archetype + 1):
            candidate = replace(profile, seed=seed, archetype=archetype).normalized()
            bundle_root = output / "bundles" / archetype.value / f"seed_{seed:04d}"
            stage_root = scratch_root / archetype.value / f"seed_{seed:04d}"
            try:
                service_result = _generate_representative(
                    candidate,
                    core=core,
                    donor=donor,
                    bundle_root=bundle_root,
                    catalog=catalog,
                )
                scenario = service_result.scenario
                validate_generated_ir(scenario).raise_for_errors()
                provenance = scenario.provenance
                if (
                    provenance.catalog_hash != catalog.fingerprint
                    or provenance.donor_hash != donor_hash
                ):
                    raise ValueError(
                        "fixed-seed artifact used different catalog or donor inputs"
                    )
                bundle_report = validate_bundle(service_result.bundle.root)
                bundle_report.raise_for_errors()
                staged = _stage_effective_core_and_preflight(
                    source_core=core,
                    bundle_root=service_result.bundle.root,
                    map_sid=service_result.bundle.map_sid,
                    stage_root=stage_root,
                    expected_core_hash=catalog.core_hash,
                )
                staged.pop("effectiveCore", None)
                staged["effectiveCoreRetained"] = False
                for key, value in _fingerprints(scenario).items():
                    fingerprints[key].add(value)
                artifact_row = {
                    "seed": seed,
                    "mapSid": service_result.bundle.map_sid,
                    "bundle": str(service_result.bundle.root),
                    "mechanicalFingerprint": scenario.mechanical_fingerprint,
                    "generationPath": "procedural_scenarios.service.generate_bundle",
                    "validation": bundle_report.to_dict(),
                    "stagedPreflight": staged,
                }
                seed_artifacts.append(artifact_row)
                successes += 1
                if archetype.value not in representatives:
                    representatives[archetype.value] = {
                        **artifact_row,
                        "presentation": service_result.presentation.manifest_fragment[
                            "presentation"
                        ],
                    }
            except Exception as exc:
                failures.append({
                    "archetype": archetype.value,
                    "seed": seed,
                    "stage": "fixed_seed_service_bundle_preflight",
                    "errorType": type(exc).__name__,
                    "error": str(exc),
                    "diagnostics": getattr(exc, "to_dict", lambda: None)(),
                })
            finally:
                if stage_root.exists():
                    try:
                        shutil.rmtree(stage_root)
                    except OSError as exc:
                        failures.append({
                            "archetype": archetype.value,
                            "seed": seed,
                            "stage": "fixed_seed_stage_cleanup",
                            "errorType": type(exc).__name__,
                            "error": str(exc),
                        })
        minimum_unique = max(2, int(seeds_per_archetype * 0.75))
        for key in DIVERSITY_FINGERPRINTS:
            if len(fingerprints[key]) < minimum_unique:
                failures.append({
                    "archetype": archetype.value,
                    "stage": "diversity",
                    "fingerprint": key,
                    "unique": len(fingerprints[key]),
                    "required": minimum_unique,
                })
        archetype_reports[archetype.value] = {
            "successes": successes,
            "requested": seeds_per_archetype,
            "fixedSeeds": list(range(1, seeds_per_archetype + 1)),
            "artifactValidatedSeeds": [row["seed"] for row in seed_artifacts],
            "stagedPreflightSeeds": [row["seed"] for row in seed_artifacts],
            "minimumUniqueRequired": minimum_unique,
            "uniqueFingerprints": {
                key: len(values) for key, values in fingerprints.items()
            },
        }
        fixed_seed_artifacts[archetype.value] = seed_artifacts
    if scratch_root.exists():
        try:
            shutil.rmtree(scratch_root)
        except OSError as exc:
            failures.append({
                "stage": "acceptance_scratch_cleanup",
                "errorType": type(exc).__name__,
                "error": str(exc),
            })
    size_reports: list[dict[str, Any]] = []
    size_seed = 10_000
    for size in (32, 48, 64):
        for archetype in Archetype:
            size_seed += 1
            candidate = replace(
                profile,
                seed=size_seed,
                map_size=size,
                archetype=archetype,
            ).normalized()
            try:
                scenario = generate_scenario(candidate, catalog, donor_hash=donor_hash)
                validate_generated_ir(scenario).raise_for_errors()
                size_reports.append({"size": size, "archetype": archetype.value, "ok": True})
            except Exception as exc:
                row = {"size": size, "archetype": archetype.value, "ok": False, "error": str(exc)}
                size_reports.append(row)
                failures.append({"stage": "size_matrix", **row})

    extreme_factions = _extreme_faction_sids(catalog)
    extreme_biomes = _extreme_biome_sids(catalog)
    extreme_reports = []
    for name, candidate in _profile_extremes(
        profile,
        faction_sids=extreme_factions,
        biome_sids=extreme_biomes,
    ):
        try:
            scenario = generate_scenario(
                candidate.normalized(),
                catalog,
                donor_hash=donor_hash,
            )
            validate_generated_ir(scenario).raise_for_errors()
            extreme_reports.append({"name": name, "seed": candidate.seed, "ok": True})
        except Exception as exc:
            row = {
                "name": name,
                "seed": candidate.seed,
                "ok": False,
                "error": str(exc),
            }
            extreme_reports.append(row)
            failures.append({"stage": "profile_extreme", **row})
    report = {
        "ok": not failures,
        "mode": "expensive",
        "core": str(source_core),
        "coreSnapshot": str(core),
        "coreHash": catalog.core_hash,
        "donor": str(source_donor),
        "donorSnapshot": str(donor),
        "donorHash": donor_hash,
        "catalogFingerprint": catalog.fingerprint,
        "archetypes": archetype_reports,
        "sizes": size_reports,
        "extremeInputs": {
            "factions": list(extreme_factions),
            "surfaceBiomes": list(extreme_biomes),
        },
        "extremes": extreme_reports,
        "fixedSeedArtifacts": fixed_seed_artifacts,
        "representatives": representatives,
        "rejectedSeeds": failures,
        "proofBoundary": (
            "source/static, generated artifact, and staged map-load preflight; "
            "install/runtime unproven"
        ),
    }
    report_path = output / "procedural_generation_audit.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expensive", action="store_true")
    parser.add_argument("--core", type=Path)
    parser.add_argument("--donor", type=Path)
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "build" / "procedural_audit")
    parser.add_argument("--seeds-per-archetype", type=int, default=20)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run_cheap_contract()
        if args.expensive:
            if args.core is None or args.donor is None:
                raise ValueError("--expensive requires --core and --donor")
            report = run_expensive_audit(
                core=args.core,
                donor=args.donor,
                output=args.output,
                seeds_per_archetype=args.seeds_per_archetype,
            )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report.get("ok") else 1
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "errorType": type(exc).__name__,
            "error": str(exc),
        }, indent=2, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
