#!/usr/bin/env python3
"""Fast bench for one faction's unit design table: build its rows on top of an existing Core, score, gate, tune.

The full overlay build takes minutes and needs every faction's table to be valid. This bench takes one table
(custom_factions/unit_designs/<faction>.json, or any path), applies it with the real keyword code to the rows
of a built Core, and scores the result with unit_power_model in a few seconds. Nothing is written to the Core.

    python tools/release_port/unit_design_lab.py dump  --faction homm3_stronghold     # current rows, cards, texts
    python tools/release_port/unit_design_lab.py bands                                # vanilla stat and power bands
    python tools/release_port/unit_design_lab.py check --faction homm3_stronghold [--design path] [--notes]
    python tools/release_port/unit_design_lab.py tune  --faction homm3_stronghold [--design path] [--write]

check   builds, runs the static design rules, the tier stat band, Focus range and the power gate.
tune    scales HP and damage (inside the tier band, never below the base form) so each unit's weekly power
        lands on its target (unit field "powerTarget", default 1.0 = vanilla median of its tier and form), and
        sets squadValue from the vanilla value-per-power rate. --write stores the result in the table.
        The body pays for the kit: a strong card comes out with less HP and damage. If the tuner cannot reach the
        window (the card is too strong for any in-band body), it says so and the card has to change.
"""
from __future__ import annotations

import argparse
import copy
import json
import statistics
import sys
import zipfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import homm3_unit_design_table as design  # noqa: E402
import homm3_upgrade_pair_parity as parity  # noqa: E402
import unit_power_model as model  # noqa: E402

DEFAULT_CORE = Path("V:/olden_port_work/unit_rebalance/lab_base/Core.zip")
VANILLA_FACTIONS = {"human", "nature", "dungeon", "demon", "undead", "unfrozen"}
TUNE_WINDOW = 0.03
PAIR_GAP = 0.10        # the two alternates' power ratios may differ by at most this much
TARGET_RANGE = (0.88, 1.1)


def _read(release_zip: zipfile.ZipFile, output: dict[str, bytes], name: str) -> Any:
    raw = output[name] if name in output else release_zip.read(name)
    return json.loads(raw.decode("utf-8-sig"))


def build_rows(core_path: Path, doc: dict[str, Any]) -> tuple[dict[str, dict], dict[str, dict], dict[str, dict]]:
    """Apply one design table to the Core's rows in memory: (logic rows, view rows, buff rows)."""
    with zipfile.ZipFile(core_path) as archive:
        ctx = design._Ctx(archive, {}, _read)
        buffs: dict[str, dict] = {}
        for spec in doc.get("buffs", []):
            donor = ctx.buffs.get(spec["cloneOf"])
            if donor is None:
                raise RuntimeError(f"unit design buff {spec['id']}: donor buff {spec['cloneOf']!r} not found")
            row = copy.deepcopy(donor)
            row["id"] = spec["id"]
            design._deep_set(row, spec.get("set", {}))
            ctx.buffs[spec["id"]] = buffs[spec["id"]] = row
        logics: dict[str, dict] = {}
        views: dict[str, dict] = {}
        for sid, unit in doc["units"].items():
            logic = _read(archive, {}, ctx.path(sid, "l"))["array"][0]
            view = _read(archive, {}, ctx.path(sid, "v"))["array"][0]
            if logic.get("fraction") != doc["faction"]:
                raise RuntimeError(f"{sid}: row faction {logic.get('fraction')!r} is not {doc['faction']}")
            design._rebuild_unit(ctx, sid, unit, logic, view)
            logics[sid], views[sid] = logic, view
    return logics, views, buffs


def stat_bands(core: model.Core) -> dict[tuple[int, bool], dict[str, tuple[float, float]]]:
    samples: dict[tuple[int, bool], dict[str, list[float]]] = {}
    for row in core.units.values():
        if row.get("fraction") not in VANILLA_FACTIONS or not isinstance(row.get("tier"), int):
            continue
        if not (row.get("upgradeSid") or row.get("baseSid")):
            continue
        bucket = samples.setdefault((row["tier"], bool(row.get("baseSid"))), {})
        for key in design.STAT_KEYS:
            bucket.setdefault(key, []).append(row["stats"][key])
    return {g: {k: (min(v), max(v)) for k, v in s.items()} for g, s in samples.items()}


