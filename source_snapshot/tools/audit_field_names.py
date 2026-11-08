#!/usr/bin/env python3
"""Scan source for hardcoded field/method name strings and suggest replacements from dump."""
import re, sys, os
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from map_obfuscation import parse_dump

DUMP = r"tools\il2cpp_out_live\dump.cs"
SOURCE = r"Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod"

d = parse_dump(DUMP)

# Build type index: short_name -> full_name
type_index = {}
field_index = defaultdict(dict)  # type_short -> {field_name: field_type}
for full, info in d.items():
    sn = full.split('.')[-1]
    type_index[sn] = full
    for fname, ftype in info.fields:
        field_index[sn][fname] = ftype
    for pname, ptype in info.properties:
        field_index[sn][pname] = ptype  # properties too

# Scan source for string literals that look like obfuscated field names
results = []
for cs_file in Path(SOURCE).rglob("*.cs"):
    if "Probe" in cs_file.name or "obj" in str(cs_file):
        continue
    try:
        content = cs_file.read_text(encoding="utf-8", errors="replace")
    except:
        continue
    
    rel = str(cs_file.relative_to(SOURCE))
    
    # Find string literals matching obfuscated patterns (3-6 lowercase letters)
    for m in re.finditer(r'"([a-z]{3,6})"', content):
        field = m.group(1)
        # Skip common non-obfuscated words
        if field in ('null', 'true', 'false', 'var', 'new', 'int', 'void', 'bool', 'string', 'float', 'class', 'this', 'base'):
            continue
        
        # Check which types have this field
        matching_types = []
        for tsn, tfull in type_index.items():
            if field in field_index.get(tsn, {}):
                matching_types.append(tfull)
        
        if matching_types:
            line_no = content[:m.start()].count('\n') + 1
            results.append((field, rel, line_no, matching_types))

# Group by field name
grouped = defaultdict(list)
for field, file, line, types in results:
    grouped[field].append((file, line, types))

# Print report
print("=== HARDCODED FIELD NAMES FOUND IN LIVE DUMP ===")
print(f"{'Field':8s} {'Refs':5s} {'Files':30s} {'Valid On Types'}")
print("-" * 90)
for field in sorted(grouped):
    entries = grouped[field]
    files = sorted(set(e[0] for e in entries))
    all_types = set()
    for _, _, types in entries:
        all_types.update(types)
    print(f"{field:8s} {len(entries):5d} {', '.join(files[:3]):30s} {', '.join(sorted(all_types)[:4])}")

print(f"\n=== FIELDS NOT FOUND IN ANY LIVE TYPE (STALE) ===")
stale = defaultdict(list)
for cs_file in Path(SOURCE).rglob("*.cs"):
    if "Probe" in cs_file.name:
        continue
    try:
        content = cs_file.read_text(encoding="utf-8", errors="replace")
    except:
        continue
    rel = str(cs_file.relative_to(SOURCE))
    for m in re.finditer(r'"([a-z]{3,6})"', content):
        field = m.group(1)
        if field in grouped:
            continue  # already found in dump
        if field in ('null', 'true', 'false', 'var', 'new', 'int', 'void', 'bool', 'string', 'float', 'class', 'this', 'base', 'name', 'guid', 'text', 'path', 'type', 'size', 'data', 'info', 'main'):
            continue
        if any(field in field_index.get(tsn, {}) for tsn in type_index):
            continue  # actually found
        line_no = content[:m.start()].count('\n') + 1
        stale[field].append((rel, line_no))

for field in sorted(stale):
    entries = stale[field]
    files = sorted(set(e[0] for e in entries))
    print(f"{field:8s} {len(entries):5d} {', '.join(files[:3])}")
