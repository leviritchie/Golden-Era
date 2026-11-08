#!/usr/bin/env python3
"""Inject HoMM3 dialogue portraits into an Olden Era install's Resources.

Adds Texture2D + Sprite objects to resources.assets and registers
``icons/dialogue/<name>`` in globalgamemanagers ResourceManager so
``Resources.Load`` resolves the key natively.

New texture pixels are embedded in resources.assets (resources.assets.resS
is not modified).

--game-root is required and has no default; --dry-run never writes to it.

Usage:
  python tools/inject_homm3_dialog_portrait_resources.py --game-root <install> --dry-run
  python tools/inject_homm3_dialog_portrait_resources.py --game-root <install> --install
  python tools/inject_homm3_dialog_portrait_resources.py --game-root <install> --from-inventory --dry-run
  python tools/inject_homm3_dialog_portrait_resources.py --game-root <install> --from-inventory --install
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import time
from pathlib import Path

import UnityPy
from PIL import Image
from UnityPy.classes.generated import AABB, PPtr, Rectf, SubMesh, Vector2f, Vector3f, Vector4f
from UnityPy.files.ObjectReader import ObjectReader

REPO = Path(__file__).resolve().parents[1]
PORTRAIT_DIR = (
    REPO
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_hero_portraits_upscaled"
)
DEFAULT_PNG = PORTRAIT_DIR / "homm3_stronghold_hero_2.png"
DEFAULT_NAME = "dialogue_hero_homm3_stronghold_2"
INVENTORY_ICONS = REPO / "artifacts" / "dialog_portrait_inventory" / "required_homm3_icons.json"
DEFAULT_SIZE = 1024
# Donors are resolved per build by (class, name, rect size), never by path id: path ids are
# assigned per build. Golden Era resolves to tex 6493 / sprite 20016 (the ids this tool
# hard-coded until 2026-09-29), while build 25061458 resolves to 6552 / 20134. On 25061458,
# path id 6493 is a different object, so the old constants would have cloned the wrong
# asset there. The sprite name has two hits in both builds (64x64 and 512x512); the
# 64x64 one is the historical donor.
TEX_DONOR = ("Texture2D", "dialogue_hero_6_gunnar", 1024, 1024)
SPR_DONOR = ("Sprite", "chain_link_artifact", 64, 64)
# The vanilla ResourceManager entry whose PPtr file index is reused for injected keys.
RM_SAMPLE_KEY = "icons/dialogue/dialogue_hero_6_gunnar"


def resolve_donors(sf) -> tuple[int, int]:
    """Return (texture path id, sprite path id). Fails closed unless each is unique."""
    found: dict[str, list[int]] = {"Texture2D": [], "Sprite": []}
    for pid, obj in sf.objects.items():
        cls = obj.type.name
        if cls == TEX_DONOR[0] and obj.peek_name() == TEX_DONOR[1]:
            d = obj.read()
            if (d.m_Width, d.m_Height) == TEX_DONOR[2:]:
                found[cls].append(pid)
        elif cls == SPR_DONOR[0] and obj.peek_name() == SPR_DONOR[1]:
            d = obj.read()
            if (int(d.m_Rect.width), int(d.m_Rect.height)) == SPR_DONOR[2:]:
                found[cls].append(pid)
    for spec in (TEX_DONOR, SPR_DONOR):
        if len(found[spec[0]]) != 1:
            raise SystemExit(f"FAIL donor {spec} resolved to {found[spec[0]]}; want exactly one")
    return found["Texture2D"][0], found["Sprite"][0]


def _sha256(path: Path, limit: int | None = 1024 * 1024) -> str:
    """limit=None: full-file sha256 (hex). Otherwise a 16-char prefix fingerprint."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        if limit is None:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
            return h.hexdigest()
        h.update(f.read(limit))
        h.update(str(path.stat().st_size).encode())
    return h.hexdigest()[:16]


def _clone_reader(donor: ObjectReader, new_id: int) -> ObjectReader:
    return ObjectReader(
        assets_file=donor.assets_file,
        reader=donor.reader,
        path_id=new_id,
        type_id=donor.type_id,
        serialized_type=donor.serialized_type,
        class_id=donor.class_id,
        type=donor.type,
        byte_start=donor.byte_start,
        byte_size=donor.byte_size,
        is_destroyed=donor.is_destroyed,
        is_stripped=donor.is_stripped,
        data=donor.get_raw_data(),
    )


def _serialized_file(env: UnityPy.Environment):
    return next(f for f in env.files.values() if hasattr(f, "objects") and len(f.objects) > 1000)


