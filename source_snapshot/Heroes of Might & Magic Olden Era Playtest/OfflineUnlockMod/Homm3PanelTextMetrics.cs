using System;
using System.Collections.Generic;

namespace OfflineUnlockMod;

/// <summary>
/// Deterministic text measuring for the mod's panels (no TMP calls): widths, greedy word-wrap line counts and line pitch
/// of the game's EN-Regular / EN-Medium / EN-Book fonts, from glyph advances in <c>Homm3PanelTextMetrics.g.cs</c>
/// (tools/factory_logistics/panel_text_metrics.py). The advances match the live game's TMP preferredWidth to 0.1 px.
/// TMP draws a line every <c>lineHeight</c> (EN-Medium about 1.97 x the size, EN-Regular 1.63 x), so a box sized with a
/// smaller pitch either overlaps the next text or, with Ellipsis overflow, has its lines cut.
/// Unknown fonts and glyphs fall back to a generous 0.6 em, which over-reserves room rather than overflowing.
/// Proof: source/static (sweep against the font export); the in-game layout is unproven until seen.
/// </summary>
internal static partial class Homm3PanelTextMetrics
{
	private const float UnknownAdvance = 0.6f;
	private const float UnknownLine = 2f;

	internal sealed class FontMetrics
	{
		internal readonly string Name;
		internal readonly float Line;
		internal readonly float Ascent;
		internal readonly float Descent;
		private readonly float[] _dense;
		private readonly Dictionary<char, float> _sparse = new();

		internal FontMetrics(string name, float line, float ascent, float descent, float[] dense, char[] sparseChars, float[] sparseAdvances)
		{
			Name = name;
			Line = line;
			Ascent = ascent;
			Descent = descent;
			_dense = dense;
			for (var i = 0; i < sparseChars.Length && i < sparseAdvances.Length; i++)
				_sparse[sparseChars[i]] = sparseAdvances[i];
		}

		internal float Advance(char c)
		{
			if (c >= 32 && c < 32 + _dense.Length)
			{
				var a = _dense[c - 32];
				return a >= 0f ? a : UnknownAdvance;
			}
			return _sparse.TryGetValue(c, out var s) ? s : UnknownAdvance;
		}
	}

	private static Dictionary<string, FontMetrics> _byName;

	private static FontMetrics Find(string font)
	{
		if (_byName == null)
		{
			var map = new Dictionary<string, FontMetrics>(StringComparer.Ordinal);
			foreach (var f in Generated)
				map[f.Name] = f;
			_byName = map;
		}
		return font != null && _byName.TryGetValue(font, out var m) ? m : null;
	}

	internal static bool Knows(string font) => Find(font) != null;

	/// <summary>Single-line width of <paramref name="text"/> (no rich text) at <paramref name="size"/>.</summary>
	internal static float Width(string font, float size, string text)
	{
		if (string.IsNullOrEmpty(text))
			return 0f;
		var f = Find(font);
		var em = 0f;
		foreach (var c in text)
			em += f != null ? f.Advance(c) : UnknownAdvance;
		return em * size;
	}

	/// <summary>Distance between two baselines (TMP's line advance with lineSpacing 0).</summary>
	internal static float LinePitch(string font, float size) => (Find(font)?.Line ?? UnknownLine) * size;

	/// <summary>Greedy word wrap at spaces (as TMP's Normal wrapping); a word wider than the box takes a line of its own.</summary>
	internal static List<string> Wrap(string font, float size, string text, float width)
	{
		var lines = new List<string>();
		foreach (var para in (text ?? "").Split('\n'))
		{
			var line = "";
			foreach (var word in para.Split(' '))
			{
				var candidate = line.Length == 0 ? word : line + " " + word;
				if (line.Length > 0 && Width(font, size, candidate) > width)
				{
					lines.Add(line);
					line = word;
				}
				else
				{
					line = candidate;
				}
			}
			lines.Add(line);
		}
		return lines;
	}

	internal static int Lines(string font, float size, string text, float width) => Math.Max(1, Wrap(font, size, text, width).Count);

	/// <summary>Height a box needs for <paramref name="lines"/> wrapped lines, drawn with Overflow (pitch per line plus a small margin).</summary>
	internal static float BlockHeight(string font, float size, int lines) => Math.Max(1, lines) * LinePitch(font, size) + 4f;
}
