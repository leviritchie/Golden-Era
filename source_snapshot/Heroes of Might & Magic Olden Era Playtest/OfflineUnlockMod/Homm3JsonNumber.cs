using System.Globalization;
using System.Text;

namespace OfflineUnlockMod;

// IL2CPP Newtonsoft formats a float JValue's ToString() with the game's current culture,
// so on ru-RU (and other decimal-comma locales) catalog numbers arrive as "47,5999984741211"
// even though the JSON on disk says 47.599998474121094. Accept that shape as well as invariant text.
internal static class Homm3JsonNumber
{
	internal static bool TryParseFloat(string text, out float value)
	{
		value = 0f;
		if (string.IsNullOrWhiteSpace(text))
			return false;
		if (float.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out value))
			return true;
		var normalized = NormalizeCultureDecimal(text);
		return normalized != null
		       && float.TryParse(normalized, NumberStyles.Float, CultureInfo.InvariantCulture, out value);
	}

	// One decimal comma (or Arabic decimal separator) -> '.', Unicode minus -> '-'.
	// Anything that looks grouped (a second separator, '.' plus ',', or a space-like group separator) is rejected.
	private static string NormalizeCultureDecimal(string text)
	{
		var trimmed = text.Trim();
		var sb = new StringBuilder(trimmed.Length);
		var sawDecimal = false;
		foreach (var c in trimmed)
		{
			switch (c)
			{
				case ',':
				case '٫':
					if (sawDecimal)
						return null;
					sawDecimal = true;
					sb.Append('.');
					break;
				case '.':
					return null;
				case '−':
					sb.Append('-');
					break;
				case ' ':
				case ' ':
				case ' ':
				case '\'':
					return null;
				default:
					sb.Append(c);
					break;
			}
		}
		return sawDecimal || sb.ToString() != trimmed ? sb.ToString() : null;
	}
}
