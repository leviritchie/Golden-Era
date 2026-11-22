// Elemental Fusion, fluid experiment (2026-11-19): the fused body never exists as an asset. At spawn the two parents'
// skinned meshes are sampled into particles bound to the host rig; every tick a small position-based fluid (PBF) with
// heat, buoyancy, immiscibility and phase change runs on them, and a surface-nets pass rebuilds the visible surface.
// Engine-agnostic on purpose (System + System.Numerics only, no Unity types, no per-step allocation after warm-up) so
// the same file compiles in the Unity editor lab and in the IL2CPP BepInEx plugin (canonical copy: the lab's src/;
// the plugin's FluidFusionCore.cs is synced from it).
using System;
using System.Collections.Generic;
using System.Numerics;
using System.Collections.Concurrent;
using System.Threading.Tasks;

namespace OldenEra.FluidFusion
{
    /// <summary>Range-chunked parallel loop over pure managed arrays (no engine objects are touched off-thread).</summary>
    public static class Par
    {
        public static bool Enabled = true;
        public static void For(int n, Action<int, int> body, int minChunk = 256)
        {
            if (!Enabled || n < minChunk * 2) { body(0, n); return; }
            int chunk = Math.Max(minChunk, n / (Environment.ProcessorCount * 3));
            Parallel.ForEach(Partitioner.Create(0, n, chunk), r => body(r.Item1, r.Item2));
        }
    }

    /// <summary>Row-major 3x4 affine (column-vector convention, like UnityEngine.Matrix4x4 rows 0..2).</summary>
    public struct Affine
    {
        public float M00, M01, M02, M03, M10, M11, M12, M13, M20, M21, M22, M23;

        public Vector3 Point(Vector3 p) => new Vector3(
            M00 * p.X + M01 * p.Y + M02 * p.Z + M03,
            M10 * p.X + M11 * p.Y + M12 * p.Z + M13,
            M20 * p.X + M21 * p.Y + M22 * p.Z + M23);

        public static Affine Identity => new Affine { M00 = 1, M11 = 1, M22 = 1 };

        public static Affine ScaleTranslate(float s, Vector3 t) =>
            new Affine { M00 = s, M11 = s, M22 = s, M03 = t.X, M13 = t.Y, M23 = t.Z };
    }

    /// <summary>Per-element fluid behaviour; one JSON row per element in the kit.</summary>
    public sealed class ElementFluid
    {
        public string Name = "";
        public float HomeStiffness = 40f;   // 1/s^2 spring toward the skinned home position
        public float HomeDamping = 6f;      // 1/s, relative to the home's own velocity
        public float Viscosity = 0.2f;      // XSPH blend 0..1 per step
        public float Cohesion = 0.5f;       // same-element attraction (m/s^2 scale)
        public float Repulsion = 0.5f;      // other-element push (immiscibility)
        public float Buoyancy = 0f;         // m/s^2 upward per unit temperature
        public float BaseTemp = 0f;         // temperature the element relaxes to (its own heat source or sink)
        public float TempRelax = 2f;        // 1/s toward BaseTemp
        public float Conductivity = 3f;     // 1/s heat exchange with neighbours
        public float BoilTemp = 999f;       // liquid -> gas (steam) above this
        public float BoilRate = 6f;         // 1/s chance scale once above BoilTemp
        public float GasLife = 1f;          // s
        public float Jitter = 0.1f;         // curl-flow turbulence (m/s^2)
        public float FlameRate = 0f;        // legacy: flame sprites / s per surface particle (= EmitKind 1)
        // visual sprites the element sheds from its surface (see SpriteKind); rate is per surface particle per second
        public byte EmitKind = SpriteKind.None;
        public float EmitRate = 0f;
        public bool EmitHot = false;        // rate scales with the particle's temperature (flames, embers)
        public float EmitLife = 0.6f;       // s
        public float EmitSize = 2.5f;       // x particle spacing
        public Vector4 EmitColor = new Vector4(1f, 1f, 1f, 1f);   // linear rgb (HDR ok); a = opacity
        public Vector4 SteamColor = new Vector4(0.9f, 0.92f, 0.95f, 0.8f);   // when this element boils
    }

    /// <summary>Sprite looks shared by the core, the lab and FluidSprite.shader (uv0.z of each sprite vertex).</summary>
    public static class SpriteKind
    {
        public const byte Steam = 0, Flame = 1, Ember = 2, Spark = 3, Wisp = 4, Snow = 5, Dust = 6, Mote = 7, None = 255;
        // per kind: upward accel (m/s^2, negative falls), drag (1/s), orbit (rad/s around the body axis), size at end of
        // life (x start), velocity stretch, initial outward speed (m/s)
        internal static readonly float[] Rise = { 1.2f, 2.5f, 1.8f, 0f, 0.35f, -0.35f, -3.2f, 0.25f };
        internal static readonly float[] Drag = { 1.2f, 2f, 1.5f, 3.5f, 1.1f, 2.2f, 0.6f, 2f };
        internal static readonly float[] Orbit = { 0f, 0f, 0.4f, 0f, 1.6f, 0.3f, 0f, 0.9f };
        internal static readonly float[] Grow = { 1.7f, 0.5f, 0.6f, 0.8f, 1.8f, 1f, 1f, 1f };
        internal static readonly float[] Stretch = { 0f, 0f, 0.6f, 5f, 1.5f, 0f, 0f, 0f };
        internal static readonly float[] Burst = { 0.3f, 0.2f, 0.4f, 1.6f, 0.25f, 0.15f, 0.5f, 0.2f };
    }

    public sealed class SkinSource
    {
        public Vector3[] Vertices = Array.Empty<Vector3>();
        public Vector3[] Normals = Array.Empty<Vector3>();
        public int[] Triangles = Array.Empty<int>();
        public int[] Bones = Array.Empty<int>();       // 4 per vertex
        public float[] Weights = Array.Empty<float>();  // 4 per vertex
        public Affine[] BindPoses = Array.Empty<Affine>();   // mesh space -> bone local (SkinnedMeshRenderer.bindposes)
        public string[] BoneNames = Array.Empty<string>();
    }

    public struct Seed
    {
        public Vector3 Rest;      // host mesh space
        public int B0, B1, B2, B3;
        public float W0, W1, W2, W3;
        public bool Surface;
    }

    /// <summary>One elemental's body sampled into particle seeds (per parent, never per fusion), at several
    /// spacings (detail levels). Rest positions are in that elemental's mesh space; bones index <see cref="BoneNames"/>.
    /// The runtime fits the file to the live mesh by bounds and resolves bones by name.</summary>
    public sealed class SeedFile
    {
        public const int Version = 1;
        public string Element = "";
        public string[] BoneNames = Array.Empty<string>();
        public Vector3 BoundsCenter, BoundsSize;
        public readonly List<(float Spacing, List<Seed> Seeds)> Lods = new List<(float, List<Seed>)>();

        public void Write(System.IO.Stream s)
        {
            using var w = new System.IO.BinaryWriter(s, System.Text.Encoding.UTF8, true);
            w.Write(0x5346454F); w.Write(Version); w.Write(Element ?? "");
            w.Write(BoneNames.Length); foreach (string n in BoneNames) w.Write(n ?? "");
            WriteV(w, BoundsCenter); WriteV(w, BoundsSize);
            w.Write(Lods.Count);
            foreach (var (sp, seeds) in Lods)
            {
                w.Write(sp); w.Write(seeds.Count);
                foreach (Seed q in seeds)
                {
                    WriteV(w, q.Rest);
                    w.Write((short)q.B0); w.Write((short)q.B1); w.Write((short)q.B2); w.Write((short)q.B3);
                    w.Write(q.W0); w.Write(q.W1); w.Write(q.W2); w.Write(q.W3);
                    w.Write(q.Surface);
                }
            }
        }

        public static SeedFile Read(System.IO.Stream s)
        {
            using var r = new System.IO.BinaryReader(s, System.Text.Encoding.UTF8, true);
            if (r.ReadInt32() != 0x5346454F) throw new System.IO.InvalidDataException("not a fluid seed file");
            int ver = r.ReadInt32();
            if (ver != Version) throw new System.IO.InvalidDataException("fluid seed file version " + ver + ", expected " + Version);
            var f = new SeedFile { Element = r.ReadString() };
            f.BoneNames = new string[r.ReadInt32()];
            for (int i = 0; i < f.BoneNames.Length; i++) f.BoneNames[i] = r.ReadString();
            f.BoundsCenter = ReadV(r); f.BoundsSize = ReadV(r);
            int lods = r.ReadInt32();
            for (int l = 0; l < lods; l++)
            {
                float sp = r.ReadSingle(); int n = r.ReadInt32();
                var seeds = new List<Seed>(n);
                for (int i = 0; i < n; i++)
                    seeds.Add(new Seed
                    {
                        Rest = ReadV(r), B0 = r.ReadInt16(), B1 = r.ReadInt16(), B2 = r.ReadInt16(), B3 = r.ReadInt16(),
                        W0 = r.ReadSingle(), W1 = r.ReadSingle(), W2 = r.ReadSingle(), W3 = r.ReadSingle(), Surface = r.ReadBoolean(),
                    });
                f.Lods.Add((sp, seeds));
            }
            return f;
        }

