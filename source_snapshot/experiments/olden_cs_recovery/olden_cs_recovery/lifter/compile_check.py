"""Compile-check gate for recovered skeletons (never promotion)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from olden_cs_recovery.lifter.emit_csharp import (
    CSPROJ_NAME,
    RECOVERED_ROOT,
    collect_referenced_simple_types,
    ensure_project_scaffold,
    write_external_stubs,
)


class CompileCheckError(RuntimeError):
    pass


def compile_check(*, defined_types: set[str]) -> dict:
    """Rebuild stub externals from emitted sources and run dotnet build. Fail closed."""
    ensure_project_scaffold()
    cs_files = sorted(RECOVERED_ROOT.rglob("*.cs"))
    if not cs_files:
        raise CompileCheckError(f"No C# sources under {RECOVERED_ROOT}")

    referenced: set[str] = set()
    for path in cs_files:
        if path.name == "ExternalStubs.cs":
            continue
        referenced |= collect_referenced_simple_types(path.read_text(encoding="utf-8"))

    write_external_stubs(referenced, known_defined=defined_types)

    csproj = RECOVERED_ROOT / CSPROJ_NAME
    dotnet = shutil.which("dotnet")
    if not dotnet:
        raise CompileCheckError("dotnet SDK not found on PATH; compile-check gate cannot run")

    proc = subprocess.run(
        [dotnet, "build", str(csproj), "-c", "Release", "--nologo"],
        cwd=str(RECOVERED_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    result = {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "csproj": str(csproj),
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
    if proc.returncode != 0:
        raise CompileCheckError(
            "dotnet build failed for recovered skeletons (compile-check gate).\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return result
