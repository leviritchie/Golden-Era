"""Direct State M4 damage side-effect write-body helpers (stack/HP + lastCorpse)."""

from __future__ import annotations

from typing import Any

# DummyDLL / method_pointers VAs (GameAssembly preferred base 0x180000000).
DAMAGE_SIDE_NATIVE_VAS: dict[str, str] = {
    "Hex.Session.Battle.UnitData::bfde(int)": "0x1820781D0",
    "Hex.Session.Battle.UnitData::bfda()": "0x182078160",
    "Hex.Session.Battle.UnitData::bfdf()": "0x182078290",
    "Hex.Session.Battle.Hex::bcxo(Unit)": "0x1805EA470",
    "Hex.Session.Battle.Hex::bcxn()": "0x1805EA440",
}

LIFECYCLE_SPAWN_NATIVE_VAS: dict[str, str] = {
    "Hex.Session.Battle.Unit::Init(int,eep,eir,Hex,int,int,int,string,bool,bool)": "0x182064CB0",
}

# bfdd shares bfde's VA — never seed as a distinct write body.
DAMAGE_SIDE_DUPLICATE_VAS: dict[str, str] = {
    "Hex.Session.Battle.UnitData::bfdd(int)": "0x1820781D0",
}


def is_damage_side_method(method_id: str, *, domain: str | None = None) -> bool:
    if domain and str(domain).startswith("DirectState.WriteBody/DamageSide"):
        return True
    return method_id in DAMAGE_SIDE_NATIVE_VAS


def is_lifecycle_spawn_method(method_id: str, *, domain: str | None = None) -> bool:
    if domain and str(domain).startswith("DirectState.WriteBody/LifecycleSpawn"):
        return True
    return method_id in LIFECYCLE_SPAWN_NATIVE_VAS


def native_va_for_damage_side(method_id: str) -> str | None:
    return DAMAGE_SIDE_NATIVE_VAS.get(method_id) or LIFECYCLE_SPAWN_NATIVE_VAS.get(method_id)


def expected_field_delta_engine_damage_side(method_id: str) -> dict[str, Any]:
    """
    Recovered expected engine outputs for EquivTester.

    Derived from ISIL UnitData.txt / Hex bcxo store notes — not invented CF.
    """
    if method_id.endswith("::bfde(int)") or method_id == "Hex.Session.Battle.UnitData::bfde(int)":
        # bfde(<=0) clears fullStacks (+0x34), hpLastUnit/temp via +0x40 qword, flag +0x50.
        return {
            "hasRealDiff": True,
            "fieldDelta": {
                "fullStacks": {"from": 3, "to": 0},
                "hpLastUnit": {"from": 7, "to": 0},
            },
            "requiredDeltaKeys": ["fullStacks", "hpLastUnit"],
        }
    if method_id.endswith("::bfda()") or method_id == "Hex.Session.Battle.UnitData::bfda()":
        # allStacks = (hpLastUnit>0?1:0) + tempFullStacks + fullStacks
        return {
            "hasRealDiff": True,
            "fieldDelta": {
                "returnAllStacks": {"from": None, "to": 4},
            },
            "requiredDeltaKeys": ["returnAllStacks"],
        }
    if method_id.endswith("::bfdf()") or method_id == "Hex.Session.Battle.UnitData::bfdf()":
        return {
            "hasRealDiff": True,
            "fieldDelta": {
                "returnAlive": {"from": None, "to": True},
            },
            "requiredDeltaKeys": ["returnAlive"],
        }
    if method_id.endswith("::bcxo(Unit)") or method_id == "Hex.Session.Battle.Hex::bcxo(Unit)":
        return {
            "hasRealDiff": True,
            "fieldDelta": {
                "lastCorpseWasNull": {"from": True, "to": False},
                "lastCorpseSameAsPlanted": {"from": False, "to": True},
            },
            "requiredDeltaKeys": ["lastCorpseWasNull", "lastCorpseSameAsPlanted"],
        }
    if method_id.endswith("::bcxn()") or method_id == "Hex.Session.Battle.Hex::bcxn()":
        return {
            "hasRealDiff": True,
            "fieldDelta": {
                "returnWasNull": {"from": True, "to": False},
                "returnSameAsPlanted": {"from": None, "to": True},
            },
            "requiredDeltaKeys": ["returnWasNull"],
        }
    if "Unit::Init(" in method_id:
        # Full Init plant needs eep/eir/Hex/config — refuse invented deltas.
        return {
            "hasRealDiff": False,
            "fieldDelta": {},
            "requiredDeltaKeys": [],
            "notes": (
                "Unit.Init requires battle plant (eep/eir/Hex/configSid). "
                "Bar C refuses fabricated Init deltas; capture with live battle fixtures or block."
            ),
        }
    raise KeyError(f"no damage-side field-delta expectation for {method_id}")
