"""Direct Gemini API 2K orthographic sheet painter for Full-PBR unit retexturing."""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import threading
import time
from typing import Callable

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from project_unit import sheet_views  # noqa: E402
from save_and_check_sheet import save_and_check  # noqa: E402

DEFAULT_MODEL = "gemini-nano-banana-2.1"
DEFAULT_IMAGE_SIZE = "2K"
DEFAULT_ASPECT_RATIO = "1:1"
DEPRECATED_PREFIXES = ("gemini-2.5-", "gemini-2.0-", "gemini-1.5-")

MODEL_PRICING: dict[str, dict[str, object]] = {
    "gemini-nano-banana-2.1": {
        "input_per_1m": 1.50,
        "text_output_per_1m": 7.50,
        "image_usd": {"1K": 0.0336, "2K": 0.0504, "4K": 0.113},
    },
    "gemini-3.1-flash-lite-image": {
        "input_per_1m": 0.25,
        "text_output_per_1m": 1.50,
        "image_usd": {"1K": 0.0336},
    },
    "gemini-3-pro-image": {
        "input_per_1m": 2.00,
        "text_output_per_1m": 12.00,
        "image_usd": {"1K": 0.134, "2K": 0.134, "4K": 0.240},
    },
}

_LOG_LOCK = threading.Lock()
_ENV_SUBKEYS = (
    ("HKCU", "Environment"),
    ("HKLM", r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
)


def mask_api_key(key: str) -> str:
    """Return a masked key preview without revealing secret characters."""
    if len(key) <= 4:
        return "***"
    if len(key) <= 10:
        return f"{key[:2]}...{key[-2:]}"
    return f"{key[:6]}...{key[-4:]}"


def _default_winreg_reader(hive_name: str, subkey: str, name: str) -> str | None:
    if sys.platform != "win32":
        return None
    import winreg

    hives = {
        "HKCU": winreg.HKEY_CURRENT_USER,
        "HKLM": winreg.HKEY_LOCAL_MACHINE,
    }
    hive = hives.get(hive_name)
    if hive is None:
        return None
    try:
        with winreg.OpenKey(hive, subkey) as reg_key:
            val, _ = winreg.QueryValueEx(reg_key, name)
            return str(val) if val is not None else None
    except (FileNotFoundError, OSError):
        return None


def resolve_gemini_api_key(
    source: str = "auto",
    _winreg_reader: Callable[[str, str, str], str | None] | None = None,
) -> str:
    """Resolve GEMINI_API_KEY, preferring live Windows registry over stale process env."""
    if source not in ("auto", "registry", "env"):
        raise ValueError(f"unsupported env-source: {source}")

    reader = _winreg_reader if _winreg_reader is not None else _default_winreg_reader
    if source in ("auto", "registry"):
        for hive_name, subkey in _ENV_SUBKEYS:
            raw = reader(hive_name, subkey, "GEMINI_API_KEY")
            if raw:
                expanded = os.path.expandvars(raw).strip()
                if expanded:
                    return expanded
        if source == "registry":
            raise RuntimeError("GEMINI_API_KEY not found in HKCU or HKLM Environment registry")

    env_val = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if env_val:
        return env_val
    raise RuntimeError(f"GEMINI_API_KEY missing or empty (source={source})")


def _validate_model_size(model: str, image_size: str) -> dict[str, object]:
    if any(model.startswith(pfx) for pfx in DEPRECATED_PREFIXES):
        raise ValueError(f"deprecated Gemini image model rejected: {model}")
    spec = MODEL_PRICING.get(model)
    if spec is None:
        supported = ", ".join(sorted(MODEL_PRICING))
        raise ValueError(f"unsupported image model '{model}' (supported: {supported})")
    img_table = spec["image_usd"]
    assert isinstance(img_table, dict)
    if image_size not in img_table:
        supported_sizes = ", ".join(sorted(img_table))
        raise ValueError(f"model '{model}' does not support image_size='{image_size}' (supported: {supported_sizes})")
    return spec


def estimate_cost_usd(
    model: str,
    image_size: str,
    input_tokens: int = 0,
    text_output_tokens: int = 0,
) -> float:
    """Estimate USD cost using official Gemini Developer API token/resolution rates."""
    spec = _validate_model_size(model, image_size)
    img_table = spec["image_usd"]
    assert isinstance(img_table, dict)
    img_usd = float(img_table[image_size])
    in_usd = (max(0, int(input_tokens)) / 1_000_000.0) * float(spec["input_per_1m"])
    out_usd = (max(0, int(text_output_tokens)) / 1_000_000.0) * float(spec["text_output_per_1m"])
    return round(img_usd + in_usd + out_usd, 6)


def _mime_for_path(path: Path) -> str:
    suf = path.suffix.lower()
    if suf in (".jpg", ".jpeg"):
        return "image/jpeg"
    if suf == ".webp":
        return "image/webp"
    return "image/png"


def build_request_body(
    prompt: str,
    ref_paths: list[Path],
    model: str = DEFAULT_MODEL,
    image_size: str = DEFAULT_IMAGE_SIZE,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
) -> dict[str, object]:
    """Build kwargs dict for google.genai client.interactions.create(...)."""
    _validate_model_size(model, image_size)
    if not prompt.strip():
        raise ValueError("prompt must be non-empty")

    input_blocks: list[dict[str, object]] = [{"type": "text", "text": prompt}]
    for rp in ref_paths:
        p = Path(rp)
        if not p.is_file():
            raise FileNotFoundError(f"missing reference image: {p}")
        data_b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        input_blocks.append(
            {
                "type": "image",
                "data": data_b64,
                "mime_type": _mime_for_path(p),
            }
        )

    return {
        "model": model,
        "input": input_blocks,
        "response_format": {
            "type": "image",
            "aspect_ratio": aspect_ratio,
            "image_size": image_size,
        },
        "store": False,
    }


def default_ref_paths(unit_dir: Path, sheet: str) -> list[Path]:
    """Return ordered reference image paths for primary or secondary sheet generation."""
    if sheet == "primary":
        return [
            unit_dir / "views/guide_sheet_primary.png",
            unit_dir / "ref/def_ref_2x2.png",
        ]
    if sheet == "secondary":
        return [
            unit_dir / "views/guide_sheet_secondary.png",
            unit_dir / "out/repaint_primary.png",
            unit_dir / "ref/def_ref_2x2.png",
        ]
    if sheet == "tertiary":  # opt-in low views (render_guides_unit.py --tertiary)
        return [
            unit_dir / "views/guide_sheet_tertiary.png",
            unit_dir / "out/repaint_primary.png",
            unit_dir / "out/repaint_secondary.png",
            unit_dir / "ref/def_ref_2x2.png",
        ]
    raise ValueError(f"invalid sheet '{sheet}' (expected 'primary', 'secondary' or 'tertiary')")


def _http_status(exc: Exception) -> int | None:
    for attr in ("status_code", "code"):
        val = getattr(exc, attr, None)
        if isinstance(val, int):
            return val
    resp = getattr(exc, "response", None)
    if resp is not None:
        sc = getattr(resp, "status_code", None)
        if isinstance(sc, int):
            return sc
    return None


def _is_transient_error(exc: Exception) -> bool:
    msg = str(exc).upper()
    non_retry_tokens = (
        "400",
        "401",
        "402",
        "403",
        "404",
        "429",
        "RESOURCE_EXHAUSTED",
        "QUOTA",
        "PERMISSION",
        "BILLING",
        "INVALID_ARGUMENT",
        "UNAUTHENTICATED",
    )
    status = _http_status(exc)
    if status in (400, 401, 402, 403, 404, 429):
        return False
    if any(tok in msg for tok in non_retry_tokens):
        return False
    if status in (500, 502, 503, 504):
        return True
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    try:
        import httpx

        if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
            return True
    except Exception:
        pass
    return any(tok in msg for tok in ("500", "502", "503", "504", "TIMED OUT", "TIMEOUT", "CONNECTION"))


def _decode_image_data(raw_data: object) -> bytes:
    if isinstance(raw_data, (bytes, bytearray)):
        return bytes(raw_data)
    if isinstance(raw_data, str) and raw_data:
        return base64.b64decode(raw_data)
    raise RuntimeError("empty image payload")


def _extract_image_bytes(interaction: object) -> bytes:
    out_img = getattr(interaction, "output_image", None)
    if out_img is not None:
        data = getattr(out_img, "data", None)
        if data:
            return _decode_image_data(data)

    for step in getattr(interaction, "steps", None) or ():
        if getattr(step, "type", None) == "image" and getattr(step, "data", None):
            return _decode_image_data(step.data)
        for item in getattr(step, "content", None) or ():
            if getattr(item, "type", None) == "image" and getattr(item, "data", None):
                return _decode_image_data(item.data)
    raise RuntimeError("Gemini interaction returned no output image")


def _extract_usage_tokens(interaction: object) -> tuple[int, int]:
    usage = getattr(interaction, "usage", None)
    if usage is None:
        return 0, 0
    in_toks = int(getattr(usage, "total_input_tokens", 0) or 0)
    thought_toks = int(getattr(usage, "total_thought_tokens", 0) or 0)
    text_toks = 0
    for entry in getattr(usage, "output_tokens_by_modality", None) or ():
        mod = getattr(entry, "modality", None)
        if mod is None and isinstance(entry, dict):
            mod = entry.get("modality")
        tok = getattr(entry, "tokens", None)
        if tok is None and isinstance(entry, dict):
            tok = entry.get("tokens")
        if str(mod or "").lower() == "text" and tok is not None:
            text_toks += int(tok)
    return in_toks, text_toks + thought_toks


def _append_cost_log(work_dir: Path, record: dict[str, object]) -> None:
    log_path = work_dir / "renders/api_cost_log.jsonl"
    with _LOG_LOCK:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")


def _print_locked(msg: str) -> None:
    with _LOG_LOCK:
        print(msg, flush=True)


def _call_with_transient_retry(client: object, req: dict[str, object], max_transient_retries: int = 2) -> object:
    backoffs = (5.0, 15.0)
    attempt = 0
    while True:
        try:
            return client.interactions.create(**req)
        except Exception as exc:
            if attempt >= max_transient_retries or not _is_transient_error(exc):
                raise
            delay = backoffs[min(attempt, len(backoffs) - 1)]
            attempt += 1
            time.sleep(delay)


def _format_iou_correction(unit: str, sheet: str, worst: float, reports: dict[str, dict]) -> str:
    vnames = sheet_views(sheet)
    parts = [f"{vn}={reports[vn]['iouPost']:.3f}" for vn in vnames if vn in reports]
    return (
        "\n\nSILHOUETTE ALIGNMENT CORRECTION REQUIRED: Previous generation drifted from Image 1 silhouette "
        f"(worst IoU={worst:.3f} < threshold; panels: {', '.join(parts)}). Keep EVERY bone, limb, wing, tail, "
        "hair strand, weapon, and silhouette contour at the EXACT pixel position and scale of Image 1 across all 4 "
        "panels on a uniform #7F7F7F flat background. Do NOT crop, zoom, shift pose, or add extra props."
    )


_STYLE_GUARDRAIL = (
    "\n\nSTYLE REQUIREMENT: Render smooth, crisp, high-resolution 2K hand-painted PBR fantasy game art "
    "with continuous brushwork and fine material detail. Use the HoMM3 DEF sprite reference strictly for "
    "color palette, silhouette identity, and costume details — NEVER output pixel art, mosaic blocks, "
    "sprite dithering, or stair-stepped low-res pixels."
)


def _with_style_guardrail(prompt: str) -> str:
    return prompt if "pixel art" in prompt.lower() else prompt + _STYLE_GUARDRAIL


def paint_unit_sheet(
    unit: str,
    work_dir: Path,
    sheet: str,
    prompt: str,
    model: str = DEFAULT_MODEL,
    image_size: str = DEFAULT_IMAGE_SIZE,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
    min_iou: float = 0.85,
    max_iou_attempts: int = 2,
    env_source: str = "auto",
    ref_paths: list[Path] | None = None,
) -> dict[str, object]:
    """Generate a 2x2 repainted sheet via Gemini API, check panel IoU, and log cost."""
    from google import genai

    _validate_model_size(model, image_size)
    key = resolve_gemini_api_key(source=env_source)
    client = genai.Client(api_key=key)

    unit_dir = work_dir / unit
    out_dir = unit_dir / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / f"raw_api_{sheet}.png"
    refs = list(ref_paths) if ref_paths else default_ref_paths(unit_dir, sheet)

    cur_prompt = _with_style_guardrail(prompt)
    total_cost = 0.0
    last_worst = 0.0
    last_raw_size = (0, 0)
    last_reports: dict[str, dict] = {}

    for attempt in range(1, max_iou_attempts + 1):
        t0 = time.perf_counter()
        req = build_request_body(
            cur_prompt,
            refs,
            model=model,
            image_size=image_size,
            aspect_ratio=aspect_ratio,
        )
        interaction = _call_with_transient_retry(client, req, max_transient_retries=2)
        img_bytes = _extract_image_bytes(interaction)
        raw_path.write_bytes(img_bytes)
        with Image.open(raw_path) as im:
            last_raw_size = im.size

        with _LOG_LOCK:
            ok, worst, reports = save_and_check(unit, work_dir, sheet, raw_path, min_iou=min_iou)
        last_worst = float(worst)
        last_reports = reports

        in_toks, text_toks = _extract_usage_tokens(interaction)
        call_cost = estimate_cost_usd(model, image_size, input_tokens=in_toks, text_output_tokens=text_toks)
        total_cost += call_cost
        elapsed = time.perf_counter() - t0

        rec: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "unit": unit,
            "sheet": sheet,
            "attempt": attempt,
            "model": model,
            "imageSize": image_size,
            "rawResolution": list(last_raw_size),
            "ok": bool(ok),
            "worstIou": round(last_worst, 4),
            "inputTokens": in_toks,
            "textOutputTokens": text_toks,
            "estCostUsd": round(call_cost, 6),
            "elapsedSec": round(elapsed, 2),
        }
        _append_cost_log(work_dir, rec)
        _print_locked(
            f"[paint_api] {unit} [{sheet}] attempt={attempt}/{max_iou_attempts} "
            f"raw={last_raw_size[0]}x{last_raw_size[1]} worstIoU={last_worst:.3f} ok={ok} "
            f"cost=${call_cost:.4f} ({elapsed:.1f}s)"
        )

        if ok:
            return {
                "unit": unit,
                "sheet": sheet,
                "attempt": attempt,
                "ok": True,
                "rawSize": list(last_raw_size),
                "worstIou": last_worst,
                "totalCostUsd": round(total_cost, 6),
                "reports": last_reports,
            }
        # IoU retry: keep the anti-pixel-art guardrail and append the correction note.
        cur_prompt = _with_style_guardrail(prompt) + _format_iou_correction(unit, sheet, last_worst, reports)

    raise RuntimeError(
        f"{unit} [{sheet}] failed IoU gate after {max_iou_attempts} attempts (worst={last_worst:.3f} < {min_iou:.2f})"
    )