class Bench:
    def __init__(self, core_path: Path, doc: dict[str, Any]) -> None:
        self.core_path = core_path
        self.core = model.Core(core_path)
        self.bands = model.load_bands()
        self.stat_bands = stat_bands(self.core)
        self.doc = doc
        self.lines = [line[1:] for line in parity.unit_lines(parity.load_enabled_manifests()) if line[0] == doc["faction"]]

    def score(self, doc: dict[str, Any] | None = None) -> tuple[dict[str, dict], dict[str, dict], dict[str, dict]]:
        doc = doc or self.doc
        logics, views, buffs = build_rows(self.core_path, doc)
        core = copy.copy(self.core)
        core.units = {**self.core.units, **logics}
        core.buffs = {**self.core.buffs, **buffs}
        extras = model.runtime_extras({doc["faction"]: doc})
        scores = {sid: model.score_unit(core, row, self.bands["refs"], extras) for sid, row in logics.items()}
        for sid, s in scores.items():
            s["ratio"] = s["weeklyPower"] / self.bands["bands"][f"{s['tier']}:{s['variant']}"]["weeklyPower"]["median"]
        return scores, logics, views

    def errors(self, scores: dict[str, dict], logics: dict[str, dict], views: dict[str, dict]) -> list[str]:
        doc = self.doc
        errors = design.check_design(doc, self.lines)
        for sid, unit in doc["units"].items():
            row, view = logics[sid], views[sid]
            band = self.stat_bands[(row["tier"], bool(row.get("baseSid")))]
            for key in design.STAT_KEYS:
                low, high = band[key]
                if not low <= unit["stats"][key] <= high:
                    errors.append(f"{sid}: {key}={unit['stats'][key]} outside vanilla tier {row['tier']} band {low:g}..{high:g}")
            low_focus, high_focus = design.FOCUS_BY_TIER[row["tier"]]
            for ability in row.get("abilities") or []:
                focus = ability.get("energyLevel")
                if "xHomm3AbilityOverride" not in ability and not (isinstance(focus, int) and low_focus <= focus <= high_focus):
                    errors.append(f"{sid}: active Focus cost {focus!r} outside tier {row['tier']} range {low_focus}..{high_focus}")
            actives = [e for e in unit["kit"] if e["k"] in design.ACTIVE_KEYWORDS]
            passives = [e for e in unit["kit"] if e["k"] not in design.ACTIVE_KEYWORDS and e["k"] != "alt_swirl"
                        and not design.runtime_mirror(e)]
            if len(row.get("abilities") or []) != len(actives) or len(view.get("abilities") or []) != len(actives):
                errors.append(f"{sid}: {len(actives)} active kit item(s) but the build has {len(row.get('abilities') or [])} logic / {len(view.get('abilities') or [])} card")
            shown = [p for p in view.get("passives") or [] if p.get("name") not in design.VIEW_MARKER_PASSIVES]
            if len(shown) != len(passives):
                errors.append(f"{sid}: {len(passives)} passive kit item(s) but the card lists {len(shown)}")
            target = unit.get("powerTarget", 1.0)
            if not TARGET_RANGE[0] <= target <= TARGET_RANGE[1]:
                errors.append(f"{sid}: powerTarget {target} outside {TARGET_RANGE}")
            errors += model.gate(scores[sid], self.bands)
        for base, upg, alt in self.lines:
            if upg in scores and alt in scores and abs(scores[upg]["ratio"] - scores[alt]["ratio"]) > PAIR_GAP:
                errors.append(f"{upg}/{alt}: alternates' power {scores[upg]['ratio']:.2f}x vs {scores[alt]['ratio']:.2f}x differ by more than {PAIR_GAP}")
        return errors

    def report(self, scores: dict[str, dict], notes: bool = False) -> None:
        for base, upg, alt in self.lines:
            for sid in (base, upg, alt):
                if sid not in scores:
                    continue
                s, unit = scores[sid], self.doc["units"][sid]
                st = unit["stats"]
                print(f"{sid:36} T{s['tier']} {s['variant']:4} {unit['role']:8} hp{st['hp']:<4} A{st['offence']:<3} D{st['defence']:<3} {st['damageMin']}-{st['damageMax']:<4} sp{st['speed']:<2} in{st['initiative']:<2} "
                      f"x{s['growth']:<2} off {s['offence']:7.1f} tough {s['toughness']:7.1f} util {s['utility']:.1f} = {s['ratio']:.2f}x  kit {len(unit['kit'])} sv {unit['squadValue']}")
                if notes:
                    for note in s["notes"]:
                        print("        ", note)

    # ---- tuner ---------------------------------------------------------------------------------
    def tune(self) -> list[str]:
        doc = self.doc
        problems: list[str] = []
        tiers = {sid: row["tier"] for sid, row in build_rows(self.core_path, doc)[0].items()}

        def band(sid: str, is_upg: bool) -> dict[str, tuple[float, float]]:
            return self.stat_bands[(tiers[sid], is_upg)]

        def fit(sids: list[str], floors: dict[str, dict[str, int]], is_upg: bool) -> None:
            for _ in range(40):
                scores, _, _ = self.score()
                moved = False
                for sid in sids:
                    unit = doc["units"][sid]
                    target = unit.get("powerTarget", 1.0)
                    ratio = scores[sid]["ratio"]
                    if abs(ratio / target - 1.0) <= TUNE_WINDOW:
                        continue
                    stats = unit["stats"]
                    factor = max(0.6, min(1.6, target / ratio))
                    b = band(sid, is_upg)
                    floor = floors.get(sid, {})
                    before = (stats["hp"], stats["damageMin"], stats["damageMax"])
                    spread = stats["damageMax"] / max(1, stats["damageMin"])

                    def clamp(key: str, value: float) -> int:
                        low = max(b[key][0], floor.get(key, 0))
                        return int(max(low, min(b[key][1], round(value))))

                    hp = clamp("hp", stats["hp"] * factor)
                    dmax = clamp("damageMax", stats["damageMax"] * factor)
                    dmin = clamp("damageMin", min(dmax, dmax / spread))
                    if (hp, dmin, dmax) == before:
                        # Rounding stalled or HP/damage are pinned: move one stat by one, body first, then Attack/Defence.
                        step = 1 if factor > 1 else -1
                        hp2, dmax2 = clamp("hp", stats["hp"] + step), clamp("damageMax", stats["damageMax"] + step)
                        dmin2 = clamp("damageMin", min(dmax, stats["damageMin"] + step))
                        if hp2 != stats["hp"] and (stats["hp"] >= 3 * stats["damageMax"] or dmax2 == stats["damageMax"]):
                            hp = hp2
                        elif dmax2 != stats["damageMax"]:
                            dmax = dmax2
                        elif dmin2 != stats["damageMin"]:
                            dmin = dmin2
                        elif hp2 != stats["hp"]:
                            hp = hp2
                        else:
                            for key in (("offence", "defence") if stats["offence"] <= stats["defence"] else ("defence", "offence")) if step > 0 else (("offence", "defence") if stats["offence"] >= stats["defence"] else ("defence", "offence")):
                                value = clamp(key, stats[key] + step)
                                if value != stats[key]:
                                    stats[key] = value
                                    moved = True
                                    break
                    stats["hp"], stats["damageMin"], stats["damageMax"] = hp, min(dmin, dmax), dmax
                    moved = moved or (stats["hp"], stats["damageMin"], stats["damageMax"]) != before
                if not moved:
                    break

        bases = [line[0] for line in self.lines]
        fit(bases, {}, False)
        # Upgrades never fall below the base form: when an upgrade's kit is so strong that it needs a smaller
        # body than its base has, the base comes down with it (to the low end of its window) before giving up.
        for attempt in range(4):
            floors = {}
            for base, upg, alt in self.lines:
                for sid in (upg, alt):
                    floors[sid] = dict(doc["units"][base]["stats"])
                    for key, low in floors[sid].items():
                        doc["units"][sid]["stats"][key] = max(doc["units"][sid]["stats"][key], low)
            fit([sid for line in self.lines for sid in line[1:]], floors, True)
            scores, _, _ = self.score()
            stuck = [line for line in self.lines if any(scores[sid]["ratio"] > doc["units"][sid].get("powerTarget", 1.0) * (1 + 2 * TUNE_WINDOW) for sid in line[1:])]
            if not stuck:
                break
            for base, upg, alt in stuck:
                unit = doc["units"][base]
                unit["powerTarget"] = round(max(TARGET_RANGE[0], unit.get("powerTarget", 1.0) - 0.05), 2)
            fit([line[0] for line in stuck], {}, False)
        scores, _, _ = self.score()
        for sid, unit in doc["units"].items():
            target = unit.get("powerTarget", 1.0)
            if abs(scores[sid]["ratio"] / target - 1.0) > 2.5 * TUNE_WINDOW:
                problems.append(f"{sid}: tuner stopped at {scores[sid]['ratio']:.2f}x (target {target}); HP/damage are at a band edge or the base floor, change the kit or other stats")
        # Value for the AI and experience: vanilla squadValue per point of model power in the same tier and form.
        for base, upg, alt in self.lines:
            values = {}
            for sid in (base, upg, alt):
                s = scores[sid]
                rate = self.bands["bands"][f"{s['tier']}:{s['variant']}"]["squadValuePerPower"]
                values[sid] = s["power"] * rate
            doc["units"][base]["squadValue"] = int(round(values[base]))
            doc["units"][upg]["squadValue"] = doc["units"][alt]["squadValue"] = int(round(max(values[base] + 1, (values[upg] + values[alt]) / 2)))
        return problems


