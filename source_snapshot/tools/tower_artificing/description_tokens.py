"""Resolve `{n}` tokens in unit passive descriptions for Tower Artificing graft buff text.

Unit passive descriptions are templates: `Lang/args/unitsAbility.json` maps a description sid to script
names in `DB/info/**/*.script`, and the game evaluates them against the unit being inspected. A graft buff
shows the text out of that context, so the generator evaluates the scripts against the source unit's Core
logic with an empty stack (fullStacks 0, so per-stack terms count one unit).

Only the unit-script subset is implemented (CurrentUnitConfig/Data/Stats, Db* lookups, arithmetic, Invoke,
Text). Anything else raises `Unresolved`, and the curated payload must then give `descriptionText`.
CPU only; parses ~60 script files once (<0.1 s).
"""
from __future__ import annotations

import json
import math
import re
import zipfile
from typing import Any

SCRIPT_ENTRY = re.compile(r"(?ms)^\s*(string|modInt|modPercentNumeric|int|float|modFloat)\s+([A-Za-z0-9_]+)\s*\{(.*?)^\s*\}")
STATEMENT = re.compile(r"([A-Za-z]+)\s*\(([^()]*)\)")


class Unresolved(Exception):
    pass


def _strip(text: str) -> str:
    return re.sub(r"//[^\n]*", "", text)


def _split_args(raw: str) -> list[str]:
    out, cur, quoted = [], "", False
    for ch in raw:
        if ch == '"':
            quoted = not quoted
            cur += ch
        elif ch == "," and not quoted:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def _path_get(doc: Any, path: str, missing: Any = None) -> Any:
    """Walk `a.b[0].c`; a missing member is `missing` (the game reads absent config numbers as 0) or Unresolved."""
    cur = doc
    for part in re.findall(r"[^.\[\]]+|\[\d+\]", path):
        if part.startswith("["):
            idx = int(part[1:-1])
            if not isinstance(cur, list) or idx >= len(cur):
                if missing is not None:
                    return missing
                raise Unresolved(f"path {path}: index {idx} missing")
            cur = cur[idx]
        else:
            if not isinstance(cur, dict) or part not in cur:
                if missing is not None:
                    return missing
                raise Unresolved(f"path {path}: key {part} missing")
            cur = cur[part]
    return cur


def _num(value: Any) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            pass
    raise Unresolved(f"not a number: {value!r}")


def _fmt_number(value: float) -> str:
    if abs(value - round(value)) < 1e-6:
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