def dialog_icon_to_png(asset_name: str) -> Path:
    """dialogue_hero_homm3_stronghold_2 -> homm3_stronghold_hero_2.png"""
    prefix = "dialogue_hero_homm3_"
    if not asset_name.startswith(prefix):
        raise ValueError(f"unsupported dialog asset name: {asset_name!r}")
    rest = asset_name[len(prefix) :]  # stronghold_2
    faction, _, num = rest.rpartition("_")
    if not faction or not num:
        raise ValueError(f"cannot parse dialog asset name: {asset_name!r}")
    return PORTRAIT_DIR / f"homm3_{faction}_hero_{num}.png"


def dialog_key_to_asset_name(key: str) -> str:
    key = key.replace("\\", "/")
    prefix = "icons/dialogue/"
    if not key.startswith(prefix):
        raise ValueError(f"expected icons/dialogue/* key; got {key!r}")
    return key[len(prefix) :]


def _inject_one(
    sf,
    *,
    asset_name: str,
    png: Path,
    size: int,
    next_id: int,
    donors: tuple[int, int],
) -> tuple[int, int, int]:
    """Inject one Texture2D+Sprite. Returns (tex_id, spr_id, next_id)."""
    drop = []
    for pid, obj in sf.objects.items():
        if obj.type.name not in ("Texture2D", "Sprite"):
            continue
        try:
            if getattr(obj.read(), "m_Name", None) == asset_name:
                drop.append(pid)
        except Exception:
            continue
    for pid in drop:
        del sf.objects[pid]

    new_tex_id = next_id
    new_spr_id = next_id + 1
    next_id = next_id + 2

    tex_reader = _clone_reader(sf.objects[donors[0]], new_tex_id)
    sf.objects[new_tex_id] = tex_reader
    tex = tex_reader.read()
    tex.set_object_reader(tex_reader)
    img = Image.open(png).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
    tex.m_Name = asset_name
    tex.set_image(img, target_format=tex.m_TextureFormat, mipmap_count=1)
    tex.save()

    spr_reader = _clone_reader(sf.objects[donors[1]], new_spr_id)
    sf.objects[new_spr_id] = spr_reader
    spr = spr_reader.read()
    spr.set_object_reader(spr_reader)
    spr.m_Name = asset_name
    spr.m_Rect = Rectf(x=0.0, y=0.0, width=float(size), height=float(size))
    spr.m_PixelsToUnits = 100.0
    spr.m_Pivot = Vector2f(0.5, 0.5)
    half = size / 100.0 / 2.0
    positions = [(-half, half, 0.0), (half, -half, 0.0), (half, half, 0.0), (-half, -half, 0.0)]
    raw = bytearray()
    for x, y, z in positions:
        raw += struct.pack("<fff", x, y, z)
    for _ in range(4):
        raw += struct.pack("<ff", 0.0, 0.0)
    spr.m_RD.m_VertexData.m_DataSize = bytes(raw)
    spr.m_RD.m_VertexData.m_VertexCount = 4
    spr.m_RD.m_IndexBuffer = bytes([3, 0, 0, 0, 1, 0, 2, 0, 1, 0, 0, 0])
    spr.m_RD.m_SubMeshes = [
        SubMesh(
            firstByte=0,
            firstVertex=0,
            indexCount=6,
            vertexCount=4,
            baseVertex=0,
            localAABB=AABB(m_Center=Vector3f(0, 0, 0), m_Extent=Vector3f(0, 0, 0)),
            topology=0,
            isTriStrip=None,
            triangleCount=None,
        )
    ]
    spr.m_RD.textureRect = Rectf(x=0.0, y=0.0, width=float(size), height=float(size))
    spr.m_RD.textureRectOffset = Vector2f(0.0, 0.0)
    spr.m_RD.atlasRectOffset = Vector2f(-1.0, -1.0)
    spr.m_RD.settingsRaw = 64
    spr.m_RD.uvTransform = Vector4f(100.0, float(size) / 2, 100.0, float(size) / 2)
    spr.m_RD.texture = PPtr(m_FileID=0, m_PathID=new_tex_id, assetsfile=sf)
    spr.m_PhysicsShape = [
        [Vector2f(-half, -half), Vector2f(-half, half), Vector2f(half, half), Vector2f(half, -half)]
    ]
    spr.save()
    return new_tex_id, new_spr_id, next_id


