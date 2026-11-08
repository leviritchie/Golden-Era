#!/usr/bin/env python3
"""Make a Unity editor builder queue-compatible (docs/unity_queue_runner.md, "Making a builder queue-compatible").

    python tools/unity_queue/apply_shim.py <file.cs> <ClassName> [<file.cs> <ClassName> ...]

Inserts the UnityQueueArgs()/UnityQueueExit() pair as the first members of the class, then replaces every
Environment.GetCommandLineArgs() with UnityQueueArgs() and every EditorApplication.Exit( with UnityQueueExit( in the
file. Keeps the file's BOM, line endings and indentation. Refuses a file that already has the shim, or that has no
`using System;` / `using UnityEditor;` (the shim needs both). Review each UnityQueueExit call afterwards: under the
dispatcher it records the code and *returns*, so it must end its path.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SHIM = (
    "{i}// Unity queue shim (tools/unity_queue, docs/unity_queue_runner.md): under UnityQueueDispatcher a job reads its\n"
    "{i}// own arguments and records its exit code instead of quitting the shared batch; a direct launch reads the command\n"
    "{i}// line and exits as before. The dispatcher refuses a class without this pair.\n"
    "{i}static string[] UnityQueueArgs() => AppDomain.CurrentDomain.GetData(\"UnityQueue.JobArgs\") as string[] ?? Environment.GetCommandLineArgs();\n"
    "{i}static void UnityQueueExit(int code)\n"
    "{i}{{\n"
    "{i}{s}if (AppDomain.CurrentDomain.GetData(\"UnityQueue.JobArgs\") == null) {{ EditorApplication.Exit(code); return; }}\n"
    "{i}{s}if (!(AppDomain.CurrentDomain.GetData(\"UnityQueue.ExitCode\") is int prev && prev != 0)) AppDomain.CurrentDomain.SetData(\"UnityQueue.ExitCode\", code);\n"
    "{i}}}\n\n"
)


def apply(path: Path, cls: str) -> dict:
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    t = raw[3:].decode("utf-8") if bom else raw.decode("utf-8")
    crlf = "\r\n" in t
    t = t.replace("\r\n", "\n")
    if "UnityQueueArgs" in t:
        raise SystemExit(f"{path}: already has the shim")
    if not re.search(r"(?m)^\s*using System;", t) or not re.search(r"(?m)^\s*using UnityEditor;", t):
        raise SystemExit(f"{path}: needs `using System;` and `using UnityEditor;` for the shim")
    m = re.search(rf"(?m)^([ \t]*)(?:public |internal |private )?(?:static )?(?:partial )?class {re.escape(cls)}\b[^\n{{]*", t)
    if not m:
        raise SystemExit(f"{path}: class {cls} not found")
    ind = m.group(1)
    step = "\t" if ind.startswith("\t") or (not ind and "\n\t" in t) else "    "
    brace = t.index("{", m.start())
    nl = t.index("\n", brace) + 1
    args = t.count("Environment.GetCommandLineArgs()")
    exits = t.count("EditorApplication.Exit(")
    t = t.replace("Environment.GetCommandLineArgs()", "UnityQueueArgs()").replace("EditorApplication.Exit(", "UnityQueueExit(")
    t = t[:nl] + SHIM.format(i=ind + step, s=step) + t[nl:]
    if crlf:
        t = t.replace("\n", "\r\n")
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + t.encode("utf-8"))
    return {"file": str(path), "class": cls, "args": args, "exits": exits}


def main(argv: list[str]) -> int:
    if not argv or len(argv) % 2:
        print(__doc__)
        return 2
    for f, c in zip(argv[::2], argv[1::2]):
        print(apply(Path(f), c))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