        /// <summary>The level whose particle count is closest to <paramref name="target"/>.</summary>
        public (float Spacing, List<Seed> Seeds) Pick(int target)
        {
            var best = Lods[0];
            foreach (var l in Lods) if (Math.Abs(l.Seeds.Count - target) < Math.Abs(best.Seeds.Count - target)) best = l;
            return best;
        }

        private static void WriteV(System.IO.BinaryWriter w, Vector3 v) { w.Write(v.X); w.Write(v.Y); w.Write(v.Z); }
        private static Vector3 ReadV(System.IO.BinaryReader r) => new Vector3(r.ReadSingle(), r.ReadSingle(), r.ReadSingle());
    }

    public static class Seeder
    {
        /// <summary>Volume + near-surface samples of one skinned mesh at <paramref name="spacing"/>, moved into host mesh
        /// space by <paramref name="align"/>, skin weights from the nearest source vertices, bones renamed through
        /// <paramref name="boneMap"/> (source bone index -> host bone index, -1 = drop).</summary>
        public static List<Seed> Sample(SkinSource s, float spacing, Affine align, int[] boneMap, int rngSeed)
        {
            int nv = s.Vertices.Length;
            var v = new Vector3[nv];
            for (int i = 0; i < nv; i++) v[i] = align.Point(s.Vertices[i]);
            Vector3 lo = new Vector3(float.MaxValue), hi = new Vector3(float.MinValue);
            foreach (var p in v) { lo = Vector3.Min(lo, p); hi = Vector3.Max(hi, p); }
            lo -= new Vector3(spacing); hi += new Vector3(spacing);
            int nx = (int)MathF.Ceiling((hi.X - lo.X) / spacing), ny = (int)MathF.Ceiling((hi.Y - lo.Y) / spacing),
                nz = (int)MathF.Ceiling((hi.Z - lo.Z) / spacing);
            var votes = new byte[nx * ny * nz];
            for (int axis = 0; axis < 3; axis++) VoteAxis(v, s.Triangles, lo, spacing, nx, ny, nz, axis, votes);

            var occupied = new bool[nx * ny * nz];
            var pts = new List<(Vector3 p, bool surf)>();
            for (int z = 0; z < nz; z++)
                for (int y = 0; y < ny; y++)
                    for (int x = 0; x < nx; x++)
                    {
                        int c = (z * ny + y) * nx + x;
                        if (votes[c] < 2) continue;
                        occupied[c] = true;
                        pts.Add((lo + new Vector3(x + 0.5f, y + 0.5f, z + 0.5f) * spacing, false));
                    }
            // near-surface fill so thin parts (arms, tail tips) survive the voxel pass
            var rng = new Random(rngSeed);
            for (int t = 0; t + 2 < s.Triangles.Length; t += 3)
            {
                Vector3 a = v[s.Triangles[t]], b = v[s.Triangles[t + 1]], c = v[s.Triangles[t + 2]];
                Vector3 n = Vector3.Cross(b - a, c - a);
                float area = n.Length() * 0.5f;
                if (area < 1e-12f) continue;
                n /= area * 2f;
                float want = area / (spacing * spacing);
                int k = (int)want + (rng.NextDouble() < want - (int)want ? 1 : 0);
                for (int q = 0; q < k; q++)
                {
                    float r1 = (float)rng.NextDouble(), r2 = (float)rng.NextDouble();
                    if (r1 + r2 > 1f) { r1 = 1f - r1; r2 = 1f - r2; }
                    Vector3 p = a + (b - a) * r1 + (c - a) * r2 - n * (0.35f * spacing);
                    int ix = (int)((p.X - lo.X) / spacing), iy = (int)((p.Y - lo.Y) / spacing), iz = (int)((p.Z - lo.Z) / spacing);
                    if (ix < 0 || iy < 0 || iz < 0 || ix >= nx || iy >= ny || iz >= nz) continue;
                    int cell = (iz * ny + iy) * nx + ix;
                    if (occupied[cell]) continue;
                    occupied[cell] = true;
                    pts.Add((p, true));
                }
            }

            // skin weights: inverse-distance blend of the 4 nearest source vertices
            float vcell = spacing * 2f;
            var vgrid = new Dictionary<long, List<int>>();
            for (int i = 0; i < nv; i++)
            {
                long key = Key(Fl(v[i].X / vcell), Fl(v[i].Y / vcell), Fl(v[i].Z / vcell));
                if (!vgrid.TryGetValue(key, out var list)) vgrid[key] = list = new List<int>();
                list.Add(i);
            }
            var outSeeds = new List<Seed>(pts.Count);
            var best = new (float d, int i)[4];
            var acc = new Dictionary<int, float>();
            foreach (var (p, surf) in pts)
            {
                for (int k = 0; k < 4; k++) best[k] = (float.MaxValue, -1);
                int cx = Fl(p.X / vcell), cy = Fl(p.Y / vcell), cz = Fl(p.Z / vcell);
                for (int ring = 1; ring <= 4 && best[3].i < 0; ring++)
                {
                    for (int dz = -ring; dz <= ring; dz++)
                        for (int dy = -ring; dy <= ring; dy++)
                            for (int dx = -ring; dx <= ring; dx++)
                            {
                                if (ring > 1 && Math.Max(Math.Abs(dx), Math.Max(Math.Abs(dy), Math.Abs(dz))) != ring) continue;
                                if (!vgrid.TryGetValue(Key(cx + dx, cy + dy, cz + dz), out var list)) continue;
                                foreach (int i in list)
                                {
                                    float d = Vector3.DistanceSquared(p, v[i]);
                                    if (d >= best[3].d) continue;
                                    int k = 3;
                                    while (k > 0 && best[k - 1].d > d) { best[k] = best[k - 1]; k--; }
                                    best[k] = (d, i);
                                }
                            }
                }
                if (best[0].i < 0) continue;
                acc.Clear();
                for (int k = 0; k < 4; k++)
                {
                    if (best[k].i < 0) break;
                    float wv = 1f / (MathF.Sqrt(best[k].d) + spacing * 0.25f);
                    for (int j = 0; j < 4; j++)
                    {
                        int sb = s.Bones[best[k].i * 4 + j];
                        float w = s.Weights[best[k].i * 4 + j];
                        if (w <= 0f || sb < 0 || sb >= boneMap.Length) continue;
                        int hb = boneMap[sb];
                        if (hb < 0) continue;
                        acc.TryGetValue(hb, out float cur);
                        acc[hb] = cur + w * wv;
                    }
                }
                if (acc.Count == 0) continue;
                var top = new List<KeyValuePair<int, float>>(acc);
                top.Sort((x, y) => y.Value.CompareTo(x.Value));
                float sum = 0f;
                for (int k = 0; k < Math.Min(4, top.Count); k++) sum += top[k].Value;
                var sd = new Seed { Rest = p, Surface = surf, B0 = top[0].Key, W0 = top[0].Value / sum };
                if (top.Count > 1) { sd.B1 = top[1].Key; sd.W1 = top[1].Value / sum; } else sd.B1 = sd.B0;
                if (top.Count > 2) { sd.B2 = top[2].Key; sd.W2 = top[2].Value / sum; } else sd.B2 = sd.B0;
                if (top.Count > 3) { sd.B3 = top[3].Key; sd.W3 = top[3].Value / sum; } else sd.B3 = sd.B0;
                outSeeds.Add(sd);
            }
            return outSeeds;
        }

        /// <summary>Spacing that gives about <paramref name="target"/> seeds, from one trial sampling.</summary>
        public static float SpacingFor(SkinSource s, Affine align, int[] boneMap, int target, float trial)
        {
            int n = Math.Max(1, Sample(s, trial, align, boneMap, 1).Count);
            return trial * MathF.Pow((float)n / target, 1f / 3f);
        }

        /// <summary>Guest infusion: the host keeps the whole shape and the guest takes over <paramref name="fraction"/> of its
        /// particles, preferring host particles inside the aligned guest volume, then interior ones, then vein noise
        /// (so the guest's anatomy decides WHERE it shows, the host decides the silhouette). Returns 0 host / 1 guest.</summary>
        public static byte[] Infuse(List<Seed> host, List<Seed> guest, float spacing, float fraction, float veinScale, int rngSeed)
        {
            int[] order = InfuseRank(host, guest, spacing, veinScale, rngSeed);
            var elem = new byte[host.Count];
            int take = (int)(fraction * host.Count);
            for (int k = 0; k < take; k++) elem[order[k]] = 1;
            return elem;
        }