def build_patched(
    *,
    game_data: Path,
    portraits: list[tuple[str, Path]],
    size: int,
    work_dir: Path,
) -> tuple[Path, Path, list[tuple[str, int, int]]]:
    if not portraits:
        raise ValueError("no portraits to inject")
    work_dir.mkdir(parents=True, exist_ok=True)
    saved = work_dir / "saved"
    saved.mkdir(parents=True, exist_ok=True)

    for fname in ("resources.assets", "globalgamemanagers"):
        shutil.copy2(game_data / fname, work_dir / fname)

    env = UnityPy.load(str(work_dir / "resources.assets"))
    sf = _serialized_file(env)
    next_id = max(sf.objects) + 1
    donors = resolve_donors(sf)
    print(f"  donors: texture={donors[0]} sprite={donors[1]}")
    injected: list[tuple[str, int, int]] = []
    for asset_name, png in portraits:
        if not png.is_file():
            raise FileNotFoundError(f"PNG missing for {asset_name}: {png}")
        tex_id, spr_id, next_id = _inject_one(
            sf, asset_name=asset_name, png=png, size=size, next_id=next_id, donors=donors
        )
        injected.append((asset_name, tex_id, spr_id))
        print(f"  staged {asset_name} tex={tex_id} spr={spr_id} from {png.name}")

    sf.mark_changed()
    env.save(pack="none", out_path=str(saved))

    genv = UnityPy.load(str(work_dir / "globalgamemanagers"))
    gsf = next(iter(genv.files.values()))
    rm_obj = next(o for o in genv.objects if o.type.name == "ResourceManager")
    rm = rm_obj.read()
    keys = {f"icons/dialogue/{name}" for name, _, _ in injected}
    rm.m_Container = [it for it in rm.m_Container if str(it[0]).replace("\\", "/") not in keys]
    samples = [it for it in rm.m_Container if str(it[0]).replace("\\", "/") == RM_SAMPLE_KEY]
    if not samples:
        raise SystemExit(f"FAIL ResourceManager has no {RM_SAMPLE_KEY} entry")
    sample = samples[0]
    # The PPtr file index of resources.assets inside globalgamemanagers is per build; take it
    # from the vanilla entry and prove it names resources.assets (it was hard-coded to 3).
    file_id = sample[1].m_FileID
    if {it[1].m_FileID for it in samples} != {file_id}:
        raise SystemExit(f"FAIL {RM_SAMPLE_KEY} entries disagree on m_FileID")
    externals = [e.path for e in gsf.externals]
    if not (1 <= file_id <= len(externals)) or Path(externals[file_id - 1]).name != "resources.assets":
        raise SystemExit(f"FAIL ResourceManager m_FileID {file_id} does not name resources.assets")
    pp_type = type(sample[1])
    for asset_name, tex_id, spr_id in injected:
        key = f"icons/dialogue/{asset_name}"
        rm.m_Container.append(
            (key, pp_type(m_FileID=file_id, m_PathID=tex_id, assetsfile=sample[1].assetsfile))
        )
        rm.m_Container.append(
            (key, pp_type(m_FileID=file_id, m_PathID=spr_id, assetsfile=sample[1].assetsfile))
        )
    rm_obj.save_typetree(rm)
    gsf.mark_changed()
    genv.save(pack="none", out_path=str(saved))

    (work_dir / "injection_ids.txt").write_text(
        "\n".join(f"{name}\ttex={tex}\tspr={spr}" for name, tex, spr in injected) + "\n",
        encoding="utf-8",
    )
    return saved / "resources.assets", saved / "globalgamemanagers", injected


def install_patched(game_data: Path, resources_src: Path, ggm_src: Path) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = game_data / f"_resources_surgery_backup_{stamp}"
    backup.mkdir(parents=True, exist_ok=True)
    for name in ("resources.assets", "globalgamemanagers"):
        shutil.copy2(game_data / name, backup / name)
    shutil.copy2(resources_src, game_data / "resources.assets")
    shutil.copy2(ggm_src, game_data / "globalgamemanagers")
    (backup / "RESTORE.txt").write_text(
        "Copy resources.assets and globalgamemanagers from this folder back into HeroesOldenEra_Data.\n"
        "resources.assets.resS was not modified.\n",
        encoding="utf-8",
    )
    return backup


