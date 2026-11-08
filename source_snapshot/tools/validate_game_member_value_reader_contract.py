"""Check the bounded GameMemberValueReader integration and its executable fixture."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("--repo-root", default=Path(__file__).resolve().parent.parent)
	parser.add_argument("--run-fixture", action="store_true",
		help="compile and run the synthetic C# fixture with PowerShell Add-Type")
	args = parser.parse_args()
	root = Path(args.repo_root).resolve()
	reader_path = root / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/GameMemberValueReader.cs"
	consumer_path = root / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3BulwarkRunesRuntime.cs"
	fixture_path = root / "tests/GameMemberValueReaderContract.cs"
	runner_path = root / "tests/run_game_member_value_reader_contract.ps1"

	errors: list[str] = []
	for path in (reader_path, consumer_path, fixture_path, runner_path):
		if not path.is_file():
			errors.append(f"missing required file: {path.relative_to(root)}")
	if errors:
		for error in errors:
			print("ERROR " + error)
		return 1

	reader = reader_path.read_text(encoding="utf-8")
	consumer = consumer_path.read_text(encoding="utf-8")
	fixture = fixture_path.read_text(encoding="utf-8")
	runner = runner_path.read_text(encoding="utf-8")

	if "AccessTools." in reader:
		errors.append("GameMemberValueReader must probe exact metadata without Harmony AccessTools misses")
	if "current.GetProperty(name, MemberFlags)" not in reader or "current.GetField(name, MemberFlags)" not in reader:
		errors.append("property and field metadata must use exact-name lookups")
	if "GetProperties(" in reader or "GetFields(" in reader:
		errors.append("property and field reads must not allocate all-member enumerations")
	if "BindingFlags.NonPublic" not in reader:
		errors.append("exact lookups must include non-public members")
	if not ("foreach (var name in names)" in reader
			and reader.index("var property = FindProperty(type, name")
			< reader.index("var field = FindField(type, name")
			< reader.index("var method = FindParameterlessMethod(type, name")):
		errors.append("reader must keep alias order and property, field, then parameterless-method priority")
	if reader.count("for (var current = type; current != null; current = current.BaseType)") != 3:
		errors.append("property, field, and method lookup must each walk the same derived-to-base hierarchy")
	if "property.GetIndexParameters().Length == 0" not in reader:
		errors.append("reader must not invoke an indexer without index arguments")
	if 'failure = FormatFailure(type, name, "property getter", ex);' not in reader:
		errors.append("a throwing getter must produce a diagnostic and stop lower-priority/alias reads")
	if "GameMemberValueReader.TryRead(target, names, out value, out var failure)" not in consumer:
		errors.append("Bulwark Runes TryReadMember must route through GameMemberValueReader")
	if "member read failed: " not in consumer:
		errors.append("Bulwark Runes must retain a capped diagnostic for actual member-read failures")
	for marker in (
		"alias order",
		"private inherited field",
		"private inherited property",
		"property before derived field",
		"field before base method",
		"zero-argument overload",
		"indexer is not a readable value member",
		"ambiguous property metadata was not reported",
		"getter failure was not reported precisely",
	):
		if marker not in fixture:
			errors.append(f"synthetic fixture is missing case: {marker}")
	if "Add-Type -Path @($reader, $fixture)" not in runner:
		errors.append("PowerShell runner must compile the production reader with the synthetic fixture")
	if args.run_fixture:
		pwsh = shutil.which("pwsh")
		if pwsh is None:
			errors.append("--run-fixture requires pwsh; no shell fallback is used")
		else:
			try:
				result = subprocess.run(
					[pwsh, "-NoProfile", "-File", str(runner_path)],
					cwd=root,
					capture_output=True,
					text=True,
					timeout=30,
					check=False,
				)
				if result.returncode != 0:
					errors.append("synthetic fixture failed: " + (result.stderr or result.stdout).strip())
				elif "GameMemberValueReader synthetic contract: OK" not in result.stdout:
					errors.append("synthetic fixture exited without its success marker")
			except subprocess.TimeoutExpired:
				errors.append("synthetic fixture exceeded the 30 second timeout")

	for error in errors:
		print("ERROR " + error)
	print(f"game member value reader contract: {'OK' if not errors else f'{len(errors)} errors'}")
	return 1 if errors else 0


if __name__ == "__main__":
	sys.exit(main())