        /// <summary>Host particle indices, most guest-like first (inside the guest volume, interior, on a vein). Several
        /// guests can then claim particles in rank order without stealing each other's.</summary>
        public static int[] InfuseRank(List<Seed> host, List<Seed> guest, float spacing, float veinScale, int rngSeed)
        {
            var occ = new HashSet<long>();
            foreach (Seed g in guest) occ.Add(Key(Fl(g.Rest.X / spacing), Fl(g.Rest.Y / spacing), Fl(g.Rest.Z / spacing)));
            var rng = new Random(rngSeed);
            var phase = new Vector3((float)rng.NextDouble() * 10f, (float)rng.NextDouble() * 10f, (float)rng.NextDouble() * 10f);
            var score = new float[host.Count];
            for (int i = 0; i < host.Count; i++)
            {
                Vector3 p = host[i].Rest;
                int cx = Fl(p.X / spacing), cy = Fl(p.Y / spacing), cz = Fl(p.Z / spacing);
                bool inside = false;
                for (int dz = -1; dz <= 1 && !inside; dz++)
                    for (int dy = -1; dy <= 1 && !inside; dy++)
                        for (int dx = -1; dx <= 1 && !inside; dx++)
                            inside = occ.Contains(Key(cx + dx, cy + dy, cz + dz));
                Vector3 q = p * veinScale + phase;
                // ridged sum of sines: thin connected veins rather than round blobs
                float n = 1f - MathF.Abs(MathF.Sin(q.X + 1.7f * MathF.Sin(q.Y)) * MathF.Cos(q.Y + 1.3f * MathF.Sin(q.Z)) + 0.5f * MathF.Sin(2.1f * q.Z + q.X));
                score[i] = (inside ? 1f : 0f) + (host[i].Surface ? 0f : 0.35f) + 0.6f * n;
            }
            var order = new int[host.Count];
            for (int i = 0; i < order.Length; i++) order[i] = i;
            Array.Sort((float[])score.Clone(), order);
            Array.Reverse(order);
            return order;
        }

        private static int Fl(float f) => (int)MathF.Floor(f);
        private static long Key(int x, int y, int z) => ((long)(x & 0x1FFFFF) << 42) | ((long)(y & 0x1FFFFF) << 21) | (long)(z & 0x1FFFFF);

        // Parity ray cast along one axis through every column of the sample grid; a cell is inside when 2 of 3 axes agree
        // (DEF retarget meshes are not reliably watertight).
        private static void VoteAxis(Vector3[] v, int[] tri, Vector3 lo, float sp, int nx, int ny, int nz, int axis, byte[] votes)
        {
            int[] n = { nx, ny, nz };
            int ua = (axis + 1) % 3, va = (axis + 2) % 3;
            int nu = n[ua], nvv = n[va];
            var hits = new List<float>[nu * nvv];
            float C(Vector3 p, int a) => a == 0 ? p.X : a == 1 ? p.Y : p.Z;
            float L(int a) => a == 0 ? lo.X : a == 1 ? lo.Y : lo.Z;
            for (int t = 0; t + 2 < tri.Length; t += 3)
            {
                Vector3 a = v[tri[t]], b = v[tri[t + 1]], c = v[tri[t + 2]];
                float au = C(a, ua), av = C(a, va), bu = C(b, ua), bv = C(b, va), cu = C(c, ua), cv = C(c, va);
                int u0 = Math.Max(0, (int)MathF.Floor((MathF.Min(au, MathF.Min(bu, cu)) - L(ua)) / sp - 0.5f));
                int u1 = Math.Min(nu - 1, (int)MathF.Ceiling((MathF.Max(au, MathF.Max(bu, cu)) - L(ua)) / sp - 0.5f));
                int v0 = Math.Max(0, (int)MathF.Floor((MathF.Min(av, MathF.Min(bv, cv)) - L(va)) / sp - 0.5f));
                int v1 = Math.Min(nvv - 1, (int)MathF.Ceiling((MathF.Max(av, MathF.Max(bv, cv)) - L(va)) / sp - 0.5f));
                float det = (bu - au) * (cv - av) - (cu - au) * (bv - av);
                if (MathF.Abs(det) < 1e-12f) continue;
                for (int iu = u0; iu <= u1; iu++)
                    for (int iv = v0; iv <= v1; iv++)
                    {
                        float pu = L(ua) + (iu + 0.5f) * sp, pv = L(va) + (iv + 0.5f) * sp;
                        float l1 = ((pu - au) * (cv - av) - (cu - au) * (pv - av)) / det;
                        float l2 = ((bu - au) * (pv - av) - (pu - au) * (bv - av)) / det;
                        if (l1 < 0 || l2 < 0 || l1 + l2 > 1) continue;
                        float h = C(a, axis) + l1 * (C(b, axis) - C(a, axis)) + l2 * (C(c, axis) - C(a, axis));
                        int col = iu * nvv + iv;
                        (hits[col] ??= new List<float>()).Add(h);
                    }
            }
            float la = L(axis);
            for (int iu = 0; iu < nu; iu++)
                for (int iv = 0; iv < nvv; iv++)
                {
                    var hl = hits[iu * nvv + iv];
                    if (hl == null || hl.Count < 2) continue;
                    hl.Sort();
                    int k = 0;
                    for (int ia = 0; ia < n[axis]; ia++)
                    {
                        float pa = la + (ia + 0.5f) * sp;
                        while (k < hl.Count && hl[k] < pa) k++;
                        if ((k & 1) == 0) continue;
                        int x = axis == 0 ? ia : ua == 0 ? iu : iv;
                        int y = axis == 1 ? ia : ua == 1 ? iu : iv;
                        int z = axis == 2 ? ia : ua == 2 ? iu : iv;
                        votes[(z * ny + y) * nx + x]++;
                    }
                }
        }
    }

    /// <summary>Visual-only sprites the adapter turns into camera-facing quads (FluidSprite.shader expands them).</summary>
    public struct Sprite
    {
        public Vector3 P, V;
        public float Age, Life, Size, Seed;
        public byte Kind;   // SpriteKind
        public byte Elem;   // emitting element (colour)
    }

    public sealed class FluidBody
    {
        public const byte Bound = 0, Gas = 1;
        public const int MaxNeighbors = 48;

        public readonly ElementFluid[] Elements;
        public readonly float Spacing, H;
        public int Count;
        public Vector3[] P, V, Pred, Home, HomePrev, Delta;
        public Vector3[] Local; public int[] Bone; public float[] W;     // 4 per particle
        public byte[] Elem, Phase; public bool[] Surface;
        public float[] Temp, Life, Rand, Rho0, Lambda, NewTemp;
        public int[] NeighborCount, Neighbors;
        public readonly List<Sprite> Sprites = new List<Sprite>();
        public float Time;
        public int BoiledThisStep, GasCount;
        public float Instability;   // 0..1, external (e.g. HP lost): weakens cohesion and home springs
        public Vector3 Gravity = new Vector3(0, -9.81f, 0);
        public float GasBuoyancy = 2.2f, GasDrag = 1.5f, MaxSpeed = 6f;
        public int SolverIterations = 2;
        public int NeighborDiv = 2;
        public float ForceScale = 12f;
        public float SteamSizeMul = 4f;
        public int MaxSprites = 420;
        private Vector3 axis;   // body centroid (bound particles), the orbit axis for wisps / motes
        /// <summary>Accumulated ms per phase: 0 homes+integrate, 1 neighbours, 2 density, 3 visc, 4 heat, 5 finish+sprites.</summary>
        public readonly double[] PhaseMs = new double[6];
        private long tick;
        private void Mark(int phase) { long t = System.Diagnostics.Stopwatch.GetTimestamp(); PhaseMs[phase] += (t - tick) * 1000.0 / System.Diagnostics.Stopwatch.Frequency; tick = t; }

        private readonly Random rng;
        private float poly6, spikyGrad, eps;
        private int[] cellOf = Array.Empty<int>(), cellStart = Array.Empty<int>(), cellCount = Array.Empty<int>(), sorted = Array.Empty<int>();

        public FluidBody(ElementFluid[] elements, float spacing, int capacity, int seed)
        {
            Elements = elements; Spacing = spacing; H = spacing * 2.1f; rng = new Random(seed);
            P = new Vector3[capacity]; V = new Vector3[capacity]; Pred = new Vector3[capacity]; Home = new Vector3[capacity];
            HomePrev = new Vector3[capacity]; Delta = new Vector3[capacity];
            Local = new Vector3[capacity * 4]; Bone = new int[capacity * 4]; W = new float[capacity * 4];
            Elem = new byte[capacity]; Phase = new byte[capacity]; Surface = new bool[capacity];
            Temp = new float[capacity]; Life = new float[capacity]; Rand = new float[capacity]; Rho0 = new float[capacity];
            Lambda = new float[capacity]; NewTemp = new float[capacity];
            NeighborCount = new int[capacity]; Neighbors = new int[capacity * MaxNeighbors];
            poly6 = 315f / (64f * MathF.PI * MathF.Pow(H, 9));
            spikyGrad = -45f / (MathF.PI * MathF.Pow(H, 6));
        }

        /// <summary>Adds up to <paramref name="max"/> seeds (uniformly subsampled) of one element.</summary>
        public void Add(List<Seed> seeds, byte elem, Affine[] hostBindPoses, int max) => Add(seeds, null, elem, hostBindPoses, max);

