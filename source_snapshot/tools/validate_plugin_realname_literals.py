"""Fail when a plugin string literal names a real-name game type or member that the new build dropped.

The symbol remap (tools/port_current) only re-derives what goes through GameSymbols. Plugin code outside
GameSymbols*.cs that binds a game type or member by a quoted real name ("UpdateView", "panelLossHero",
"Hex.UI.City.BhBuildingView.UpdateView") compiles on every build and silently binds nothing once the
obfuscator renames it. This scan reads both builds' interop indexes (tools/port_current port_index.tsv v2)
and reports every literal that resolves on the old build but not on the new one:

- a type literal (full or short name) whose type is gone;
- a member literal whose nearest context type (same line, else the closest earlier line within
  --context-lines that names a game type which had the member) lost it or is gone;
- a member literal with no such context that no longer exists on any new-build type.

Real names only: interop-generated names (Method_*, field_*, Native*Ptr_*) and constructors are not
indexed as members, so stale obfuscated tokens (GameSymbols' job) are out of scope.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MOD = Path("Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod")
GAME_BUILD = MOD / "GameBuild.cs"
CURRENT_SYMBOLS = MOD / "GameSymbolsCurrent.g.cs"
INDEX_TEMPLATE = "artifacts/port_current/idx2_live_{build}/port_index.tsv"
INDEX_HEADER = "#port_index.v2"
# Mirrors the Compile Remove globs in OfflineUnlockMod.csproj plus the GameSymbols resolver layer.
EXCLUDED_DIRS = {"_decompiled_shipped", "_decompiled_filtered", "_decompiled_release_hex", "tools", "obj", "bin"}
EXCLUDED_FILE = re.compile(r"^(GameSymbols.*|tmp_decomp_.*)\.cs$")
GENERATED_MEMBER = re.compile(r"^(Method_|field_|NativeFieldInfoPtr_|NativeMethodInfoPtr_|NativeClassPtr|\.c?ctor$)")
ACCESSOR_PREFIX = re.compile(r"^(get_|set_|add_|remove_)")
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DOTTED = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:[.+/][A-Za-z_][A-Za-z0-9_]*)+$")
CODE_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass
class Index:
	build: str
	types_full: set[str]
	types_short: dict[str, set[str]]
	members: dict[str, set[str]]
	all_members: set[str]

	def members_of_short(self, short: str) -> set[str] | None:
		fulls = self.types_short.get(short)
		if not fulls:
			return None
		merged: set[str] = set()
		for full in fulls:
			merged |= self.members.get(full, set())
		return merged


@dataclass
class Finding:
	file: str
	line: int
	literal: str
	reason: str

	def text(self) -> str:
		return f"{self.file}:{self.line}: \"{self.literal}\" {self.reason}"


def short_name(full: str) -> str:
	return re.split(r"[.+/]", full)[-1]


def load_index(path: Path, build: str) -> Index:
	if not path.is_file():
		raise SystemExit(f"realname literals: missing {build} index {path}; pass --old-index/--new-index explicitly")
	types_full: set[str] = set()
	types_short: dict[str, set[str]] = {}
	members: dict[str, set[str]] = {}
	with path.open(encoding="utf-8", errors="replace") as handle:
		header = handle.readline().strip()
		if header != INDEX_HEADER:
			raise SystemExit(f"realname literals: {path} header is {header!r}, expected {INDEX_HEADER!r}")
		for row in handle:
			cols = row.split("\t", 5)
			if len(cols) < 5:
				continue
			kind, full, name = cols[0], cols[2], cols[3]
			if kind == "T":
				types_full.add(full)
				types_short.setdefault(short_name(full), set()).add(full)
			elif kind in ("M", "P") and not GENERATED_MEMBER.match(name):
				bucket = members.setdefault(full, set())
				bucket.add(name)
				bucket.add(ACCESSOR_PREFIX.sub("", name))
	all_members = set().union(*members.values()) if members else set()
	if not types_full or not all_members:
		raise SystemExit(f"realname literals: {path} has no type or member rows")
	return Index(build, types_full, types_short, members, all_members)


def scan_source(source: str) -> tuple[list[tuple[int, str]], dict[int, set[str]]]:
	"""Return (line, value) string literals and code identifiers per line, skipping comments and char literals."""
	literals: list[tuple[int, str]] = []
	code: list[str] = []
	i, n, line = 0, len(source), 1

	def skip_string(start: int, verbatim: bool, interpolated: bool) -> int:
		nonlocal line
		buf: list[str] = []
		j = start
		while j < n:
			ch = source[j]
			if ch == "\n":
				line += 1
			if verbatim and ch == '"' and j + 1 < n and source[j + 1] == '"':
				buf.append('"')
				j += 2
				continue
			if not verbatim and ch == "\\" and j + 1 < n:
				buf.append(source[j:j + 2])
				j += 2
				continue
			if ch == '"':
				if not interpolated:
					literals.append((start_line, "".join(buf)))
				return j + 1
			if interpolated and ch == "{":
				if j + 1 < n and source[j + 1] == "{":
					j += 2
					continue
				j = skip_code(j + 1, stop_at_brace=True)
				continue
			buf.append(ch)
			j += 1
		return j

	def skip_code(start: int, stop_at_brace: bool) -> int:
		nonlocal line, start_line
		j = start
		depth = 0
		while j < n:
			ch = source[j]
			nxt = source[j + 1] if j + 1 < n else ""
			if ch == "\n":
				line += 1
				code.append("\n")
				j += 1
			elif ch == "/" and nxt == "/":
				end = source.find("\n", j)
				j = n if end < 0 else end
			elif ch == "/" and nxt == "*":
				end = source.find("*/", j + 2)
				end = n if end < 0 else end + 2
				newlines = source.count("\n", j, end)
				line += newlines
				code.append("\n" * newlines)
				j = end
			elif ch == "'":
				end = j + 1
				while end < n and source[end] != "'":
					end += 2 if source[end] == "\\" else 1
				j = end + 1
				code.append(" ")
			elif ch == '"' and source.startswith('"""', j):
				run = j
				while run < n and source[run] == '"':
					run += 1
				quotes = source[j:run]
				end = source.find(quotes, run)
				end = n if end < 0 else end
				line += source.count("\n", j, end)
				code.append("\n" * source.count("\n", j, end) + " ")
				j = end + len(quotes)
			elif ch in "$@" or ch == '"':
				prefix_end = j
				while prefix_end < n and source[prefix_end] in "$@":
					prefix_end += 1
				if prefix_end < n and source[prefix_end] == '"' and prefix_end - j <= 2:
					prefix = source[j:prefix_end]
					start_line = line
					before = line
					j = skip_string(prefix_end + 1, "@" in prefix, "$" in prefix)
					code.append("\n" * (line - before) + " ")
				else:
					code.append(ch)
					j += 1
			elif stop_at_brace and ch == "{":
				depth += 1
				code.append(ch)
				j += 1
			elif stop_at_brace and ch == "}":
				if depth == 0:
					return j + 1
				depth -= 1
				code.append(ch)
				j += 1
			else:
				code.append(ch)
				j += 1
		return j

	start_line = 1
	skip_code(0, stop_at_brace=False)
	identifiers: dict[int, set[str]] = {}
	for number, text in enumerate("".join(code).split("\n"), start=1):
		found = set(CODE_IDENTIFIER.findall(text))
		if found:
			identifiers[number] = found
	return literals, identifiers


