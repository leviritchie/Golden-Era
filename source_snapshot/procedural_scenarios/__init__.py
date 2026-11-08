"""Public package path for the procedural scenario framework."""

from pathlib import Path

_IMPLEMENTATION = (
    Path(__file__).resolve().parents[1]
    / "experiments"
    / "campaign_port_poc"
    / "procedural_scenarios"
)
if not _IMPLEMENTATION.is_dir():
    raise ImportError(f"procedural scenario implementation is missing: {_IMPLEMENTATION}")

__path__ = [str(_IMPLEMENTATION)]