class TokenResolver:
    def __init__(self, zf: zipfile.ZipFile, logics: dict[str, dict[str, Any]], texts: dict[str, str]):
        self.logics = logics
        self.texts = texts
        self.scripts: dict[str, tuple[str, list[tuple[str, list[str]]]]] = {}
        names = zf.namelist()
        for name in names:
            if name.startswith("DB/info/") and name.endswith(".script"):
                text = _strip(zf.read(name).decode("utf-8-sig"))
                for kind, sid, body in SCRIPT_ENTRY.findall(text):
                    statements = [(op, _split_args(raw)) for op, raw in STATEMENT.findall(body)]
                    self.scripts.setdefault(sid, (kind, statements))
        self.args: dict[str, list[str]] = {}
        if "Lang/args/unitsAbility.json" in names:
            doc = json.loads(zf.read("Lang/args/unitsAbility.json").decode("utf-8-sig"))
            for row in doc.get("tokensArgs") or []:
                self.args[row["sid"]] = list(row.get("args") or [])
        self.db: dict[str, dict[str, dict[str, Any]]] = {"buff": {}, "side_buff": {}, "obstacle": {}}
        prefixes = {"DB/buffs/": "buff", "DB/side_buffs/side_buff_base/": "side_buff", "DB/field_objects/obstacles/": "obstacle"}
        for name in names:
            kind = next((k for p, k in prefixes.items() if name.startswith(p)), None)
            if kind and name.endswith(".json"):
                doc = json.loads(re.sub(r"(?m)^\s*//.*$", "", zf.read(name).decode("utf-8-sig")))
                for row in doc.get("array", []) if isinstance(doc, dict) else []:
                    if isinstance(row, dict) and "id" in row:
                        self.db[kind].setdefault(row["id"], row)

    def _value(self, token: str, env: dict[str, Any]) -> Any:
        if token.startswith('"') and token.endswith('"'):
            return token[1:-1]
        if token in env:
            return env[token]
        try:
            return float(token)
        except ValueError:
            raise Unresolved(f"unknown variable {token}") from None

    def run(self, script: str, logic: dict[str, Any], depth: int = 0) -> tuple[str, Any]:
        if depth > 8 or script not in self.scripts:
            raise Unresolved(f"script {script} not found")
        kind, statements = self.scripts[script]
        env: dict[str, Any] = {}
        stats = logic.get("stats") or {}
        for op, args in statements:
            ret = args[0] if args else ""
            vals = args[1:]
            if op == "Text":
                env[ret] = self._value(vals[0], env)
            elif op == "CurrentUnitConfig":
                env[ret] = _path_get(logic, self._value(vals[0], env), 0.0)
            elif op == "CurrentUnitStats":
                env[ret] = _num(_path_get(stats, self._value(vals[0], env), 0.0))
            elif op == "CurrentUnitData":
                field = self._value(vals[0], env)
                if field in ("fullStacks", "tempFullStacks", "startBattleFullStacks"):
                    env[ret] = 0.0
                elif field.startswith("unit.stats."):
                    env[ret] = _num(stats.get(field[len("unit.stats."):], 0))
                else:
                    raise Unresolved(f"CurrentUnitData {field}")
            elif op in ("DbBuff", "DbSideBuff", "DbObstacle"):
                table = self.db[{"DbBuff": "buff", "DbSideBuff": "side_buff", "DbObstacle": "obstacle"}[op]]
                sid = self._value(vals[0], env)
                if sid not in table:
                    raise Unresolved(f"{op} {sid} missing")
                env[ret] = _path_get(table[sid], self._value(vals[1], env))
            elif op in ("Add", "Plus"):
                env[ret] = _num(self._value(vals[0], env)) + _num(self._value(vals[1], env))
            elif op == "Sub":
                env[ret] = _num(self._value(vals[0], env)) - _num(self._value(vals[1], env))
            elif op in ("Mul", "Multiply"):
                env[ret] = _num(self._value(vals[0], env)) * _num(self._value(vals[1], env))
            elif op == "Div":
                den = _num(self._value(vals[1], env))
                env[ret] = _num(self._value(vals[0], env)) / den if den else 0.0
            elif op == "Floor":
                env[ret] = float(math.floor(_num(self._value(vals[0], env))))
            elif op == "Avg":
                env[ret] = (_num(self._value(vals[0], env)) + _num(self._value(vals[1], env))) / 2
            elif op == "Invoke":
                env[ret] = self.run(self._value(vals[0], env), logic, depth + 1)[1]
            else:
                raise Unresolved(f"op {op} not supported")
        if "return" not in env:
            raise Unresolved(f"script {script} has no return")
        return kind, env["return"]

    def format_arg(self, arg: str, logic: dict[str, Any]) -> str:
        script, _, alt = arg.partition("|")
        try:
            kind, value = self.run(script, logic)
        except Unresolved:
            if alt and alt in self.texts and "{" not in self.texts[alt]:
                return self.texts[alt]
            raise
        if kind == "string" and isinstance(value, str):
            try:
                value = float(value)
            except ValueError:
                return value
        number = _num(value)
        if kind == "modPercentNumeric":
            return _fmt_number(abs(number * 100))
        if kind == "modInt":
            return _fmt_number(abs(round(number)))
        return _fmt_number(number)

    def resolve(self, description_sid: str, template: str, unit_sids: list[str]) -> str:
        """Fill `{n}` from the first source unit whose scripts all evaluate."""
        if not re.search(r"\{\d+\}", template):
            return template
        args = self.args.get(description_sid)
        if not args:
            raise Unresolved(f"no tokensArgs for {description_sid}")
        last: Exception | None = None
        for sid in unit_sids:
            logic = self.logics.get(sid)
            if logic is None:
                continue
            try:
                values = [self.format_arg(a, logic) for a in args]
            except (Unresolved, IndexError, ValueError, TypeError) as exc:
                last = exc
                continue

            def sub(match: re.Match[str]) -> str:
                idx = int(match.group(1))
                if idx >= len(values):
                    raise Unresolved(f"token {{{idx}}} has no arg")
                return values[idx]

            try:
                return re.sub(r"\{(\d+)\}", sub, template)
            except Unresolved as exc:
                last = exc
        raise Unresolved(str(last) if last else "no source unit logic")