def dump(core_path: Path, faction: str) -> None:
    core = model.Core(core_path)
    texts: dict[str, str] = {}
    views: dict[str, dict] = {}
    with zipfile.ZipFile(core_path) as archive:
        for name in archive.namelist():
            if name.startswith("Lang/english/texts/") and name.endswith(".json"):
                doc = json.loads(archive.read(name).decode("utf-8-sig"))
                for row in (doc.get("tokens") or doc.get("array") or []) if isinstance(doc, dict) else []:
                    if isinstance(row, dict) and isinstance(row.get("sid"), str):
                        texts[row["sid"]] = row.get("text") or ""
            elif name.startswith("DB/units/units_views/") and name.endswith(".json"):
                for row in json.loads(archive.read(name).decode("utf-8-sig")).get("array") or []:
                    if isinstance(row, dict) and isinstance(row.get("id"), str):
                        views[row["id"]] = row
    bands = model.load_bands()
    lines = [line[1:] for line in parity.unit_lines(parity.load_enabled_manifests()) if line[0] == faction]
    for line in lines:
        for sid in line:
            row, view = core.units[sid], views[sid]
            s = model.score_unit(core, row, bands["refs"])
            median = bands["bands"][f"{s['tier']}:{s['variant']}"]["weeklyPower"]["median"]
            st = row["stats"]
            gold = [c.get("cost") for c in row["unitCost"]["costResArray"] if c.get("name") == "gold"]
            attack = row["defaultAttacks"][0]
            print(f"\n## {sid}  ({texts.get(view.get('name', ''), texts.get(sid + '_name', '?'))})  tier {row['tier']} {s['variant']}  growth {s['growth']}/week  gold {gold}  squadValue {row.get('squadValue')}")
            print(f"   hp {st['hp']} atk {st['offence']} def {st['defence']} dmg {st['damageMin']}-{st['damageMax']} speed {st['speed']} init {st['initiative']} move {st.get('moveType', 'walk')} "
                  f"attack {attack.get('attackType_')} pattern {attack['damageDealer'].get('attackPatternSid')}  model power now {s['weeklyPower'] / median:.2f}x vanilla median")
            extra = {k: v for k, v in st.items() if k in ("damagePerHex", "ignoreShootDmgBuff", "ignoreShootingBlock", "numCounters", "armorPen", "ammo") and v not in (None, 1, False)}
            mods = [(m["t"], m["v"]) for m in model._mods(st, "inDmgMods")] + [("out:" + m["t"], m["v"]) for m in model._mods(st, "outDmgMods")]
            if extra or mods:
                print(f"   stats+ {extra} mods {mods}")
            for bucket in ("passives", "abilities", "alternativeAttacks"):
                for card in view.get(bucket) or []:
                    print(f"   [{bucket[:-1]}] view={card.get('name')} :: {texts.get(card.get('name', ''), '?')}: {texts.get(card.get('description', ''), '?')}")


