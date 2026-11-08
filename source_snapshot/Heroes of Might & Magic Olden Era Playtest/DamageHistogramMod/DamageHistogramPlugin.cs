using BepInEx;
using BepInEx.Logging;
using BepInEx.Unity.IL2CPP;
using HarmonyLib;

namespace OfflineUnlockMod;

[BepInPlugin(PluginGuid, PluginName, PluginVersion)]
public sealed class Plugin : BasePlugin
{
	internal const string PluginGuid = "levir.heroesoe.damagehistogram";
	internal const string PluginName = "HeroesOE Damage Histogram";
	internal const string PluginVersion = "0.1.0";

	internal static ManualLogSource LogSource;

	private Harmony _harmony;

	public override void Load()
	{
		LogSource = Log;
		var cfg = LauncherConfigReader.TryLoad();
		if (!cfg.DamageHistograms)
		{
			Log.LogInfo("Damage histogram disabled by config: " + LauncherConfigReader.LastResolvedModSettingsPath);
			return;
		}

		_harmony = new Harmony(PluginGuid);
		DamageHistogramBootstrap.Ensure();
		_ = DamageHistogramSettings.ShouldApplyPatches();
		DamageHistogramForecastRecorder.TryRegisterForecastPatches(_harmony);
		DamageHistogramForecastRecorder.TryRegisterPanelPatches(_harmony);
		Log.LogInfo(
			"Damage histogram plugin loaded: config="
			+ (string.IsNullOrEmpty(LauncherConfigReader.LastResolvedModSettingsPath) ? "none" : LauncherConfigReader.LastResolvedModSettingsPath)
			+ ", nativeFrame="
			+ cfg.DamageHistogramUseNativeFrameSprite
			+ ", panelUgui="
			+ cfg.DamageHistogramPanelUgui);
	}

	public override bool Unload()
	{
		_harmony?.UnpatchSelf();
		_harmony = null;
		DamageHistogramState.Clear();
		DamageHistogramSettings.InvalidateCache();
		return true;
	}
}