        /// <summary>Adds seeds with a per-seed element (<paramref name="elems"/>, e.g. from <see cref="Seeder.Infuse"/>).</summary>
        public void Add(List<Seed> seeds, byte[] elems, byte elem, Affine[] hostBindPoses, int max)
        {
            var order = new int[seeds.Count];
            for (int i = 0; i < order.Length; i++) order[i] = i;
            for (int i = order.Length - 1; i > 0; i--) { int j = rng.Next(i + 1); (order[i], order[j]) = (order[j], order[i]); }
            int take = Math.Min(Math.Min(max, seeds.Count), P.Length - Count);
            for (int k = 0; k < take; k++)
            {
                Seed s = seeds[order[k]];
                int i = Count++;
                int[] b = { s.B0, s.B1, s.B2, s.B3 };
                float[] w = { s.W0, s.W1, s.W2, s.W3 };
                for (int j = 0; j < 4; j++)
                {
                    Bone[i * 4 + j] = b[j]; W[i * 4 + j] = w[j];
                    Local[i * 4 + j] = hostBindPoses[b[j]].Point(s.Rest);
                }
                byte e = elems != null ? elems[order[k]] : elem;
                Elem[i] = e; Phase[i] = Bound; Surface[i] = s.Surface;
                Temp[i] = Elements[e].BaseTemp; Rand[i] = (float)rng.NextDouble();
            }
        }

        public void Initialise(Affine[] boneWorld)
        {
            ComputeHomes(boneWorld);
            SortByMorton();
            ComputeHomes(boneWorld);
            for (int i = 0; i < Count; i++) { P[i] = Pred[i] = HomePrev[i] = Home[i]; V[i] = Vector3.Zero; }
            BuildNeighbors();
            // per-particle rest density = density of the home configuration, so PBF only resists compression the
            // motion adds (the superposed parents overlap; a single rho0 would inflate the overlap forever)
            float gsum = 0f; int gn = 0;
            for (int i = 0; i < Count; i++)
            {
                float rho = poly6 * H * H * H * H * H * H;
                Vector3 gi = Vector3.Zero; float g2 = 0f;
                for (int k = 0; k < NeighborCount[i]; k++)
                {
                    int j = Neighbors[i * MaxNeighbors + k];
                    Vector3 d = P[i] - P[j];
                    float r2 = d.LengthSquared();
                    float x = H * H - r2;
                    rho += poly6 * x * x * x;
                    float r = MathF.Sqrt(r2);
                    if (r > 1e-6f) { Vector3 gw = spikyGrad * (H - r) * (H - r) * (d / r); gi += gw; g2 += gw.LengthSquared(); }
                }
                Rho0[i] = rho;
                if (NeighborCount[i] > 8) { gsum += (gi.LengthSquared() + g2) / (rho * rho); gn++; }
            }
            eps = 0.05f * (gn > 0 ? gsum / gn : 1f);
            Surface = MarkSurface();
        }

        private static uint Spread(uint v)
        {
            v &= 0x3ff;
            v = (v | (v << 16)) & 0x030000FF; v = (v | (v << 8)) & 0x0300F00F;
            v = (v | (v << 4)) & 0x030C30C3; v = (v | (v << 2)) & 0x09249249;
            return v;
        }

        /// <summary>Permutes every per-particle array into Morton order of the home positions (spawn-time only).</summary>
        private void SortByMorton()
        {
            int n = Count;
            if (n < 2) return;
            Vector3 lo = new Vector3(float.MaxValue), hi = new Vector3(float.MinValue);
            for (int i = 0; i < n; i++) { lo = Vector3.Min(lo, Home[i]); hi = Vector3.Max(hi, Home[i]); }
            float inv = 1f / Spacing;
            var key = new ulong[n]; var ord = new int[n];
            for (int i = 0; i < n; i++)
            {
                Vector3 g = (Home[i] - lo) * inv;
                uint code = Spread((uint)g.X) | (Spread((uint)g.Y) << 1) | (Spread((uint)g.Z) << 2);
                key[i] = ((ulong)code << 32) | (uint)i; ord[i] = i;
            }
            Array.Sort(key, ord);
            void Perm<T>(T[] a, int stride)
            {
                var tmp = new T[n * stride];
                for (int k = 0; k < n; k++) Array.Copy(a, ord[k] * stride, tmp, k * stride, stride);
                Array.Copy(tmp, 0, a, 0, n * stride);
            }
            Perm(P, 1); Perm(V, 1); Perm(Pred, 1); Perm(Home, 1); Perm(HomePrev, 1);
            Perm(Local, 4); Perm(Bone, 4); Perm(W, 4);
            Perm(Elem, 1); Perm(Phase, 1); Perm(Surface, 1); Perm(Temp, 1); Perm(Life, 1); Perm(Rand, 1);
        }

        public void ComputeHomes(Affine[] boneWorld)
        {
            Par.For(Count, (a0, a1) => {
            for (int i = a0; i < a1; i++)
            {
                Vector3 h = Vector3.Zero;
                for (int j = 0; j < 4; j++)
                {
                    float w = W[i * 4 + j];
                    if (w > 0f) h += w * boneWorld[Bone[i * 4 + j]].Point(Local[i * 4 + j]);
                }
                Home[i] = h;
            }
            });
        }

        public void Step(float dt, Affine[] boneWorld)
        {
            if (dt <= 0f) return;
            tick = System.Diagnostics.Stopwatch.GetTimestamp();
            ComputeHomes(boneWorld);
            float inv = 1f / dt;
            float hold = 1f - 0.6f * Instability;
            BoiledThisStep = 0; GasCount = 0;
            for (int i = 0; i < Count; i++) if (Phase[i] != Bound) GasCount++;
            Par.For(Count, (a0, a1) => {
            for (int i = a0; i < a1; i++)
            {
                ElementFluid e = Elements[Elem[i]];
                Vector3 vHome = (Home[i] - HomePrev[i]) * inv;
                Vector3 a;
                if (Phase[i] == Bound)
                {
                    a = e.HomeStiffness * hold * (Home[i] - P[i]) + e.HomeDamping * (vHome - V[i]);
                    a.Y += e.Buoyancy * Temp[i];
                    a += e.Jitter * (1f + Instability) * Flow(P[i], Time, Rand[i]);
                }
                else
                {
                    a = new Vector3(0, GasBuoyancy, 0) - GasDrag * V[i] + 0.6f * Flow(P[i], Time, Rand[i]);
                    Life[i] -= dt;
                }
                V[i] += a * dt;
                float s2 = V[i].LengthSquared();
                if (s2 > MaxSpeed * MaxSpeed) V[i] *= MaxSpeed / MathF.Sqrt(s2);
                Pred[i] = P[i] + V[i] * dt;
            }
            });

            Mark(0);
            BuildNeighbors();
            Mark(1);
            for (int it = 0; it < SolverIterations; it++) SolveDensity();
            Mark(2);

            for (int i = 0; i < Count; i++) if (Phase[i] == Bound) V[i] = (Pred[i] - P[i]) * inv;
            ViscosityAndCohesion(dt);
            Mark(3);
            Heat(dt);
            Mark(4);

            for (int i = 0; i < Count; i++)
            {
                if (Phase[i] == Gas && Life[i] <= 0f)
                {
                    // condensed back: the particle rejoins its home inside the body
                    Phase[i] = Bound; Pred[i] = Home[i]; V[i] = (Home[i] - HomePrev[i]) * inv;
                    Temp[i] = Elements[Elem[i]].BaseTemp;
                }
                P[i] = Pred[i];
                HomePrev[i] = Home[i];
            }
            UpdateSprites(dt);
            Time += dt;
            Mark(5);
        }

        // two octaves of a divergence-free sine field (curl of (sin fy, sin fz, sin fx)); cheap stand-in for curl noise
        public static Vector3 Flow(Vector3 p, float t, float s)
        {
            Vector3 r = Vector3.Zero;
            float f = 5f, amp = 1f;
            for (int o = 0; o < 2; o++)
            {
                float a = t * (1.3f + o) + s * 6.283f, b = t * (1.7f + o) + 2.1f, c = t * (2.3f + o) + 4.2f;
                r += amp * new Vector3(-MathF.Cos(f * p.Z + b), -MathF.Cos(f * p.X + c), -MathF.Cos(f * p.Y + a));
                f *= 2.3f; amp *= 0.5f;
            }
            return r;
        }

        private int gnx, gny, gnz;