def context_types(line: int, identifiers: dict[int, set[str]], literal_types: dict[int, set[str]],
		old: Index, context_lines: int) -> list[tuple[int, set[str]]]:
	"""Game type short names named on each line from `line` back to `line - context_lines`, nearest first."""
	result: list[tuple[int, set[str]]] = []
	for number in range(line, max(0, line - context_lines - 1), -1):
		names = {name for name in identifiers.get(number, ()) if name in old.types_short}
		names |= literal_types.get(number, set())
		if names:
			result.append((number, names))
	return result


def split_literal(value: str) -> str:
	"""Drop a trailing signature/description: "T.Member(string)" -> "T.Member", "T bind" -> "T"."""
	return re.split(r"[\s(<\[,:]", value.strip(), maxsplit=1)[0]


def check_file(rel: str, source: str, old: Index, new: Index, context_lines: int) -> list[Finding]:
	literals, identifiers = scan_source(source)
	literal_types: dict[int, set[str]] = {}
	for line, value in literals:
		token = split_literal(value)
		if token in old.types_full:
			literal_types.setdefault(line, set()).add(short_name(token))
		elif DOTTED.match(token):
			owner = re.split(r"[.+/]", token)
			owner_full = ".".join(owner[:-1])
			if owner_full in old.types_full:
				literal_types.setdefault(line, set()).add(owner[-2])
	findings: list[Finding] = []
	for line, value in literals:
		token = split_literal(value)
		if not token:
			continue
		if token in old.types_full:
			if token not in new.types_full:
				findings.append(Finding(rel, line, value, f"type {token} exists on {old.build} but not on {new.build}"))
			continue
		if DOTTED.match(token):
			parts = re.split(r"[.+/]", token)
			owner = ".".join(parts[:-1])
			member = parts[-1]
			if owner not in old.types_full or member not in old.members.get(owner, ()):
				continue
			if owner not in new.types_full:
				findings.append(Finding(rel, line, value, f"type {owner} exists on {old.build} but not on {new.build}"))
			elif member not in new.members.get(owner, ()):
				findings.append(Finding(rel, line, value, f"member {owner}.{member} exists on {old.build} but not on {new.build}"))
			continue
		if not IDENTIFIER.match(token):
			continue
		if token in old.types_short and token not in new.types_short:
			fulls = ", ".join(sorted(old.types_short[token]))
			findings.append(Finding(rel, line, value, f"type {fulls} exists on {old.build} but not on {new.build}"))
			continue
		if token not in old.all_members:
			continue
		reason = None
		decided = False
		for _, names in context_types(line, identifiers, literal_types, old, context_lines):
			owners = sorted(name for name in names if token in (old.members_of_short(name) or ()))
			if not owners:
				continue
			decided = True
			lost = []
			for owner in owners:
				now = new.members_of_short(owner)
				if now is None:
					lost.append(f"{owner} (type gone)")
				elif token not in now:
					lost.append(owner)
			if len(lost) == len(owners):
				reason = f"member on {', '.join(lost)} exists on {old.build} but not on {new.build}"
			break
		if not decided and token not in new.all_members and token not in new.types_short:
			reason = f"member exists on {old.build} but on no {new.build} type (no context type within {context_lines} lines)"
		if reason:
			findings.append(Finding(rel, line, value, reason))
	return findings


