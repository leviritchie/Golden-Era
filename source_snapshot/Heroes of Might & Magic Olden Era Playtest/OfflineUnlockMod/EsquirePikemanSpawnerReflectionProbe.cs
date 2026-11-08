using System;
using System.Linq;
using System.Reflection;
using BepInEx.Logging;
using Hex.Configs;

namespace OfflineUnlockMod;

/// <summary>One-time reflection over <c>Hex.UI.UiModelsSpawner</c> for future narrow-hook work (see ESQUIRE_STOCK_VISUAL_CONTRACT.md).</summary>
internal static class EsquirePikemanSpawnerReflectionProbe
{
	internal static void TryRun(ManualLogSource log)
	{
		if (log == null)
			return;
		try
		{
			var asm = typeof(ObjCityConfig).Assembly;
			var t = asm.GetType("Hex.UI.UiModelsSpawner", false);
			if (t == null)
			{
				log.LogWarning(
					"EsquirePikeman probe: type Hex.UI.UiModelsSpawner not found in Hex assembly (build may have renamed it).");
				return;
			}

			const BindingFlags f = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance
				| BindingFlags.Static | BindingFlags.DeclaredOnly;
			var spawnLike = t.GetMethods(f)
				.Where(m => m.Name.IndexOf("Spawn", StringComparison.Ordinal) >= 0)
				.OrderBy(m => m.MetadataToken)
				.ToList();
			if (spawnLike.Count == 0)
			{
				log.LogWarning("EsquirePikeman probe: no methods with 'Spawn' in name on UiModelsSpawner.");
				return;
			}

			log.LogInfo("EsquirePikeman probe: Hex.UI.UiModelsSpawner methods containing 'Spawn':");
			for (var i = 0; i < spawnLike.Count; i++)
			{
				var m = spawnLike[i];
				var ps = string.Join(
					", ",
					m.GetParameters().Select(p => p.ParameterType.Name + " " + p.Name));
				log.LogInfo("  " + m.Name + "(" + ps + ") ret=" + m.ReturnType.Name);
			}
		}
		catch (Exception ex)
		{
			log.LogWarning("EsquirePikeman probe failed: " + ex.Message);
		}
	}
}