        private void BuildNeighbors()
        {
            int n = Count;
            Vector3 lo = new Vector3(float.MaxValue), hi = new Vector3(float.MinValue);
            for (int i = 0; i < n; i++) if (Phase[i] == Bound) { lo = Vector3.Min(lo, Pred[i]); hi = Vector3.Max(hi, Pred[i]); }
            if (lo.X > hi.X) { Array.Clear(NeighborCount, 0, n); return; }
            // dense grid with cell >= H / NeighborDiv; searching +-NeighborDiv cells is exact. Finer cells test fewer
            // candidates (H/2: 125 eighth-cells = 15.6 H^3 instead of 27 H^3). Grown to cap the table size.
            int reach = Math.Max(1, NeighborDiv);
            float cell = H / reach;
            Vector3 ext = hi - lo;
            while ((long)((int)(ext.X / cell) + 1) * ((int)(ext.Y / cell) + 1) * ((int)(ext.Z / cell) + 1) > 1 << 21) cell *= 1.25f;
            gnx = (int)(ext.X / cell) + 1; gny = (int)(ext.Y / cell) + 1; gnz = (int)(ext.Z / cell) + 1;
            int size = gnx * gny * gnz;
            if (cellStart.Length < size + 1) { cellStart = new int[size + 1]; cellCount = new int[size + 1]; }
            if (cellOf.Length < n) { cellOf = new int[P.Length]; sorted = new int[P.Length]; }
            Array.Clear(cellCount, 0, size + 1);
            float inv = 1f / cell;
            for (int i = 0; i < n; i++)
            {
                if (Phase[i] != Bound) { cellOf[i] = -1; continue; }
                Vector3 g = (Pred[i] - lo) * inv;
                int c = (Math.Min((int)g.Z, gnz - 1) * gny + Math.Min((int)g.Y, gny - 1)) * gnx + Math.Min((int)g.X, gnx - 1);
                cellOf[i] = c; cellCount[c]++;
            }
            int run = 0;
            for (int c = 0; c < size; c++) { cellStart[c] = run; run += cellCount[c]; cellCount[c] = 0; }
            cellStart[size] = run;
            for (int i = 0; i < n; i++) { int c = cellOf[i]; if (c >= 0) sorted[cellStart[c] + cellCount[c]++] = i; }
            float h2 = H * H;
            Par.For(n, (a, e) =>
            {
                for (int i = a; i < e; i++)
                {
                    int cnt = 0, ci = cellOf[i];
                    if (ci >= 0)
                    {
                        Vector3 p = Pred[i];
                        int cx = ci % gnx, cy = (ci / gnx) % gny, cz = ci / (gnx * gny);
                        int x0 = Math.Max(0, cx - reach), x1 = Math.Min(gnx - 1, cx + reach);
                        int baseI = i * MaxNeighbors;
                        for (int z = Math.Max(0, cz - reach); z <= Math.Min(gnz - 1, cz + reach) && cnt < MaxNeighbors; z++)
                            for (int y = Math.Max(0, cy - reach); y <= Math.Min(gny - 1, cy + reach) && cnt < MaxNeighbors; y++)
                            {
                                int row = (z * gny + y) * gnx;
                                // cells x0..x1 of one row are contiguous in the sorted order
                                int s0 = cellStart[row + x0], s1 = cellStart[row + x1] + cellCount[row + x1];
                                for (int q = s0; q < s1 && cnt < MaxNeighbors; q++)
                                {
                                    int j = sorted[q];
                                    if (j != i && Vector3.DistanceSquared(p, Pred[j]) < h2) Neighbors[baseI + cnt++] = j;
                                }
                            }
                    }
                    NeighborCount[i] = cnt;
                }
            });
        }

        private void SolveDensity()
        {
            float h2 = H * H, self = poly6 * h2 * h2 * h2, Hh = H, p6 = poly6, sg = spikyGrad, ep = eps;
            Par.For(Count, (a, e) =>
            {
                for (int i = a; i < e; i++)
                {
                    Lambda[i] = 0f;
                    if (Phase[i] != Bound) continue;
                    float rho = self; Vector3 gi = Vector3.Zero; float g2 = 0f; Vector3 pi = Pred[i]; float ir0 = 1f / Rho0[i];
                    int bi = i * MaxNeighbors, nc = NeighborCount[i];
                    for (int k = 0; k < nc; k++)
                    {
                        Vector3 d = pi - Pred[Neighbors[bi + k]];
                        float r2 = d.LengthSquared();
                        if (r2 >= h2) continue;
                        float x = h2 - r2; rho += p6 * x * x * x;
                        if (r2 > 1e-12f) { float r = MathF.Sqrt(r2), hr = Hh - r; Vector3 gw = (sg * hr * hr * ir0 / r) * d; gi += gw; g2 += gw.LengthSquared(); }
                    }
                    float C = rho * ir0 - 1f;
                    if (C <= 0f) continue;   // only resist compression; free surfaces and stretching are the springs' job
                    Lambda[i] = -C / (gi.LengthSquared() + g2 + ep);
                }
            });
            float cap = Spacing * 0.5f;
            Par.For(Count, (a, e) =>
            {
                for (int i = a; i < e; i++)
                {
                    Delta[i] = Vector3.Zero;
                    if (Phase[i] != Bound) continue;
                    Vector3 dp = Vector3.Zero, pi = Pred[i]; float li = Lambda[i];
                    int bi = i * MaxNeighbors, nc = NeighborCount[i];
                    for (int k = 0; k < nc; k++)
                    {
                        int j = Neighbors[bi + k];
                        Vector3 d = pi - Pred[j];
                        float r2 = d.LengthSquared();
                        if (r2 >= h2 || r2 < 1e-12f) continue;
                        float r = MathF.Sqrt(r2), hr = Hh - r;
                        dp += ((li + Lambda[j]) * sg * hr * hr / r) * d;
                    }
                    dp /= Rho0[i];
                    float l = dp.Length();
                    if (l > cap) dp *= cap / l;
                    Delta[i] = dp;
                }
            });
            for (int i = 0; i < Count; i++) Pred[i] += Delta[i];
        }

        private void ViscosityAndCohesion(float dt)
        {
            float h2 = H * H;
            float stick = 1f - 0.7f * Instability;
            Par.For(Count, (a0, a1) => {
            for (int i = a0; i < a1; i++)
            {
                Delta[i] = Vector3.Zero;
                if (Phase[i] != Bound) continue;
                ElementFluid ei = Elements[Elem[i]];
                Vector3 dv = Vector3.Zero, f = Vector3.Zero; float wsum = 0f; int fn = 0;
                for (int k = 0; k < NeighborCount[i]; k++)
                {
                    int j = Neighbors[i * MaxNeighbors + k];
                    Vector3 d = P[j] - Pred[i];
                    float r2 = d.LengthSquared();
                    if (r2 >= h2) continue;
                    float x = h2 - r2, w = x * x * x;
                    ElementFluid ej = Elements[Elem[j]];
                    dv += w * (V[j] - V[i]) * (0.5f * (ei.Viscosity + ej.Viscosity));
                    wsum += w;
                    float r = MathF.Sqrt(r2);
                    if (r < 1e-6f) continue;
                    // cohesion pulls toward like neighbours beyond the rest spacing; unlike neighbours push apart
                    float q = r / H;
                    if (Elem[j] == Elem[i]) f += ei.Cohesion * stick * (q > 0.45f ? (q - 0.45f) / 0.55f : 0f) * (d / r);
                    else f -= 0.5f * (ei.Repulsion + ej.Repulsion) * (1f - q) * (d / r);
                    fn++;
                }
                if (wsum > 0f) dv /= wsum;
                // neighbour-averaged, so Cohesion / Repulsion read as accelerations (x ForceScale m/s^2) and the
                // segregation they cause stays local (a few spacings) against the home springs
                if (fn > 0) f /= fn;
                Delta[i] = dv + f * (ForceScale * dt);
            }
            });
            for (int i = 0; i < Count; i++) V[i] += Delta[i];
        }

        private void Heat(float dt)
        {
            float h2 = H * H;
            Par.For(Count, (a0, a1) => {
            for (int i = a0; i < a1; i++)
            {
                ElementFluid e = Elements[Elem[i]];
                float t = Temp[i];
                if (Phase[i] == Bound)
                {
                    float acc = 0f, wsum = 0f;
                    for (int k = 0; k < NeighborCount[i]; k++)
                    {
                        int j = Neighbors[i * MaxNeighbors + k];
                        float r2 = Vector3.DistanceSquared(Pred[i], Pred[j]);
                        if (r2 >= h2) continue;
                        float x = h2 - r2, w = x * x * x;
                        acc += w * (Temp[j] - t) * MathF.Min(e.Conductivity, Elements[Elem[j]].Conductivity);
                        wsum += w;
                    }
                    if (wsum > 0f) t += dt * acc / wsum;
                    t += dt * e.TempRelax * (e.BaseTemp - t);
                }
                else t += dt * 0.8f * (0f - t);
                NewTemp[i] = t;
            }
            });
            for (int i = 0; i < Count; i++)
            {
                Temp[i] = NewTemp[i];
                ElementFluid e = Elements[Elem[i]];
                if (Phase[i] != Bound || Temp[i] <= e.BoilTemp) continue;
                float p = e.BoilRate * (Temp[i] - e.BoilTemp) * (1f / 60f);
                if (rng.NextDouble() >= p) continue;
                Phase[i] = Gas; Life[i] = e.GasLife * (0.7f + 0.6f * (float)rng.NextDouble());
                V[i] += new Vector3(0, 0.6f, 0) + 0.3f * Flow(P[i], Time, Rand[i]);
                Temp[i] *= 0.5f;   // latent heat: boiling carries heat away from the interface
                BoiledThisStep++;
                if (Sprites.Count < MaxSprites)
                    Sprites.Add(new Sprite { P = Pred[i], V = V[i] * 0.5f, Life = Life[i] * 1.2f, Size = Spacing * SteamSizeMul, Seed = Rand[i], Kind = SpriteKind.Steam, Elem = Elem[i] });
            }
        }