def paint_manifest(
    work_dir: Path,
    manifest_path: Path,
    sheet: str,
    units_filter: list[str] | None = None,
    jobs: int = 4,
    model: str = DEFAULT_MODEL,
    image_size: str = DEFAULT_IMAGE_SIZE,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
    min_iou: float = 0.85,
    max_iou_attempts: int = 2,
    env_source: str = "auto",
) -> list[dict[str, object]]:
    """Paint one sheet across a prompt manifest JSON concurrently."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not manifest:
        raise ValueError(f"manifest must be a non-empty JSON object: {manifest_path}")

    target_units = units_filter if units_filter else list(manifest.keys())
    for u in target_units:
        if u not in manifest or not isinstance(manifest[u], dict) or not manifest[u].get(sheet):
            raise ValueError(f"manifest {manifest_path} missing '{sheet}' prompt for unit '{u}'")

    results: list[dict[str, object]] = []
    errors: list[tuple[str, Exception]] = []
    workers = max(1, min(int(jobs), len(target_units)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {
            pool.submit(
                paint_unit_sheet,
                u,
                work_dir,
                sheet,
                str(manifest[u][sheet]),
                model=model,
                image_size=image_size,
                aspect_ratio=aspect_ratio,
                min_iou=min_iou,
                max_iou_attempts=max_iou_attempts,
                env_source=env_source,
            ): u
            for u in target_units
        }
        for fut in as_completed(futs):
            u = futs[fut]
            try:
                results.append(fut.result())
            except Exception as exc:
                errors.append((u, exc))
                _print_locked(f"[paint_api ERROR] {u} [{sheet}]: {exc}")

    batch_cost = sum(float(r["totalCostUsd"]) for r in results)
    _print_locked(
        f"[paint_api SUMMARY] sheet={sheet} ok={len(results)}/{len(target_units)} "
        f"errors={len(errors)} batchCost=${batch_cost:.4f}"
    )
    if errors:
        detail = "; ".join(f"{u}: {e}" for u, e in errors)
        raise RuntimeError(f"paint_manifest failed for {len(errors)} unit(s): {detail}")
    return results


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--work-dir", required=True, type=Path)
    ap.add_argument("--sheet", required=True, choices=["primary", "secondary", "tertiary"])
    ap.add_argument("--unit", default="", help="Single unit mode")
    ap.add_argument("--prompt", default="", help="Inline prompt for single-unit mode")
    ap.add_argument("--prompt-file", type=Path, default=None, help="Prompt file for single-unit mode")
    ap.add_argument("--manifest", type=Path, default=None, help="JSON map: {unit: {primary: ..., secondary: ...}}")
    ap.add_argument("--units", default="", help="Optional comma-separated subset for --manifest")
    ap.add_argument("--jobs", type=int, default=4, help="Parallel threads for --manifest")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--image-size", default=DEFAULT_IMAGE_SIZE, choices=["512", "1K", "2K", "4K"])
    ap.add_argument("--aspect-ratio", default=DEFAULT_ASPECT_RATIO)
    ap.add_argument("--min-iou", type=float, default=0.85)
    ap.add_argument("--max-iou-attempts", type=int, default=2)
    ap.add_argument("--env-source", default="auto", choices=["auto", "registry", "env"])
    ap.add_argument("--ref", action="append", type=Path, default=None, help="Optional explicit reference image(s)")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    work_dir = args.work_dir.resolve()
    try:
        if args.manifest is not None:
            subset = [x.strip() for x in args.units.split(",") if x.strip()] if args.units else None
            paint_manifest(
                work_dir=work_dir,
                manifest_path=args.manifest.resolve(),
                sheet=args.sheet,
                units_filter=subset,
                jobs=args.jobs,
                model=args.model,
                image_size=args.image_size,
                aspect_ratio=args.aspect_ratio,
                min_iou=args.min_iou,
                max_iou_attempts=args.max_iou_attempts,
                env_source=args.env_source,
            )
            return 0

        if not args.unit:
            raise ValueError("must supply either --manifest or --unit")
        prompt_text = args.prompt
        if args.prompt_file is not None:
            prompt_text = args.prompt_file.read_text(encoding="utf-8")
        paint_unit_sheet(
            unit=args.unit,
            work_dir=work_dir,
            sheet=args.sheet,
            prompt=prompt_text,
            model=args.model,
            image_size=args.image_size,
            aspect_ratio=args.aspect_ratio,
            min_iou=args.min_iou,
            max_iou_attempts=args.max_iou_attempts,
            env_source=args.env_source,
            ref_paths=args.ref,
        )
        return 0
    except Exception as exc:
        print(f"FAIL paint_api: {exc}", file=sys.stderr)
        return 2 if "IoU gate" in str(exc) else 1


if __name__ == "__main__":
    raise SystemExit(main())
