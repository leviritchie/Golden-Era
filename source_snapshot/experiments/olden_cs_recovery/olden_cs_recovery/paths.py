"""Path anchors for the olden_cs_recovery package."""

from __future__ import annotations

from pathlib import Path

# experiments/olden_cs_recovery/
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
# repo root: V:/Games/Olden Era Playtest Tweak
REPO_ROOT = PACKAGE_ROOT.parents[1]

SCHEMAS_DIR = PACKAGE_ROOT / "schemas"
QUEUE_PARTITIONS_DIR = PACKAGE_ROOT / "queue" / "partitions"
PROOF_LEDGER_ENTRIES_DIR = PACKAGE_ROOT / "proof_ledger" / "entries"
INPUT_MANIFEST_PATH = PACKAGE_ROOT / "input_manifest.json"

# DiffableCs Hex assembly root (edb.cs + Hex/Session/Battle/...).
DEFAULT_DIFFABLE_HEX_ROOT = (
    REPO_ROOT / "tmp" / "cpp2il_experiment" / "out_dev_diffable_cs" / "DiffableCs" / "Hex"
)
DEFAULT_ISIL_HEX_ROOT = REPO_ROOT / "tmp" / "cpp2il_experiment" / "out_dev_isil" / "IsilDump" / "Hex"

IR_DIR = PACKAGE_ROOT / "ir"
RECOVERED_DIR = PACKAGE_ROOT / "recovered"
ORACLE_TRACES_DIR = PACKAGE_ROOT / "oracle_traces"
ORACLE_TRACES_LIVE_DIR = ORACLE_TRACES_DIR / "live"
ORACLE_TRACES_SYNTHETIC_DIR = ORACLE_TRACES_DIR / "synthetic"
IDENTITY_PROOFS_DIR = PACKAGE_ROOT / "proof_ledger" / "identity_probes"

BATTLE_EVENTARGS_REL = Path("Hex") / "Session" / "Battle"
EDB_REL = Path("edb.cs")
EDB_ISIL_REL = Path("edb.txt")

ROLES = (
    "dumper",
    "lifter",
    "renamer",
    "oracle_capturer",
    "equiv_tester",
    "promoter",
    "auditor",
)

STAGES = (
    "lift",
    "rename",
    "oracle_capture",
    "equiv_test",
    "promote",
    "blocked",
)

# Role -> stages that role may claim.
ROLE_CLAIM_STAGES: dict[str, frozenset[str]] = {
    "dumper": frozenset(),  # input pinning only; does not claim method work items
    "lifter": frozenset({"lift"}),
    "renamer": frozenset({"rename"}),
    # equiv_test allowed so surface→live_execution upgrades can re-claim without inventing stages.
    "oracle_capturer": frozenset({"oracle_capture", "equiv_test"}),
    "equiv_tester": frozenset({"equiv_test"}),
    "promoter": frozenset({"promote"}),
    "auditor": frozenset({"lift", "rename", "oracle_capture", "equiv_test", "promote", "blocked"}),
}

PROOF_STATUSES = (
    "static-lifted",
    "renamed-proposed",
    "renamed-accepted",
    "identity-bridged",
    "oracle-captured",
    "equivalence-proven",
    "blocked",
)

# Explicit stage transitions only (no silent jumps).
ALLOWED_STAGE_TRANSITIONS: dict[str, frozenset[str]] = {
    "lift": frozenset({"rename", "blocked"}),
    "rename": frozenset({"oracle_capture", "blocked"}),
    "oracle_capture": frozenset({"equiv_test", "blocked"}),
    "equiv_test": frozenset({"promote", "blocked"}),
    "promote": frozenset({"blocked"}),
    "blocked": frozenset(),  # unblock requires explicit human/auditor workflow later
}