        private bool[] MarkSurface()
        {
            var s = new bool[P.Length];
            int full = 0; long tot = 0; int n = 0;
            for (int i = 0; i < Count; i++) { tot += NeighborCount[i]; n++; }
            full = n > 0 ? (int)(tot / n) : 0;
            for (int i = 0; i < Count; i++) s[i] = NeighborCount[i] < full * 0.7f;
            return s;
        }

        private void UpdateSprites(float dt)
        {
            // each element sheds its own sprite kind from surface particles (flame tongues, embers, sparks, wisps, ...)
            int nb = 0; long tot = 0; Vector3 c = Vector3.Zero;
            for (int i = 0; i < Count; i++) if (Phase[i] == Bound) { tot += NeighborCount[i]; nb++; c += P[i]; }
            float mean = nb > 0 ? (float)tot / nb : 0f;
            if (nb > 0) axis = c / nb;
            for (int i = 0; i < Count && Sprites.Count < MaxSprites; i++)
            {
                if (Phase[i] != Bound) continue;
                ElementFluid e = Elements[Elem[i]];
                byte kind = e.EmitKind; float rate = e.EmitRate;
                if (kind == SpriteKind.None && e.FlameRate > 0f) { kind = SpriteKind.Flame; rate = e.FlameRate; }
                if (kind == SpriteKind.None || rate <= 0f) continue;
                Surface[i] = NeighborCount[i] < mean * 0.75f;
                if (!Surface[i]) continue;
                bool hot = e.EmitHot || kind == SpriteKind.Flame;
                if (hot && Temp[i] < 0.5f) continue;
                float r = rate * (hot ? Temp[i] : 1f) * dt;
                if (rng.NextDouble() >= r) continue;
                Vector3 outward = P[i] - Home[i] + (P[i] - axis) * 0.5f;
                float ol = outward.Length();
                outward = ol > 1e-5f ? outward / ol : new Vector3(0, 1, 0);
                float u = (float)rng.NextDouble();
                Sprites.Add(new Sprite
                {
                    P = P[i], V = V[i] * 0.6f + outward * SpriteKind.Burst[kind] * (0.6f + 0.8f * u) + new Vector3(0, kind == SpriteKind.Flame ? 0.9f : 0f, 0),
                    Life = e.EmitLife * (0.7f + 0.6f * (float)rng.NextDouble()),
                    Size = Spacing * e.EmitSize * (0.7f + 0.6f * u), Seed = (float)rng.NextDouble(), Kind = kind, Elem = Elem[i],
                });
            }
            for (int k = Sprites.Count - 1; k >= 0; k--)
            {
                Sprite s = Sprites[k];
                s.Age += dt;
                if (s.Age >= s.Life) { Sprites.RemoveAt(k); continue; }
                int kd = s.Kind < SpriteKind.Rise.Length ? s.Kind : 0;
                Vector3 a = new Vector3(0, SpriteKind.Rise[kd], 0) - SpriteKind.Drag[kd] * s.V;
                if (SpriteKind.Orbit[kd] != 0f)
                {
                    var rad = new Vector3(s.P.X - axis.X, 0, s.P.Z - axis.Z);
                    var tan = new Vector3(-rad.Z, 0, rad.X);
                    a += SpriteKind.Drag[kd] * SpriteKind.Orbit[kd] * tan - 0.8f * rad * SpriteKind.Orbit[kd];
                }
                s.V += (a + 0.4f * Flow(s.P, Time, s.Seed)) * dt;
                s.P += s.V * dt;
                Sprites[k] = s;
            }
        }
    }

    /// <summary>One sprite as four vertices for FluidSprite.shader, which expands the quad in view space (so worker threads
    /// never need the camera). Per vertex: position = centre, normal = velocity, uv0 = (corner x, corner y, kind, age 0..1),
    /// uv1 = (size at this age, seed, rotation, velocity stretch), colour = linear rgba (premultiplied in the shader).</summary>
    public static class SpriteVerts
    {
        private static readonly float[] Cx = { -1f, 1f, 1f, -1f }, Cy = { -1f, -1f, 1f, 1f };

        public static int Count(FluidBody b) => b.Sprites.Count * 4;

        /// <summary>Writes into caller arrays (length >= 4 x sprites, indices >= 6 x sprites). Returns the vertex count.</summary>
        public static int Write(List<Sprite> sprites, ElementFluid[] elements, Vector3[] pos, Vector3[] vel, float[] uv0, float[] uv1, float[] col, int[] idx)
        {
            int n = 0;
            for (int k = 0; k < sprites.Count; k++)
            {
                Sprite s = sprites[k];
                int kd = s.Kind < SpriteKind.Grow.Length ? s.Kind : 0;
                float age = Math.Clamp(s.Age / Math.Max(1e-4f, s.Life), 0f, 1f);
                float size = s.Size * (1f + (SpriteKind.Grow[kd] - 1f) * age);
                ElementFluid e = elements[s.Elem < elements.Length ? s.Elem : 0];
                Vector4 cl = s.Kind == SpriteKind.Steam ? e.SteamColor : e.EmitColor;
                float rot = s.Seed * 6.283f + (s.Kind == SpriteKind.Steam ? age * 0.8f : s.Kind == SpriteKind.Snow ? age * 2f : 0f);
                int v0 = n;
                for (int c = 0; c < 4; c++, n++)
                {
                    pos[n] = s.P; vel[n] = s.V;
                    uv0[n * 4] = Cx[c]; uv0[n * 4 + 1] = Cy[c]; uv0[n * 4 + 2] = s.Kind; uv0[n * 4 + 3] = age;
                    uv1[n * 4] = size; uv1[n * 4 + 1] = s.Seed; uv1[n * 4 + 2] = rot; uv1[n * 4 + 3] = SpriteKind.Stretch[kd];
                    col[n * 4] = cl.X; col[n * 4 + 1] = cl.Y; col[n * 4 + 2] = cl.Z; col[n * 4 + 3] = cl.W;
                }
                int t = k * 6;
                idx[t] = v0; idx[t + 1] = v0 + 2; idx[t + 2] = v0 + 1; idx[t + 3] = v0; idx[t + 4] = v0 + 3; idx[t + 5] = v0 + 2;
            }
            return n;
        }
    }

    /// <summary>Scalar field splatted from a particle subset + naive surface nets. Output buffers are reused.
    /// Splat, vertex and quad passes run in parallel z-slabs, each slab writing only its own cells / lists.</summary>
    public sealed class SurfaceNets
    {
        public readonly List<Vector3> Positions = new List<Vector3>();
        public readonly List<Vector3> Normals = new List<Vector3>();
        public readonly List<float> Mix = new List<float>();     // per-vertex secondary weight (e.g. heat / other element)
        public readonly List<int> Indices = new List<int>();
        public float Cell, Radius, Iso;
        public int MaxDim = 96;
        private float[] field = Array.Empty<float>(), aux = Array.Empty<float>();
        private int[] vid = Array.Empty<int>();
        private int nx, ny, nz; private Vector3 origin; private float cellSize;
        private float[] pw = Array.Empty<float>(), pa = Array.Empty<float>();
        private int[] zStart = Array.Empty<int>(), zOrder = Array.Empty<int>(), pz = Array.Empty<int>();
        private Slab[] slabs = Array.Empty<Slab>();
        private int[] rowLo = Array.Empty<int>(), rowHi = Array.Empty<int>();
        public static int WindingMismatch, WindingChecked; public static bool CheckWinding;
        public static bool SimdSplat = true;
        public static readonly double[] PassMs = new double[5];
        public static bool Profile; private static long pt; private static void PMark(int k) { if (!Profile) return; long t = System.Diagnostics.Stopwatch.GetTimestamp(); PassMs[k] += (t - pt) * 1000.0 / System.Diagnostics.Stopwatch.Frequency; pt = t; }

        private sealed class Slab
        {
            public readonly List<Vector3> Pos = new List<Vector3>(), Nrm = new List<Vector3>();
            public readonly List<float> Mix = new List<float>();
            public readonly List<int> Idx = new List<int>();
            public int Offset;
        }

        private static readonly int[] EA = { 0, 2, 4, 6, 0, 1, 4, 5, 0, 1, 2, 3 }, EB = { 1, 3, 5, 7, 2, 3, 6, 7, 4, 5, 6, 7 };

        public SurfaceNets(float cell, float radius, float iso) { Cell = cell; Radius = radius; Iso = iso; }