def verify_installed(game_data: Path, injected: list[tuple[str, int, int]]) -> None:
    env = UnityPy.load(str(game_data / "resources.assets"))
    sf = _serialized_file(env)
    genv = UnityPy.load(str(game_data / "globalgamemanagers"))
    rm = next(o.read() for o in genv.objects if o.type.name == "ResourceManager")
    for asset_name, tex_id, spr_id in injected:
        key = f"icons/dialogue/{asset_name}"
        tex = sf.objects[tex_id].read()
        spr = sf.objects[spr_id].read()
        assert tex.m_Name == asset_name, tex.m_Name
        assert spr.m_Name == asset_name, spr.m_Name
        assert tex.image is not None and tex.image.size[0] > 0
        hits = [it[1].m_PathID for it in rm.m_Container if str(it[0]).replace("\\", "/") == key]
        assert hits == [tex_id, spr_id], (key, hits, tex_id, spr_id)
        print(f"verify ok: {key} -> tex={tex_id} spr={spr_id} image={tex.image.size}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--game-root",
        type=Path,
        required=True,
        help="Install or mirror root holding HeroesOldenEra.exe. Required; there is no default "
        "install. Only --install writes to it.",
    )
    ap.add_argument("--png", type=Path, default=DEFAULT_PNG)
    ap.add_argument("--name", default=DEFAULT_NAME)
    ap.add_argument("--size", type=int, default=DEFAULT_SIZE)
    ap.add_argument(
        "--from-inventory",
        action="store_true",
        help="Inject every icons/dialogue/dialogue_hero_homm3_* listed by inventory_campaign_dialog_portraits.py",
    )
    ap.add_argument(
        "--inventory",
        type=Path,
        default=INVENTORY_ICONS,
        help="Path to required_homm3_icons.json",
    )
    ap.add_argument(
        "--work-dir",
        type=Path,
        default=REPO / "artifacts" / "resources_dialog_portrait_inject",
    )
    ap.add_argument("--report", type=Path, help="Write a JSON record of input/output sha256 and ids.")
    ap.add_argument("--dry-run", action="store_true", help="Build only; do not touch --game-root.")
    ap.add_argument("--install", action="store_true", help="Backup and install into --game-root.")
    args = ap.parse_args()

    if not args.dry_run and not args.install:
        ap.error("Pass --dry-run or --install")
    game_root = args.game_root.resolve()
    game_data = game_root / "HeroesOldenEra_Data"
    if not (game_root / "HeroesOldenEra.exe").is_file():
        raise SystemExit(f"FAIL --game-root has no HeroesOldenEra.exe: {game_root}")
    for fname in ("resources.assets", "globalgamemanagers"):
        if not (game_data / fname).is_file():
            raise SystemExit(f"FAIL game data missing {fname}: {game_data}")

    if args.from_inventory:
        if not args.inventory.is_file():
            raise SystemExit(
                f"inventory missing: {args.inventory}\n"
                "Run: python tools/inventory_campaign_dialog_portraits.py"
            )
        icons = json.loads(args.inventory.read_text(encoding="utf-8")).get("icons") or []
        portraits = []
        for key in icons:
            name = dialog_key_to_asset_name(key)
            portraits.append((name, dialog_icon_to_png(name)))
    else:
        portraits = [(args.name, args.png)]

    inputs = {f: _sha256(game_data / f, limit=None) for f in ("resources.assets", "globalgamemanagers")}
    print(f"source resources sha256 {inputs['resources.assets']}")
    print(f"injecting {len(portraits)} portrait(s)")
    res_out, ggm_out, injected = build_patched(
        game_data=game_data,
        portraits=portraits,
        size=args.size,
        work_dir=args.work_dir,
    )
    print(f"built {res_out} ({res_out.stat().st_size} bytes)")
    print(f"built {ggm_out} ({ggm_out.stat().st_size} bytes)")
    verify_installed(res_out.parent, injected)

    if args.report:
        report = {
            "schema": "dialog_portrait_inject_report.v1",
            "gameRoot": str(game_root),
            "inventory": str(args.inventory) if args.from_inventory else None,
            "size": args.size,
            "inputs": {
                f: {"size": (game_data / f).stat().st_size, "sha256": inputs[f]} for f in inputs
            },
            "outputs": {
                p.name: {"path": str(p), "size": p.stat().st_size, "sha256": _sha256(p, limit=None)}
                for p in (res_out, ggm_out)
            },
            "injected": [{"key": f"icons/dialogue/{n}", "tex": t, "spr": s} for n, t, s in injected],
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
        print(f"report {args.report}")

    if args.install:
        backup = install_patched(game_data, res_out, ggm_out)
        print(f"installed; backup at {backup}")
        verify_installed(game_data, injected)
    else:
        print("dry-run only; --game-root unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