def plugin_sources(plugin_dir: Path) -> list[Path]:
	sources = []
	for path in sorted(plugin_dir.rglob("*.cs")):
		rel = path.relative_to(plugin_dir)
		if rel.parts[0] in EXCLUDED_DIRS or EXCLUDED_FILE.match(path.name):
			continue
		sources.append(path)
	return sources


def build_id_from(path: Path, pattern: str, label: str) -> str:
	try:
		text = path.read_text(encoding="utf-8")
	except OSError as ex:
		raise SystemExit(f"realname literals: cannot read {path} for the {label} build id: {ex}")
	found = re.findall(pattern, text)
	if not found:
		raise SystemExit(f"realname literals: no {label} build id in {path}; pass the index explicitly")
	return found[-1]


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
	parser.add_argument("--repo-root", type=Path, default=ROOT)
	parser.add_argument("--old-index", type=Path,
		help="port_index.tsv of the previous build (default: last GameBuild.RetiredBuilds entry)")
	parser.add_argument("--new-index", type=Path,
		help="port_index.tsv of the target build (default: GameSymbolsCurrent.g.cs BuildId)")
	parser.add_argument("--context-lines", type=int, default=25,
		help="earlier lines searched for the type a member literal belongs to")
	parser.add_argument("--json", type=Path, help="also write the findings as JSON")
	args = parser.parse_args(argv)

	started = time.monotonic()
	root = args.repo_root.resolve()
	old_index = args.old_index
	if old_index is None:
		old_build = build_id_from(root / GAME_BUILD, r'\("(\d+)",\s*"[0-9A-F]{64}"\)', "retired")
		old_index = root / INDEX_TEMPLATE.format(build=old_build)
	new_index = args.new_index
	if new_index is None:
		new_build = build_id_from(root / CURRENT_SYMBOLS, r'BuildId\s*=\s*"(\d+)"', "current")
		new_index = root / INDEX_TEMPLATE.format(build=new_build)
	old = load_index(old_index, old_index.parent.name)
	new = load_index(new_index, new_index.parent.name)

	plugin_dir = root / MOD
	sources = plugin_sources(plugin_dir)
	if not sources:
		raise SystemExit(f"realname literals: no plugin sources under {plugin_dir}")
	findings: list[Finding] = []
	for path in sources:
		rel = path.relative_to(plugin_dir).as_posix()
		findings.extend(check_file(rel, path.read_text(encoding="utf-8-sig", errors="replace"), old, new, args.context_lines))

	elapsed = time.monotonic() - started
	if args.json:
		args.json.write_text(json.dumps({
			"old": old.build, "new": new.build, "files": len(sources), "seconds": round(elapsed, 1),
			"findings": [finding.__dict__ for finding in findings]}, indent=1), encoding="utf-8")
	for finding in findings:
		print(finding.text())
	summary = (f"realname literals: {len(findings)} finding(s) in {len(sources)} files, "
		f"{old.build} -> {new.build}, {elapsed:.1f}s")
	if findings:
		print(f"FAIL {summary}", file=sys.stderr)
		return 1
	print(f"OK {summary}")
	return 0


if __name__ == "__main__":
	sys.exit(main())