        /// <summary>Splat particles with weight(i) &gt; 0 (poly6-shaped bumps) and extract the iso surface.
        /// <paramref name="auxOf"/> is averaged into <see cref="Mix"/> per vertex. Delegates run on the calling thread.</summary>
        public void Build(FluidBody b, Func<int, float> weight, Func<int, float> auxOf)
        {
            if (Profile) pt = System.Diagnostics.Stopwatch.GetTimestamp();
            Positions.Clear(); Normals.Clear(); Mix.Clear(); Indices.Clear();
            int np = b.Count;
            if (pw.Length < np) { pw = new float[b.P.Length]; pa = new float[b.P.Length]; pz = new int[b.P.Length]; zOrder = new int[b.P.Length]; }
            Vector3 lo = new Vector3(float.MaxValue), hi = new Vector3(float.MinValue);
            int used = 0;
            for (int i = 0; i < np; i++)
            {
                float w = weight(i); pw[i] = w;
                if (w <= 0f) continue;
                pa[i] = auxOf(i);
                lo = Vector3.Min(lo, b.P[i]); hi = Vector3.Max(hi, b.P[i]); used++;
            }
            if (used == 0) return;
            float cell = Cell;
            Vector3 pad = new Vector3(Radius + 2f * cell);
            lo -= pad; hi += pad;
            Vector3 size = hi - lo;
            float maxSide = MathF.Max(size.X, MathF.Max(size.Y, size.Z));
            if (maxSide / cell > MaxDim) cell = maxSide / MaxDim;
            origin = lo; cellSize = cell;
            nx = (int)MathF.Ceiling(size.X / cell) + 1; ny = (int)MathF.Ceiling(size.Y / cell) + 1; nz = (int)MathF.Ceiling(size.Z / cell) + 1;
            int n = nx * ny * nz;
            if (field.Length < n) { field = new float[n]; aux = new float[n]; vid = new int[n]; }
            if (rowLo.Length < ny * nz) { rowLo = new int[ny * nz * 2]; rowHi = new int[ny * nz * 2]; }

            // bucket the used particles by their grid z so a slab only visits particles that can reach it
            if (zStart.Length < nz + 1) zStart = new int[nz + 1];
            Array.Clear(zStart, 0, nz + 1);
            float invCell = 1f / cell;
            for (int i = 0; i < np; i++)
            {
                if (pw[i] <= 0f) continue;
                int z = Math.Clamp((int)MathF.Round((b.P[i].Z - origin.Z) * invCell), 0, nz - 1);
                pz[i] = z; zStart[z + 1]++;
            }
            for (int z = 0; z < nz; z++) zStart[z + 1] += zStart[z];
            {
                var fill = new int[nz];
                for (int i = 0; i < np; i++) if (pw[i] > 0f) { int z = pz[i]; zOrder[zStart[z] + fill[z]++] = i; }
            }

            int slabCount = Par.Enabled ? Math.Max(1, Math.Min(nz / 3, Environment.ProcessorCount * 2)) : 1;
            if (slabs.Length < slabCount) { var ns = new Slab[slabCount]; for (int k = 0; k < slabCount; k++) ns[k] = k < slabs.Length ? slabs[k] : new Slab(); slabs = ns; }
            int per = (nz + slabCount - 1) / slabCount;
            float R = Radius, R2 = R * R, invR2 = 1f / R2;
            int rc = (int)MathF.Ceiling(R / cell);
            Vector3[] P = b.P;

            PMark(0);
            // pass 1: splat (each slab clears and writes only its own z planes)
            int VW = Vector<float>.Count; bool simd = Vector.IsHardwareAccelerated && SimdSplat;
            Vector<float> lane; { var la = new float[VW]; for (int q = 0; q < VW; q++) la[q] = q; lane = new Vector<float>(la); }
            RunSlabs(slabCount, k =>
            {
                int z0 = k * per, z1 = Math.Min(nz, z0 + per);
                if (z0 >= z1) return;
                Array.Clear(field, z0 * nx * ny, (z1 - z0) * nx * ny);
                Array.Clear(aux, z0 * nx * ny, (z1 - z0) * nx * ny);
                for (int r = z0 * ny; r < z1 * ny; r++) { rowLo[r] = int.MaxValue; rowHi[r] = -1; }
                int q0 = zStart[Math.Max(0, z0 - rc)], q1 = zStart[Math.Min(nz, z1 + rc)];
                for (int q = q0; q < q1; q++)
                {
                    int i = zOrder[q];
                    float wgt = pw[i], ax = pa[i];
                    Vector3 g = (P[i] - origin) * invCell;
                    int gx = (int)MathF.Round(g.X), gy = (int)MathF.Round(g.Y), gz = (int)MathF.Round(g.Z);
                    int za = Math.Max(z0, gz - rc), zb = Math.Min(z1 - 1, gz + rc);
                    for (int z = za; z <= zb; z++)
                    {
                        float dz = (z - g.Z) * cell, dz2 = dz * dz;
                        if (dz2 >= R2) continue;
                        for (int y = Math.Max(0, gy - rc); y <= Math.Min(ny - 1, gy + rc); y++)
                        {
                            float dy = (y - g.Y) * cell, dyz = dy * dy + dz2;
                            if (dyz >= R2) continue;
                            // x-extent of the sphere on this row
                            float xr = MathF.Sqrt(R2 - dyz) * invCell;
                            int xa = Math.Max(0, (int)MathF.Ceiling(g.X - xr)), xb = Math.Min(nx - 1, (int)MathF.Floor(g.X + xr));
                            int ri = z * ny + y, row = ri * nx;
                            if (xa < rowLo[ri]) rowLo[ri] = xa;
                            if (xb > rowHi[ri]) rowHi[ri] = xb;
                            int x = xa;
                            if (simd)
                            {
                                // lanes past xb stay inside this row (xa + VW <= nx) and get a clamped 0 weight
                                float c0 = 1f - dyz * invR2, sx = cell * cell * invR2;
                                for (; x <= xb && x + VW <= nx; x += VW)
                                {
                                    var dxv = (new Vector<float>(x - g.X) + lane);
                                    var kv = Vector.Max(Vector<float>.Zero, new Vector<float>(c0) - dxv * dxv * sx);
                                    kv = kv * kv * kv * wgt;
                                    (new Vector<float>(field, row + x) + kv).CopyTo(field, row + x);
                                    (new Vector<float>(aux, row + x) + kv * ax).CopyTo(aux, row + x);
                                }
                            }
                            for (; x <= xb; x++)
                            {
                                float dx = (x - g.X) * cell;
                                float kk = 1f - (dx * dx + dyz) * invR2;
                                if (kk <= 0f) continue;
                                kk = kk * kk * kk * wgt;
                                field[row + x] += kk; aux[row + x] += kk * ax;
                            }
                        }
                    }
                }
            });

            PMark(1);
            // pass 2: one vertex per sign-changing cell (mean of its edge crossings); slab-local ids. Only cells inside the
            // union of the touched x-ranges of their four corner rows can change sign (everything else is exactly 0).
            float iso = Iso;
            RunSlabs(slabCount, k =>
            {
                Slab sl = slabs[k];
                sl.Pos.Clear(); sl.Nrm.Clear(); sl.Mix.Clear();
                int z0 = k * per, z1 = Math.Min(nz, z0 + per);
                if (z0 >= z1) return;
                Array.Fill(vid, -1, z0 * nx * ny, (z1 - z0) * nx * ny);
                Span<float> cv = stackalloc float[8];
                Span<float> av = stackalloc float[8];
                int sy = nx, sz = nx * ny;
                for (int z = z0; z < Math.Min(z1, nz - 1); z++)
                    for (int y = 0; y < ny - 1; y++)
                    {
                        int r00 = z * ny + y, r10 = r00 + 1, r01 = r00 + ny, r11 = r01 + 1;
                        int xa = Math.Min(Math.Min(rowLo[r00], rowLo[r10]), Math.Min(rowLo[r01], rowLo[r11])) - 1;
                        int xb = Math.Max(Math.Max(rowHi[r00], rowHi[r10]), Math.Max(rowHi[r01], rowHi[r11]));
                        xa = Math.Max(0, xa); xb = Math.Min(nx - 2, xb);
                        int row = r00 * nx;
                        for (int x = xa; x <= xb; x++)
                        {
                            int c0 = row + x;
                            int mask = 0;
                            for (int kk = 0; kk < 8; kk++)
                            {
                                float v = field[c0 + (kk & 1) + ((kk >> 1) & 1) * sy + ((kk >> 2) & 1) * sz];
                                cv[kk] = v;
                                if (v > iso) mask |= 1 << kk;
                            }
                            if (mask == 0 || mask == 255) continue;
                            Vector3 sum = Vector3.Zero; int cnt = 0;
                            for (int e = 0; e < 12; e++)
                            {
                                int ea = EA[e], eb = EB[e];
                                if ((cv[ea] > iso) == (cv[eb] > iso)) continue;
                                float t = (iso - cv[ea]) / (cv[eb] - cv[ea]);
                                Vector3 pA = new Vector3(ea & 1, (ea >> 1) & 1, (ea >> 2) & 1), pB = new Vector3(eb & 1, (eb >> 1) & 1, (eb >> 2) & 1);
                                sum += pA + (pB - pA) * t; cnt++;
                            }
                            Vector3 f = sum / cnt;
                            // analytic gradient of the cell's trilinear field at f (+ trilinear field / aux for the mix)
                            float gx = 0f, gy = 0f, gz = 0f, fv = 0f, ax = 0f;
                            for (int kk = 0; kk < 8; kk++)
                            {
                                int bx = kk & 1, by = (kk >> 1) & 1, bz = (kk >> 2) & 1;
                                float wx = bx == 1 ? f.X : 1f - f.X, wy = by == 1 ? f.Y : 1f - f.Y, wz = bz == 1 ? f.Z : 1f - f.Z;
                                float c = cv[kk];
                                gx += (bx == 1 ? c : -c) * wy * wz;
                                gy += (by == 1 ? c : -c) * wx * wz;
                                gz += (bz == 1 ? c : -c) * wx * wy;
                                float w = wx * wy * wz;
                                fv += c * w;
                                ax += aux[c0 + bx + by * sy + bz * sz] * w;
                            }
                            Vector3 grad = new Vector3(gx, gy, gz);
                            float gl = grad.Length();
                            vid[c0] = sl.Pos.Count;
                            sl.Pos.Add(origin + (new Vector3(x, y, z) + f) * cell);
                            sl.Nrm.Add(gl > 1e-8f ? -grad / gl : Vector3.UnitY);
                            sl.Mix.Add(fv > 1e-6f ? ax / fv : 0f);
                        }
                    }
            });
            int total = 0;
            for (int k = 0; k < slabCount; k++) { slabs[k].Offset = total; total += slabs[k].Pos.Count; }
            for (int k = 0; k < slabCount; k++) { Positions.AddRange(slabs[k].Pos); Normals.AddRange(slabs[k].Nrm); Mix.AddRange(slabs[k].Mix); }
            RunSlabs(slabCount, k =>
            {
                int off = slabs[k].Offset;
                if (off == 0) return;
                int c0 = k * per * nx * ny, c1 = Math.Min(nz, (k + 1) * per) * nx * ny;
                for (int c = c0; c < c1; c++) if (vid[c] >= 0) vid[c] += off;
            });

            PMark(2);
            // pass 3: one quad per sign-changing grid edge, joining the 4 cells around it; the inside end of the edge
            // fixes the winding (outward = towards decreasing field)
            RunSlabs(slabCount, k =>
            {
                List<int> idx = slabs[k].Idx; idx.Clear();
                int z0 = Math.Max(1, k * per), z1 = Math.Min(nz - 1, (k + 1) * per);
                for (int z = z0; z < z1; z++)
                    for (int y = 1; y < ny - 1; y++)
                    {
                        int r = z * ny + y;
                        int xa = Math.Max(1, Math.Min(rowLo[r], Math.Min(rowLo[r + 1], rowLo[r + ny])) - 1);
                        int xb = Math.Min(nx - 2, Math.Max(rowHi[r], Math.Max(rowHi[r + 1], rowHi[r + ny])));
                        for (int x = xa; x <= xb; x++)
                        {
                            int c = r * nx + x;
                            bool inside = field[c] > iso;
                            if (inside != (field[c + 1] > iso)) Quad(idx, V(x, y - 1, z - 1), V(x, y, z - 1), V(x, y, z), V(x, y - 1, z), inside);
                            if (inside != (field[c + nx] > iso)) Quad(idx, V(x - 1, y, z - 1), V(x, y, z - 1), V(x, y, z), V(x - 1, y, z), !inside);
                            if (inside != (field[c + nx * ny] > iso)) Quad(idx, V(x - 1, y - 1, z), V(x, y - 1, z), V(x, y, z), V(x - 1, y, z), inside);
                        }
                    }
            });
            for (int k = 0; k < slabCount; k++) Indices.AddRange(slabs[k].Idx);
            PMark(3);
        }

