using System;

namespace OfflineUnlockMod;

/// <summary>
/// Procedural Inferno Gating art (RGBA8, row 0 = bottom, like Texture2D). Deliberately Unity-free so the
/// same code renders the owner-review mockups offline (tools/inferno_gating_mockup) with identical pixels.
/// Loops: every animated set tiles in time (frame n wraps to frame 0 without a jump).
/// </summary>
internal static class Homm3InfernoGatingArt
{
	// ---------------------------------------------------------------- noise (tileable value noise)

	private static float Hash(int x, int y, int seed)
	{
		unchecked
		{
			var h = (uint)(x * 374761393 + y * 668265263 + seed * 1442695041);
			h = (h ^ (h >> 13)) * 1274126177u;
			h ^= h >> 16;
			return (h & 0xFFFFFF) / 16777215f;
		}
	}

	private static float Smooth(float t) => t * t * (3f - 2f * t);

	/// <summary>Value noise tiling with period (px, py) cells.</summary>
	private static float Noise(float x, float y, int px, int py, int seed)
	{
		var x0 = (int)Math.Floor(x);
		var y0 = (int)Math.Floor(y);
		var fx = Smooth(x - x0);
		var fy = Smooth(y - y0);
		int Wrap(int v, int p) => p <= 0 ? v : ((v % p) + p) % p;
		var a = Hash(Wrap(x0, px), Wrap(y0, py), seed);
		var b = Hash(Wrap(x0 + 1, px), Wrap(y0, py), seed);
		var c = Hash(Wrap(x0, px), Wrap(y0 + 1, py), seed);
		var d = Hash(Wrap(x0 + 1, px), Wrap(y0 + 1, py), seed);
		return Lerp(Lerp(a, b, fx), Lerp(c, d, fx), fy);
	}

	private static float Fbm(float x, float y, int px, int py, int seed)
	{
		return Noise(x, y, px, py, seed) * 0.6f
		       + Noise(x * 2f, y * 2f, px * 2, py * 2, seed + 17) * 0.28f
		       + Noise(x * 4f, y * 4f, px * 4, py * 4, seed + 41) * 0.12f;
	}

	private static float Lerp(float a, float b, float t) => a + (b - a) * t;
	private static float Clamp01(float v) => v < 0f ? 0f : v > 1f ? 1f : v;
	private static float SmoothStep(float e0, float e1, float v) => Smooth(Clamp01((v - e0) / (e1 - e0)));

	/// <summary>Fire ramp: heat 0..1 -> premultiplied-free RGBA (alpha from heat).</summary>
	private static void Fire(float heat, out float r, out float g, out float b, out float a)
	{
		heat = Clamp01(heat);
		// ember red -> orange -> amber -> pale yellow core
		r = Clamp01(0.35f + heat * 1.6f);
		g = Clamp01((heat - 0.25f) * 1.45f);
		b = Clamp01((heat - 0.72f) * 2.2f);
		a = SmoothStep(0.06f, 0.42f, heat);
	}

	private static void Put(byte[] px, int w, int x, int y, float r, float g, float b, float a)
	{
		var i = (y * w + x) * 4;
		px[i] = (byte)(Clamp01(r) * 255f + 0.5f);
		px[i + 1] = (byte)(Clamp01(g) * 255f + 0.5f);
		px[i + 2] = (byte)(Clamp01(b) * 255f + 0.5f);
		px[i + 3] = (byte)(Clamp01(a) * 255f + 0.5f);
	}

	/// <summary>Signed distance to an axis-aligned rounded box centred at 0 (half extents hx, hy, radius rr).</summary>
	private static float BoxDistance(float x, float y, float hx, float hy, float rr)
	{
		var qx = Math.Abs(x) - hx + rr;
		var qy = Math.Abs(y) - hy + rr;
		var ox = Math.Max(qx, 0f);
		var oy = Math.Max(qy, 0f);
		return (float)Math.Sqrt(ox * ox + oy * oy) + Math.Min(Math.Max(qx, qy), 0f) - rr;
	}

	// ---------------------------------------------------------------- army-strip frame

