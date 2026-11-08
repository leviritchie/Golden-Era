#!/usr/bin/env python3
"""Apply method/field name renames — string literals only. Safe because every
rename entry represents a name that actually changed between builds, and all
references in source appear in quotes."""
import json, os, re, sys
from collections import defaultdict

def load_rename_map(path):
    with open(path) as f:
        return json.load(f)

# Common English words / C# identifiers that should never be renamed
common = frozenset({
    'id','map','me','add','out','get','set','len','sum','min','max','end','key',
    'old','new','try','per','off','own','use','bit','and','not','via','few','was',
    'non','too','two','our','pre','war','zip','obj','ref','sit','img','rim','sig',
    'ran','src','cfg','rig','log','top','row','col','yes','put','all','any','but',
    'can','day','did','far','got','had','has','her','him','his','how','its','let',
    'may','now','see','she','the','van','way','who','why',
    'base','been','blue','bias','best','call','dear','done','down','draw','drop',
    'drug','each','easy','even','fact','fail','fair','fast','fill','find','fine',
    'fire','fish','five','food','form','four','free','full','fund','girl','give',
    'good','grow','half','hand','hard','have','head','hear','help','here','high',
    'hold','home','hope','keep','kind','king','knew','know','lack','last','late',
    'lead','left','life','like','line','list','live','load','long','look','love',
    'made','make','mark','mean','miss','more','most','move','much','must','name',
    'need','next','nine','none','note','once','only','open','over','pace','pack',
    'page','paid','part','pass','past','pick','plan','play','plus','poor','pull',
    'push','race','rang','rare','rate','read','real','rest','rice','rich','ride',
    'ring','rise','risk','road','rock','role','room','rule','safe','said','sale',
    'same','save','seem','self','ship','shop','show','shut','side','sign','size',
    'slow','small','snap','soft','some','sort','spin','spot','star','stay','step',
    'stop','such','sure','take','talk','task','tell','tend','term','test','them',
    'then','they','thin','this','thus','till','time','told','tone','took','tour',
    'tree','true','turn','type','unit','upon','used','vary','very','view','vote',
    'wait','walk','wall','want','warm','warn','wave','weak','wear','week','well',
    'went','were','west','what','when','whom','wide','wife','wild','will','wind',
    'wine','wing','wire','wise','wish','with','wood','word','wore','work','worm',
    'worn','year','your','zero','zone',
    'asc','desc','first','last','count','group','order','select','where','from',
    'join','into','let','by','equals','on',
    # C# keywords
    'abstract','as','base','bool','break','byte','case','catch','char','checked',
    'class','const','continue','decimal','default','delegate','do','double','else',
    'enum','event','explicit','extern','false','finally','fixed','float','for',
    'foreach','goto','if','implicit','in','int','interface','internal','is','lock',
    'long','namespace','new','null','object','operator','out','override','params',
    'private','protected','public','readonly','ref','return','sbyte','sealed',
    'short','sizeof','stackalloc','static','string','struct','switch','this',
    'throw','true','try','typeof','uint','ulong','unchecked','unsafe','ushort',
    'using','var','virtual','void','volatile','while','add','remove','get','set',
    'value','from','where','select','let','orderby','join','equals','nameof',
    'async','await','when','yield','global','partial','dynamic','into','group',
    'by','ascending','descending','on','or','and','not','with','init','record',
    'required','file',
})

def build_renames(rm, key="method_renames"):
    """Build old_name -> new_name map from method_renames or field_renames.
    Only include entries where the old name is unambiguously renamed
    (same old_name maps to same new_name across all types)."""
    src = rm.get(key, {})
    mm = defaultdict(set)
    for qn, nn in src.items():
        if '.' not in qn:
            continue
        m = qn.rsplit('.', 1)[1]
        if len(m) <= 4 and m.islower() and m.isalpha() and m not in ('ctor', 'cctor'):
            mm[m].add(nn)
    
    result = {}
    for m, nn in mm.items():
        if len(nn) == 1:
            new_name = list(nn)[0]
            # Skip common words and very short names
            if m in common or len(m) < 4:
                continue
            # Skip if new name is already the same (shouldn't happen but check)
            if m == new_name:
                continue
            # Skip if new name would be a common word
            if new_name in common:
                continue
            result[m] = new_name
    return result

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("rename_map", nargs='?', default="rename_map.json")
    parser.add_argument("source_dir", nargs='?', default=".")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--backup", action="store_true")
    args = parser.parse_args()

    rm = load_rename_map(args.rename_map)
    method_renames = build_renames(rm, "method_renames")
    field_renames = build_renames(rm, "field_renames")
    all_renames = {**method_renames, **field_renames}
    print(f"Loaded: {len(method_renames)} method + {len(field_renames)} field = {len(all_renames)} total renames")

    if not args.dry_run and args.backup:
        bdir = os.path.join(os.path.dirname(args.source_dir.rstrip('/\\')), '_method_rename_bak')
        if not os.path.exists(bdir):
            os.makedirs(bdir)
            for root, dirs, fns in os.walk(args.source_dir):
                dirs[:] = [d for d in dirs if d not in ('bin','obj','.git','_backup','_method_rename_bak',
                    '_surgical_rename_bak','tools','_decompiled_shipped') and not d.startswith('.')]
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
        dirs[:] = [d for d in dirs if d not in ('bin','obj','.git','_backup','_method_rename_bak',
            '_surgical_rename_bak','tools','_decompiled_shipped') and not d.startswith('.')]
        for fn in fns:
            if not fn.endswith('.cs'): continue
            fp = os.path.join(root, fn)
            rel = os.path.relpath(fp, args.source_dir)
            
            with open(fp, encoding='utf-8', errors='replace') as f:
                text = f.read()
            original = text
            
            # Single-pass replacement: build one regex matching all old names
            # Use a repl function to avoid chaining (bdon -> bdpn, then bdpn -> .ctor)
            if all_renames:
                pattern = '|'.join(re.escape(old) for old in all_renames)
                def repl(m):
                    old = m.group(0)[1:-1]  # strip quotes
                    return '"' + all_renames[old] + '"'
                text = re.sub(r'"(' + pattern + r')"', repl, text)
                
                # Also handle auto-backing-field pattern: "<oldName>k__BackingField"
                # Build a separate regex for backing field patterns
                bf_pattern = '|'.join(re.escape(old) for old in all_renames)
                def bf_repl(m):
                    inner = m.group(1)  # captured between < and >
                    new_inner = all_renames.get(inner, inner)
                    return f'"<{new_inner}>k__BackingField"'
                text = re.sub(r'"<(' + bf_pattern + r')>k__BackingField"', bf_repl, text)
            
            if text != original:
                if args.dry_run:
                    dry_count += 1
                    # Show changes
                    for i, (ol, nl) in enumerate(zip(original.splitlines(), text.splitlines())):
                        if ol != nl:
                            print(f"  {rel}:{i+1}: {ol.strip()}")
                            print(f"         -> {nl.strip()}")
                else:
                    with open(fp, 'w', encoding='utf-8') as f:
                        f.write(text)
                    changed += 1
    
    if args.dry_run:
        print(f"\n{dry_count} files would change")
    else:
        if changed:
            print(f"\n{changed} files updated")
        else:
            print("No files changed")

if __name__ == '__main__':
    main()
