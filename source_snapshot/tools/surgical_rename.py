#!/usr/bin/env python3
"""surgical_rename.py — context-aware rename, type-level only (no string literals)."""

import json, os, re, sys

def load_rename_map(path):
    with open(path) as f:
        return json.load(f)

def is_obfuscated(name):
    return 2 <= len(name) <= 4 and name.islower() and name.isalpha()

def build_lookups(rm):
    tr = rm.get("type_renames", {})
    mr = rm.get("method_renames", {})
    sn_renames = {k.split('.')[-1]: v.split('.')[-1] for k, v in tr.items()}
    nameof_map = {}
    for qn, nn in mr.items():
        if '.' not in qn: continue
        t = qn.rsplit('.', 1)[0].split('.')[-1]
        m = qn.rsplit('.', 1)[1]
        nameof_map[(t, m)] = nn
    type_alt = '|'.join(re.escape(s) for s in sn_renames) if sn_renames else ''
    return sn_renames, nameof_map, type_alt

def process_file(fp, rm, lookups, dry_run=False):
    sn_renames, nameof_map, type_alt = lookups
    with open(fp, encoding='utf-8', errors='replace') as f:
        text = f.read()
    original = text

    if not re.search(r'\b[a-z]{2,4}\b', text):
        return False

    # typeof(X) -> typeof(newX)
    def typeof_repl(m):
        return "typeof(" + sn_renames.get(m.group(1), m.group(1)) + ")"
    text = re.sub(r'typeof\s*\(\s*(\w+)\s*\)', typeof_repl, text)

    # global::X -> global::newX
    if type_alt:
        def global_repl(m):
            return "global::" + sn_renames.get(m.group(1), m.group(1))
        text = re.sub(r'global::(' + type_alt + r')\b', global_repl, text)

    # nameof(X.Y) -> nameof(newX.newY) — always update the type part
    def nameof_repl(m):
        ts = m.group(1); me = m.group(2)
        new_type = sn_renames.get(ts, ts)
        new_method = nameof_map.get((ts, me), me)
        if new_type != ts or new_method != me:
            return "nameof(" + new_type + "." + new_method + ")"
        return m.group(0)
    text = re.sub(r'nameof\s*\(\s*(?:global::)?(\w+)\.(\w+)\s*\)', nameof_repl, text)

    # new X( -> new newX(
    if type_alt:
        def new_repl(m):
            return "new " + sn_renames.get(m.group(1), m.group(1)) + "("
        text = re.sub(r'\bnew\s+(' + type_alt + r')\s*\(', new_repl, text)

    if dry_run:
        if text != original:
            for i, (ol, nl) in enumerate(zip(original.splitlines(), text.splitlines())):
                if ol != nl:
                    print(f"  L{i+1}: {ol.strip()}")
                    print(f"     -> {nl.strip()}")
            return True
        return False

    if text != original:
        with open(fp, 'w', encoding='utf-8') as f:
            f.write(text)
        return True
    return False

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("rename_map", nargs='?', default="rename_map.json")
    parser.add_argument("source_dir", nargs='?', default=".")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--backup", action="store_true")
    args = parser.parse_args()

    rm = load_rename_map(args.rename_map)
    lookups = build_lookups(rm)
    print(f"Loaded: {len(lookups[0])} type renames, {len(lookups[1])} nameof maps")
    print("Type-level only (typeof, global::, nameof, new). String literals skipped.")

    if not args.dry_run and args.backup:
        bdir = os.path.join(os.path.dirname(args.source_dir.rstrip('/\\')), '_surgical_rename_bak')
        if not os.path.exists(bdir):
            os.makedirs(bdir)
            for root, dirs, fns in os.walk(args.source_dir):
                dirs[:] = [d for d in dirs if d not in ('bin','obj','.git','_backup','_surgical_rename_bak','tools','_decompiled_shipped') and not d.startswith('.')]
                for fn in fns:
                    if not fn.endswith('.cs'): continue
                    src = os.path.join(root, fn)
                    dst = os.path.join(bdir, os.path.relpath(src, args.source_dir))
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    with open(src, 'rb') as sf, open(dst, 'wb') as df:
                        df.write(sf.read())
            print(f"Backup: {bdir}")

    changed = 0
    dry_count = 0
    for root, dirs, fns in os.walk(args.source_dir):
        dirs[:] = [d for d in dirs if d not in ('bin','obj','.git','_backup','_surgical_rename_bak','tools','_decompiled_shipped') and not d.startswith('.')]
        for fn in fns:
            if not fn.endswith('.cs'): continue
            fp = os.path.join(root, fn)
            rel = os.path.relpath(fp, args.source_dir)
            if args.dry_run:
                if process_file(fp, rm, lookups, dry_run=True):
                    dry_count += 1
                    print(f"\n{rel}:")
            else:
                if process_file(fp, rm, lookups):
                    changed += 1
                    print(f"  {rel}")

    if args.dry_run:
        print(f"\n{dry_count} files would change")
    else:
        print(f"\n{changed} files updated")

if __name__ == '__main__':
    main()