	/// <summary>
	/// Burning frame for a reserved army slot. The slot portrait sits in the clear middle; flames lick
	/// upward off the border (taller along the top edge) and loop over <paramref name="frames"/>.
	/// </summary>
	internal static byte[] FlameFrame(int size, int frame, int frames)
	{
		var px = new byte[size * size * 4];
		var phase = frame / (float)Math.Max(1, frames);
		const int periodY = 4;
		for (var y = 0; y < size; y++)
		{
			for (var x = 0; x < size; x++)
			{
				var u = (x + 0.5f) / size * 2f - 1f; // -1..1
				var v = (y + 0.5f) / size * 2f - 1f;
				var d = BoxDistance(u, v + 0.06f, 0.74f, 0.70f, 0.16f); // inner slot box (portrait area)
				// flames rise: sample noise scrolling downward in texture space = moving up on screen
				var n = Fbm(u * 3.2f + 7f, v * 2.6f + 3f - phase * 3f, 0, 3, 5); // scrolls exactly one period per loop
				var up = Clamp01((v + 1f) * 0.5f); // 0 bottom .. 1 top
				var reach = 0.10f + 0.20f * n + 0.10f * up; // how far flames reach outward
				float heat;
				if (d < 0f)
					heat = Clamp01(1f + d / 0.05f) * 0.9f; // thin inner rim glow
				else
					heat = Clamp01(1f - d / reach) * (0.75f + 0.5f * n);
				// tongues above the top edge
				if (v > 0.6f && d > 0f)
				{
					var tongue = Fbm(u * 6f + 1f, v * 3f - phase * periodY, 0, periodY, 11);
					heat = Math.Max(heat, Clamp01((tongue - 0.35f) * 2.2f - (v - 0.6f) * 2.4f));
				}
				Fire(heat, out var r, out var g, out var b, out var a);
				Put(px, size, x, y, r, g, b, a);
			}
		}
		return px;
	}

	/// <summary>Reserved-but-closed slot: cold iron rim with dull ember cracks (static).</summary>
	internal static byte[] EmberSeal(int size)
	{
		var px = new byte[size * size * 4];
		for (var y = 0; y < size; y++)
		{
			for (var x = 0; x < size; x++)
			{
				var u = (x + 0.5f) / size * 2f - 1f;
				var v = (y + 0.5f) / size * 2f - 1f;
				var d = BoxDistance(u, v + 0.06f, 0.74f, 0.70f, 0.16f);
				// wide blackened-iron band with smouldering cracks and a low outer ember glow: must read as
				// "reserved" at a glance even though Gating is closed
				var band = SmoothStep(0f, 0.25f, Clamp01(1f - Math.Abs(d - 0.05f) / 0.075f));
				var crack = Clamp01((Fbm(u * 8f, v * 8f, 0, 0, 23) - 0.55f) * 5f) * band;
				var glow = d > 0.05f ? Clamp01(1f - (d - 0.05f) / 0.12f) * 0.45f : 0f;
				var rim = Clamp01(1f - Math.Abs(d - 0.05f) / 0.012f) * 0.5f; // bright iron edge line
				var r = Lerp(0.30f, 1.00f, crack) + rim * 0.5f;
				var g = Lerp(0.22f, 0.42f, crack) + rim * 0.3f;
				var b = Lerp(0.18f, 0.08f, crack) + rim * 0.15f;
				var a = Math.Max(band * 0.95f, glow);
				if (band < 0.05f && glow > 0f)
				{
					r = 0.85f;
					g = 0.28f;
					b = 0.06f;
				}
				Put(px, size, x, y, r, g, b, a);
			}
		}
		return px;
	}

	/// <summary>Round iron badge with a gate arch; lit = fire inside the arch.</summary>
	internal static byte[] GateIcon(int size, bool lit)
	{
		var px = new byte[size * size * 4];
		for (var y = 0; y < size; y++)
		{
			for (var x = 0; x < size; x++)
			{
				var u = (x + 0.5f) / size * 2f - 1f;
				var v = (y + 0.5f) / size * 2f - 1f;
				var rr = (float)Math.Sqrt(u * u + v * v);
				var disc = SmoothStep(1f, 0.92f, rr);
				var rim = SmoothStep(0.80f, 0.86f, rr) * disc;
				// arch: rectangle below y=0.05 plus semicircle above
				var ax = Math.Abs(u);
				var inArch = (v < 0.05f && v > -0.62f && ax < 0.40f) || (v >= 0.05f && u * u + (v - 0.05f) * (v - 0.05f) < 0.40f * 0.40f);
				var archEdge = inArch ? 1f : 0f;
				float r, g, b;
				if (inArch)
				{
					if (lit)
					{
						var heat = 0.55f + 0.45f * Clamp01(1f - (v + 0.62f) / 1.1f) + 0.2f * (Fbm(u * 5f, v * 5f, 0, 0, 3) - 0.5f);
						Fire(heat, out r, out g, out b, out _);
					}
					else
					{
						r = 0.20f; g = 0.07f; b = 0.05f;
					}
				}
				else
				{
					// iron
					var shade = 0.22f + 0.10f * (v * 0.5f + 0.5f);
					r = shade; g = shade * 0.92f; b = shade * 0.86f;
				}
				if (rim > 0f)
				{
					var gold = lit ? 1f : 0.55f;
					r = Lerp(r, 0.78f * gold, rim);
					g = Lerp(g, 0.52f * gold, rim);
					b = Lerp(b, 0.22f * gold, rim);
				}
				Put(px, size, x, y, r, g, b, disc * (archEdge > 0f || rim > 0f ? 1f : 0.96f));
			}
		}
		return px;
	}

