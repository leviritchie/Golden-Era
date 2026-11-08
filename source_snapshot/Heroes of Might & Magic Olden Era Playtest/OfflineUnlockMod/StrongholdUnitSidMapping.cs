using System;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Battle;

namespace OfflineUnlockMod;

/// <summary>
/// Redirects unit SIDs for custom HoMM3 faction units during HUD/ability lookups
/// so the game's internal dictionaries resolve donor unit configs (icons, abilities, passives).
///
/// Pattern matches <see cref="SoFractionsCustomFactionAliasPatch"/>: before the engine method
/// runs, rewrite the unit SID to the registered donor SID. The original SID is restored after.
///
/// Donor mapping lives in <see cref="Homm3CustomFactionRegistry"/>. Do not add
/// donor-to-custom reverse maps here; donor collisions require faction/session context.
/// </summary>
internal static class StrongholdUnitSidMapping
{
    private static bool _patched;
    private static int _logged;
    private static int _loggedRestored;


    internal static bool TryGetDonorSid(string sid, out string donorSid)
    {
        return Homm3CustomFactionRegistry.TryGetDonorSid(sid, out donorSid);
    }

    internal static bool TryGetCustomSidForDonorInFaction(string donorSid, string factionSid, out string customSid)
    {
        return Homm3CustomFactionRegistry.TryGetCustomSidForDonorInFaction(donorSid, factionSid, out customSid);
    }

    /// <summary>
    /// Cached FieldInfo for Unit.sid backing field (Il2CPP: property may be get-only on the interop type).
    /// Harmony's <c>ref string</c> doesn't work on non-ref args, so we rewrite via reflection.
    /// </summary>
    private static bool _lookedUpSidSetter;

    internal static void TryRegister(Harmony h, ManualLogSource log)
    {
        if (_patched || h == null)
            return;

        try
        {
            var bdon = AccessTools.Method(typeof(BhSelectedUnitHud), ".ctor");
            if (bdon == null)
            {
                log?.LogWarning("StrongholdUnitSidMapping: BhSelectedUnitHud.bdon not found — SID alias inactive.");
                return;
            }

            h.Patch(bdon,
                prefix: new HarmonyMethod(typeof(StrongholdUnitSidMapping), nameof(PrefixBdon)),
                postfix: new HarmonyMethod(typeof(StrongholdUnitSidMapping), nameof(PostfixBdon)));
            _patched = true;
            log?.LogInfo("StrongholdUnitSidMapping: prefix/postfix on BhSelectedUnitHud.bdon registered (custom SID → donor alias).");
        }
        catch (Exception ex)
        {
            log?.LogError("StrongholdUnitSidMapping registration failed: " + ex);
        }
    }

    /// <summary>
    /// Before <c>bdon()</c> runs, if the unit SID is a custom Stronghold SID,
    /// rewrite it to the registered donor SID so internal dictionary lookups (icons, abilities, passives) resolve.
    /// Store the original SID on the unit so the postfix can restore it.
    /// </summary>
    private static void PrefixBdon(object __0, BattleEventArgs __1, ref string __state)
    {
        __state = null;
        try
        {
            Unit target = __1?.target;
            if (target == null)
                return;

            string originalSid = ReadUnitSid(target);
            if (string.IsNullOrEmpty(originalSid))
                return;

            if (!Homm3CustomFactionRegistry.TryGetDonorSid(originalSid, out var donorSid))
                return;

            __state = originalSid;
            WriteUnitSid(target, donorSid);

            if (_logged < 20)
            {
                _logged++;
                Plugin.LogSource?.LogInfo(
                    $"StrongholdUnitSidMapping: alias '{originalSid}' → '{donorSid}' for BhSelectedUnitHud.bdon");
            }
        }
        catch (Exception ex)
        {
            Plugin.LogSource?.LogWarning($"StrongholdUnitSidMapping prefix error: {ex.Message}");
        }
    }

    /// <summary>
    /// Restore only units rewritten by this prefix. Do not reverse-map donor SIDs:
    /// vanilla donor units can legitimately enter this HUD path too.
    /// </summary>
    private static void PostfixBdon(object __0, BattleEventArgs __1, string __state)
    {
        try
        {
            if (string.IsNullOrEmpty(__state))
                return;

            Unit target = __1?.target;
            if (target == null)
                return;

            string currentSid = ReadUnitSid(target);
            if (string.IsNullOrEmpty(currentSid))
                return;

            WriteUnitSid(target, __state);

            if (_loggedRestored < 10)
            {
                _loggedRestored++;
                Plugin.LogSource?.LogInfo(
                    $"StrongholdUnitSidMapping: restored '{currentSid}' -> '{__state}' after BhSelectedUnitHud.bdon");
            }
        }
        catch (Exception ex)
        {
            Plugin.LogSource?.LogWarning($"StrongholdUnitSidMapping postfix error: {ex.Message}");
        }
    }

    private static string ReadUnitSid(Unit unit)
    {
        if (unit == null)
            return null;

        try
        {
            // Try the interop property first
            var t = typeof(Unit);
            var prop = t.GetProperty("sid", BindingFlags.Public | BindingFlags.Instance);
            if (prop != null && prop.CanRead)
                return prop.GetValue(unit) as string;

            // Try backing field <sid>k__BackingField
            var backingField = t.GetField("<sid>k__BackingField", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            if (backingField != null)
                return backingField.GetValue(unit) as string;

            // Try raw field named "sid"
            var rawField = t.GetField("sid", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            if (rawField != null)
                return rawField.GetValue(unit) as string;

            return null;
        }
        catch
        {
            return null;
        }
    }

    private static void WriteUnitSid(Unit unit, string value)
    {
        if (unit == null)
            return;

        try
        {
            var t = typeof(Unit);

            // Try property setter first
            var prop = t.GetProperty("sid", BindingFlags.Public | BindingFlags.Instance);
            if (prop != null && prop.CanWrite)
            {
                prop.SetValue(unit, value);
                return;
            }

            // Try backing field
            var backingField = t.GetField("<sid>k__BackingField", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            if (backingField != null)
            {
                backingField.SetValue(unit, value);
                return;
            }

            // Try raw field
            var rawField = t.GetField("sid", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            if (rawField != null)
            {
                rawField.SetValue(unit, value);
                return;
            }

            // Cache the FieldInfo for future use (if found via different access)
            if (!_lookedUpSidSetter)
            {
                _lookedUpSidSetter = true;
                Plugin.LogSource?.LogWarning(
                    "StrongholdUnitSidMapping: Cannot find setter for Unit.sid. " +
                    "Property is read-only, no backing field found. SID alias will not work.");
            }
        }
        catch (Exception ex)
        {
            if (!_lookedUpSidSetter)
            {
                _lookedUpSidSetter = true;
                Plugin.LogSource?.LogWarning(
                    $"StrongholdUnitSidMapping: Failed to set Unit.sid: {ex.Message}. " +
                    "The game may crash with KeyNotFoundException if the finalizer is removed.");
            }
        }
    }
}