        private static void RunSlabs(int count, Action<int> body)
        {
            if (count <= 1 || !Par.Enabled) { for (int k = 0; k < count; k++) body(k); return; }
            Parallel.For(0, count, body);
        }

        private int V(int x, int y, int z) => vid[(z * ny + y) * nx + x];

        private void Quad(List<int> idx, int a, int b, int c, int d, bool flip)
        {
            if (a < 0 || b < 0 || c < 0 || d < 0) return;
            if (CheckWinding)
            {
                Vector3 fn = Vector3.Cross(Positions[b] - Positions[a], Positions[c] - Positions[a]);
                Vector3 vn = Normals[a] + Normals[b] + Normals[c] + Normals[d];
                System.Threading.Interlocked.Increment(ref WindingChecked);
                if ((Vector3.Dot(fn, vn) < 0f) == flip) System.Threading.Interlocked.Increment(ref WindingMismatch);
            }
            if (!flip) { (b, d) = (d, b); }
            idx.Add(a); idx.Add(b); idx.Add(c);
            idx.Add(a); idx.Add(c); idx.Add(d);
        }

        /// <summary>Typical interior field value of a particle cloud at this spacing (for picking the iso level).</summary>
        public static float InteriorValue(float spacing, float radius)
        {
            float sum = 0f, R2 = radius * radius;
            int rc = (int)MathF.Ceiling(radius / spacing);
            for (int z = -rc; z <= rc; z++)
                for (int y = -rc; y <= rc; y++)
                    for (int x = -rc; x <= rc; x++)
                    {
                        float r2 = (x * x + y * y + z * z) * spacing * spacing;
                        if (r2 >= R2) continue;
                        float k = 1f - r2 / R2; sum += k * k * k;
                    }
            return sum;
        }
    }

    /// <summary>In-game driver: steps the body and rebuilds its surfaces on a worker task while the engine draws the
    /// previous result (one frame of latency). The main thread only copies bone matrices in and reads the front
    /// buffers out; nothing here touches engine objects, so it is safe off the main thread under IL2CPP.</summary>
    public sealed class FluidRunner
    {
        public readonly FluidBody Body;
        public readonly byte[] SurfaceElems;
        public SurfaceNets[] Front, Back;
        public readonly List<Sprite> FrontSprites = new List<Sprite>();
        private readonly List<Sprite> backSprites = new List<Sprite>();
        private Affine[] bones = Array.Empty<Affine>();
        private System.Threading.Tasks.Task job;
        private float jobDt; private int jobSteps;
        public double LastJobMs;
        public int Frames, Skipped;
        public int MaxCatchUpSteps = 3;
        /// <summary>Runs on the worker after the surfaces are built (managed data only: fill engine-layout staging here,
        /// so the main thread only bulk-copies). Reads <see cref="Back"/>.</summary>
        public Action PostWork;
        /// <summary>Runs on the caller's (main) thread right after <see cref="Collect"/> swaps the buffers.</summary>
        public Action Swapped;
        private float pending;   // simulated time owed by kicks that found the job still running

        public FluidRunner(FluidBody body, byte[] surfaceElems, Func<SurfaceNets> makeNets)
        {
            Body = body; SurfaceElems = surfaceElems;
            Front = new SurfaceNets[surfaceElems.Length]; Back = new SurfaceNets[surfaceElems.Length];
            for (int k = 0; k < surfaceElems.Length; k++) { Front[k] = makeNets(); Back[k] = makeNets(); }
        }

        public bool Busy => job != null && !job.IsCompleted;

        /// <summary>Starts a job for <paramref name="steps"/> steps of <paramref name="dt"/>; false while the last one runs.</summary>
        public bool TryKick(Affine[] boneWorld, float dt, int steps)
        {
            if (Busy) { Skipped++; pending += dt * steps; return false; }
            if (job != null) Collect();
            if (bones.Length != boneWorld.Length) bones = new Affine[boneWorld.Length];
            Array.Copy(boneWorld, bones, boneWorld.Length);
            // catch up the time a late job cost, a bounded number of extra steps at a time
            int extra = Math.Min(MaxCatchUpSteps, (int)(pending / dt));
            pending = Math.Min(pending - extra * dt, dt * MaxCatchUpSteps);
            jobDt = dt; jobSteps = steps + extra;
            job = System.Threading.Tasks.Task.Run(Work);
            return true;
        }

        private void Work()
        {
            long t0 = System.Diagnostics.Stopwatch.GetTimestamp();
            for (int k = 0; k < jobSteps; k++) Body.Step(jobDt, bones);
            FluidBody b = Body;
            for (int k = 0; k < SurfaceElems.Length; k++)
            {
                byte e = SurfaceElems[k];
                Back[k].Build(b, i => b.Elem[i] == e && b.Phase[i] == FluidBody.Bound ? 1f : 0f, i => b.Temp[i]);
            }
            backSprites.Clear(); backSprites.AddRange(b.Sprites);
            PostWork?.Invoke();
            LastJobMs = (System.Diagnostics.Stopwatch.GetTimestamp() - t0) * 1000.0 / System.Diagnostics.Stopwatch.Frequency;
        }

        /// <summary>If the job finished, swaps it to the front buffers (rethrowing any job exception) and returns true.</summary>
        public bool Collect()
        {
            if (job == null || !job.IsCompleted) return false;
            job.GetAwaiter().GetResult();
            job = null;
            (Front, Back) = (Back, Front);
            FrontSprites.Clear(); FrontSprites.AddRange(backSprites);
            Frames++;
            Swapped?.Invoke();
            return true;
        }

        public void Wait() { job?.Wait(); }
    }
}