	// ---------------------------------------------------------------- battle portal

	/// <summary>Camera-facing hellgate: a ring of fire around a slow crimson vortex (loops over frames).</summary>
	internal static byte[] PortalRing(int size, int frame, int frames)
	{
		var px = new byte[size * size * 4];
		var phase = frame / (float)Math.Max(1, frames);
		const int angularCells = 12;
		for (var y = 0; y < size; y++)
		{
			for (var x = 0; x < size; x++)
			{
				var u = (x + 0.5f) / size * 2f - 1f;
				var v = (y + 0.5f) / size * 2f - 1f;
				// slightly tall ellipse (a doorway, not a coin)
				var ex = u / 0.78f;
				var ey = v / 0.98f;
				var rr = (float)Math.Sqrt(ex * ex + ey * ey);
				var ang = (float)(Math.Atan2(ey, ex) / (2 * Math.PI) + 0.5); // 0..1
				// vortex interior: spiral bands rotating with phase
				var swirl = Fbm(ang * angularCells + rr * 6f - phase * angularCells, rr * 5f, angularCells, 0, 31);
				var interior = SmoothStep(0.80f, 0.55f, rr);
				var vr = Lerp(0.18f, 0.80f, swirl) * (0.55f + 0.45f * (1f - rr));
				var vg = Lerp(0.02f, 0.18f, swirl * swirl) * (1f - rr);
				var vb = 0.02f + 0.05f * (1f - rr);
				var va = interior * (0.78f + 0.2f * swirl);
				// fire ring: noisy band around rr ~0.82, tongues flare outward + upward
				var flick = Fbm(ang * angularCells * 1.5f, phase * 6f + rr * 2f, (int)(angularCells * 1.5f), 6, 47);
				var up = Clamp01(v * 0.5f + 0.5f);
				var band = 1f - Math.Abs(rr - 0.84f) / (0.08f + 0.14f * flick + 0.06f * up);
				var heat = Clamp01(band) * (0.7f + 0.6f * flick);
				Fire(heat, out var fr, out var fg, out var fb, out var fa);
				// composite fire over vortex
				var a = fa + va * (1f - fa);
				var r = a > 0f ? (fr * fa + vr * va * (1f - fa)) / a : 0f;
				var g = a > 0f ? (fg * fa + vg * va * (1f - fa)) / a : 0f;
				var b = a > 0f ? (fb * fa + vb * va * (1f - fa)) / a : 0f;
				Put(px, size, x, y, r, g, b, a);
			}
		}
		return px;
	}

