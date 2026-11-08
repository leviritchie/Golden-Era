using System;
using System.IO;
using BepInEx;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Battle;

namespace OfflineUnlockMod;

/// <summary>
/// Diagnostic probe to trace Warcry ability wrapper initialization.
///
/// Enabled via flag file: <c>warcry_wrapper_probe.flag</c> in the OfflineUnlockMod plugin directory.
/// </summary>
internal static class Homm3WarcryWrapperProbe
{
    private const string FlagFileName = "warcry_wrapper_probe.flag";
    private static bool _patched;
    private static ManualLogSource _log;
    private static int _initLogged;
    private static int _extractLogged;

    private static bool IsEnabled()
    {
        return File.Exists(Path.Combine(Paths.GameRootPath, "BepInEx", "plugins", "OfflineUnlockMod", FlagFileName));
    }

    internal static void TryRegister(Harmony h, ManualLogSource log)
    {
        if (_patched || h == null || !IsEnabled())
            return;

        _log = log;

        try
        {
            // BhUnitAbilityView binding probe is intentionally disabled; the old typed wrapper fields were removed.
            var bindMethod = AccessTools.Method(typeof(BhUnitAbilityView), "beiq");
            if (bindMethod != null)
                log.LogInfo("[WarcryWrapperProbe] BhUnitAbilityView.befk candidate found; typed wrapper bind probe remains disabled.");
            else
                log.LogWarning("[WarcryWrapperProbe] BhUnitAbilityView.befk not found.");

            var initializerType = FindRuntimeType(GameSymbols.WarcryHeroAbility.WrapperProbeLegacyInitializerTypeNames);
            var initializerCtor = initializerType == null ? null : AccessTools.Constructor(initializerType);
            if (initializerCtor != null)
            {
                h.Patch(initializerCtor,
                    postfix: new HarmonyMethod(typeof(Homm3WarcryWrapperProbe), nameof(PostfixEkjConstruct)));
                log.LogInfo("[WarcryWrapperProbe] postfix on legacy initializer .ctor() registered.");
            }

            var initializerInit = initializerType == null ? null : AccessTools.Method(initializerType, "Init");
            if (initializerInit != null)
            {
                h.Patch(initializerInit,
                    postfix: new HarmonyMethod(typeof(Homm3WarcryWrapperProbe), nameof(PostfixEkjInit)));
                log.LogInfo("[WarcryWrapperProbe] postfix on legacy initializer Init() registered.");
            }

            _patched = true;
        }
        catch (Exception ex)
        {
            log.LogError("[WarcryWrapperProbe] registration failed: " + ex);
        }
    }

    private static void PostfixEkjConstruct(object __instance)
    {
        const int limit = 20;
        if (_initLogged >= limit)
            return;
        _initLogged++;

        try
        {
            _log?.LogInfo(
                $"[WarcryWrapper.legacy.ctor #{_initLogged}] " +
                $"type={__instance?.GetType()?.FullName} " +
                $"stack={Environment.StackTrace?.Truncate(300)}");
        }
        catch (Exception ex)
        {
            _log?.LogWarning($"[WarcryWrapper.legacy.ctor] error: {ex.Message}");
        }
    }

    private static void PostfixEkjInit(object __instance)
    {
        const int limit = 20;
        if (_extractLogged >= limit)
            return;
        _extractLogged++;

        try
        {
            _log?.LogInfo(
                $"[WarcryWrapper.legacy.Init #{_extractLogged}] " +
                $"type={__instance?.GetType()?.FullName} " +
                $"stack={Environment.StackTrace?.Truncate(300)}");
        }
        catch (Exception ex)
        {
            _log?.LogWarning($"[WarcryWrapper.legacy.Init] error: {ex.Message}");
        }
    }

    private static Type FindRuntimeType(string[] typeNames)
    {
        if (typeNames == null)
            return null;
        var asm = typeof(BhUnitAbilityView).Assembly;
        foreach (var typeName in typeNames)
        {
            if (string.IsNullOrWhiteSpace(typeName))
                continue;
            try
            {
                var type = asm.GetType(typeName, throwOnError: false) ?? ModActions.GetHexType(typeName);
                if (type != null)
                    return type;
            }
            catch
            {
            }
        }
        return null;
    }

    private static string Truncate(this string s, int max)
    {
        if (string.IsNullOrEmpty(s) || s.Length <= max)
            return s;
        return s[..max] + "...";
    }
}
