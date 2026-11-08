using System;
using Hex.Configs;

namespace OfflineUnlockMod;

/// <summary>
/// A few damage previews call into native code on battle <see cref="Unit"/> in ways that are unsafe
/// (e.g. <c>Unit.bcba</c> AV) while still not being useful histogram targets. For those, we pass
/// <c>null</c> receivers into <see cref="DamageDistribution"/> so the forward PMF still uses
/// <c>DamageUiParams</c>, the forecast, and bajp stats, but stack-kill mapping stays forecast-based only.
/// </summary>
internal static class DamageHistogramCastBlocklist
{
	/// <summary>Matched against <see cref="CastDealerConfig.attackPatternSid"/> (any substring, case-insensitive)</summary>
	private static readonly string[] s_forecastOnlyByAttackPatternSidFragment =
	{
		// "Basic Summon Swarm" (tweak the fragments if a future build renames the sid)
		"basic_summon",
		"summon_swarm",
		"summonswarm"
	};

	/// <summary>Optional: add known cast-source <c>zzr</c> ids from the same build if string matching is insufficient</summary>
	private static readonly int[] s_forecastOnlyZzr = Array.Empty<int>();

	internal static bool IsForecastOnlyKillStackMapping(object castSource)
	{
		if (castSource == null)
		{
			return false;
		}

		if (ZzrInBlocklist(castSource))
		{
			return true;
		}

		return AnyAttackPatternSidMatches(castSource, s_forecastOnlyByAttackPatternSidFragment);
	}

	private static bool ZzrInBlocklist(object castSource)
	{
		if (s_forecastOnlyZzr == null
		    || s_forecastOnlyZzr.Length == 0)
		{
			return false;
		}

		if (!DamageHistogramCastSourceInfo.TryReadCastSourceId(castSource, out var id))
		{
			return false;
		}

		foreach (var b in s_forecastOnlyZzr)
		{
			if (b == id)
			{
				return true;
			}
		}

		return false;
	}

	private static bool AnyAttackPatternSidMatches(object castSource, string[] fragments)
	{
		var sids = DamageHistogramCastSourceInfo.CollectAttackPatternSids(castSource);
		foreach (var sid in sids)
		{
			if (string.IsNullOrEmpty(sid))
			{
				continue;
			}

			foreach (var frag in fragments)
			{
				if (string.IsNullOrEmpty(frag))
				{
					continue;
				}

				if (sid.IndexOf(frag, StringComparison.OrdinalIgnoreCase) >= 0)
				{
					return true;
				}
			}
		}

		return false;
	}
}
