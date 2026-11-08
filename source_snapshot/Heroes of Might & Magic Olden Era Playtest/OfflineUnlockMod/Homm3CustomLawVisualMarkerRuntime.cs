using System;

namespace OfflineUnlockMod;

/// <summary>
/// Applies visible custom law marker buff state for runtime bookkeeping and
/// player/debug proof. Markers are added through the exact native buff manager,
/// dispatch the native buff event so the icon surface can update, and are
/// verified by has-by-SID before the law treats them as active.
/// </summary>
internal static class Homm3CustomLawVisualMarkerRuntime
{
	internal const string AvengerIntensity = GameSymbols.RampartAvengerLaws.CustomMarkerBuffSid;
	internal const string AvengerReprisal = "homm3_law_marker_avenger_reprisal";
	internal const string BurningAsh = "homm3_law_marker_burning_ash";
	internal const string StrongholdBloodFeud = "homm3_law_marker_blood_feud";
	internal const string ConfluxBacklash = "homm3_law_marker_elemental_backlash";
	internal const string NecropolisDeathGrip = "homm3_law_marker_death_grip";
	internal const string DungeonOutnumber = "homm3_law_marker_outnumber";
	internal const string FortressThornedHidesArmed = "homm3_law_marker_thorned_hides_armed";
	internal const string FortressThornedHidesWeakness = "homm3_law_marker_thorned_hides_weakness";

	private const int LogCap = 96;
	private static int _logged;

	internal static bool TryApplyUnitMarker(object unit, string markerSid, int level, int duration, string source)
	{
		if (unit == null)
		{
			LogLimited("HoMM3 custom law marker skipped: unit is null markerSid=" + (markerSid ?? "null") + " source=" + (source ?? "null") + ".");
			return false;
		}
		if (string.IsNullOrWhiteSpace(markerSid))
		{
			LogLimited("HoMM3 custom law marker skipped: marker SID is empty source=" + (source ?? "null") + ".");
			return false;
		}
		var safeLevel = Math.Max(1, level);
		var safeDuration = Math.Max(1, duration);
		if (!Homm3BuffDebuffNativeAdapter.TryAddBuffSidFromReceiver(
			    unit,
			    markerSid,
			    unit,
			    safeLevel,
			    safeDuration,
			    safeLevel,
			    refresh: true,
			    out var info,
			    out var failReason))
		{
			LogLimited("HoMM3 custom law marker failed closed: markerSid=" + markerSid + " source=" + (source ?? "null") + " reason=" + failReason + ".");
			return false;
		}
		LogLimited("HoMM3 custom law marker applied: markerSid=" + markerSid + " level=" + safeLevel + " duration=" + safeDuration + " source=" + (source ?? "null") + " status={" + info + "}.");
		return true;
	}

	private static void LogLimited(string message)
	{
		Homm3CandidateSurfaceRuntimeCounters.Record(message);
		if (_logged >= LogCap)
			return;
		_logged++;
		Plugin.LogSource?.LogInfo(message);
	}
}