def print_bands(core_path: Path) -> None:
    core = model.Core(core_path)
    bands = model.load_bands()
    sb = stat_bands(core)
    for (tier, upg), stats in sorted(sb.items()):
        b = bands["bands"][f"{tier}:{'upg' if upg else 'base'}"]
        print(f"tier {tier} {'upgraded' if upg else 'base    '}: " + "  ".join(f"{k} {lo:g}..{hi:g}" for k, (lo, hi) in stats.items())
              + f"  | weekly power median {b['weeklyPower']['median']:.0f}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=("dump", "bands", "check", "tune"))
    parser.add_argument("--faction")
    parser.add_argument("--design", type=Path)
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    parser.add_argument("--notes", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.mode == "bands":
        print_bands(args.core)
        return 0
    if not args.faction:
        parser.error("--faction is required")
    if args.mode == "dump":
        dump(args.core, args.faction)
        return 0
    path = args.design or design.DESIGN_DIR / f"{args.faction}.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    bench = Bench(args.core, doc)
    problems: list[str] = []
    if args.mode == "tune":
        problems = bench.tune()
        if args.write:
            path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    scores, logics, views = bench.score()
    bench.report(scores, args.notes)
    errors = bench.errors(scores, logics, views) + problems
    ratios = [s["ratio"] for s in scores.values()]
    print(f"\nfaction median {statistics.median(ratios):.2f}x, min {min(ratios):.2f}x, max {max(ratios):.2f}x")
    for error in errors:
        print("ERROR:", error)
    print(f"unit-design-lab {args.mode}: {len(errors)} error(s), {len(scores)} unit(s)" + (" (table written)" if args.mode == "tune" and args.write else ""))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