	/// <summary>
	/// Army-strip gate: Portal-style orange light hugging the unit card's own rectangle (crisp white-hot edge,
	/// soft outer glow, faint swirling inner haze so the portrait stays readable). The texture is <paramref name="w"/> x
	/// <paramref name="h"/> at the card's aspect and covers the card plus <paramref name="margin"/> (fraction of the
	/// card width) on every side; energy runs round the edge and loops over <paramref name="frames"/>.
	/// </summary>
	internal static byte[] HudPortal(int w, int h, float margin, int frame, int frames)
	{
		var px = new byte[w * h * 4];
		var phase = frame / (float)Math.Max(1, frames);
		const int cells = 16;
		// work in card-width units: the card spans [-0.5, 0.5] x [-hy, hy]
		var span = 1f + 2f * margin;
		var hy = (h * span / w - 2f * margin) * 0.5f;
		const float corner = 0.07f;
		for (var y = 0; y < h; y++)
		{
			for (var x = 0; x < w; x++)
			{
				var cx = ((x + 0.5f) / w - 0.5f) * span;
				var cy = ((y + 0.5f) / h - 0.5f) * (h * span / w);
				var ang = (float)(Math.Atan2(cy / hy, cx / 0.5f) / (2 * Math.PI) + 0.5); // 0..1 round the card
				var wobble = (Fbm(ang * cells + phase * cells, phase * 4f, cells, 4, 61) - 0.5f) * 0.01f;
				var energy = Fbm(ang * cells - phase * cells * 2f, 0.5f, cells, 0, 73);
				var d = BoxDistance(cx, cy, 0.5f, hy, corner) - wobble; // <0 inside the card
				var core = (float)Math.Exp(-(d * d) / (2f * 0.010f * 0.010f));
				var band = (float)Math.Exp(-(d * d) / (2f * 0.028f * 0.028f));
				var glow = d > 0f ? (float)Math.Exp(-d / (margin * 0.4f)) : (float)Math.Exp(d / 0.11f);
				var lum = 0.75f + 0.5f * energy;
				var depth = Clamp01(-d / 0.35f); // 0 at the edge, 1 deep inside
				var swirl = Fbm(ang * 8f + depth * 4f + phase * 8f, depth * 3f, 8, 0, 89);
				var haze = d < 0f ? (1f - depth) * (0.10f + 0.22f * swirl) : 0f;
				var edgeFade = SmoothStep(margin * 0.98f, margin * 0.6f, Math.Max(Math.Abs(cx) - 0.5f, Math.Abs(cy) - hy));
				var a = Clamp01(core + band * 0.85f * lum + glow * 0.55f * lum + haze) * edgeFade;
				var hot = Clamp01(core * lum);
				var g = Lerp(Lerp(0.36f, 0.58f, Clamp01(band * lum)), 0.93f, hot);
				var bl = Lerp(Lerp(0.04f, 0.12f, Clamp01(band * lum)), 0.72f, hot);
				Put(px, w, x, y, 1f, g, bl, a);
			}
		}
		return px;
	}

	/// <summary>Ground sigil under the entry hex: burning circle, inner ring and eight brand marks (static; rotated in scene).</summary>
	internal static byte[] GroundSigil(int size)
	{
		var px = new byte[size * size * 4];
		for (var y = 0; y < size; y++)
		{
			for (var x = 0; x < size; x++)
			{
				var u = (x + 0.5f) / size * 2f - 1f;
				var v = (y + 0.5f) / size * 2f - 1f;
				var rr = (float)Math.Sqrt(u * u + v * v);
				var ang = Math.Atan2(v, u);
				var outer = Clamp01(1f - Math.Abs(rr - 0.90f) / 0.045f);
				var inner = Clamp01(1f - Math.Abs(rr - 0.66f) / 0.025f);
				var spoke = 0f;
				var k = ang / (Math.PI / 4) + 8;
				var frac = (float)(k - Math.Floor(k));
				if (rr > 0.68f && rr < 0.88f)
					spoke = Clamp01(1f - Math.Abs(frac - 0.5f) / 0.07f) * Clamp01(1f - Math.Abs(rr - 0.78f) / 0.09f);
				var scorch = SmoothStep(0.95f, 0.2f, rr) * 0.55f;
				var heat = Math.Max(Math.Max(outer, inner * 0.9f), spoke) * (0.8f + 0.2f * Fbm(u * 8f, v * 8f, 0, 0, 59));
				Fire(heat, out var r, out var g, out var b, out var a);
				// char under the lines
				var ca = scorch * (1f - a);
				var outA = a + ca;
				Put(px, size, x, y, outA > 0 ? (r * a + 0.06f * ca) / outA : 0, outA > 0 ? (g * a + 0.02f * ca) / outA : 0, outA > 0 ? (b * a + 0.01f * ca) / outA : 0, outA);
			}
		}
		return px;
	}

	/// <summary>Soft ember dot.</summary>
	internal static byte[] Ember(int size)
	{
		var px = new byte[size * size * 4];
		for (var y = 0; y < size; y++)
		{
			for (var x = 0; x < size; x++)
			{
				var u = (x + 0.5f) / size * 2f - 1f;
				var v = (y + 0.5f) / size * 2f - 1f;
				var rr = (float)Math.Sqrt(u * u + v * v);
				var heat = Clamp01(1f - rr) * 1.25f;
				Fire(heat, out var r, out var g, out var b, out var a);
				Put(px, size, x, y, r, g, b, a * Clamp01(1f - rr));
			}
		}
		return px;
	}
}
