using System;
using System.Collections;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Step 1 feasibility spike for native HeroAbilityConfig injection.
/// One-shot: reach the configs holder cjv, read cju&lt;HeroAbilityConfig, string&gt; bxnh,
/// and dump every loaded ability sid so we can identify a Dungeon warcry to clone for
/// homm3_stronghold_ability_{moral,luck,initiative}. Read-only — no mutation yet.
/// </summary>
internal static class Homm3WarcryConfigInjectorProbe
{
	private static bool _registered;
	private static int _dumpAttempts;
	private static bool _dumped;
	private const int MaxAttempts = 200;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered)
			return;
		_registered = true;

		try
		{
			var postfix = AccessTools.Method(typeof(Homm3WarcryConfigInjectorProbe), nameof(TriggerDump));
			TryAttach(harmony, log, postfix, "cjv", "rtp");
			TryAttachPropertyGetter(harmony, log, postfix, "cjv", "cnaq");
			TryAttachSoFractionsLookup(harmony, log, postfix);
			TryDumpOnce(log, "register");
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3WarcryConfigInjectorProbe: register failed: " + ex.Message);
		}
	}

	private static void TriggerDump(MethodBase __originalMethod, object __instance, object __result)
	{
		var site = (__originalMethod?.DeclaringType?.Name ?? "?") + "." + (__originalMethod?.Name ?? "?");
		var holder = __result ?? __instance;
		if (holder != null && _capturedHolder == null && holder.GetType().Name == "cjv")
		{
			_capturedHolder = holder;
			Plugin.LogSource?.LogInfo("Homm3WarcryConfigInjectorProbe: captured cjv holder via " + site + ".");
		}
		if (holder != null)
			TryDumpWithHolder(Plugin.LogSource, site, holder);
		else
			TryDumpOnce(Plugin.LogSource, site);
	}

	private static void TryDumpWithHolder(ManualLogSource log, string site, object holder)
	{
		if (_dumped)
			return;
		try
		{
			var cjvType = holder.GetType();
			if (cjvType.Name != "cjv")
			{
				// Walk to base type that has bxnh.
				for (var t = cjvType; t != null; t = t.BaseType)
				{
					if (AccessTools.Field(t, "bxnh") != null)
					{
						cjvType = t;
						break;
					}
				}
			}
			DumpFromHolder(log, site, cjvType, holder);
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3WarcryConfigInjectorProbe[" + site + "]: holder-dump failed: " + ex.Message);
		}
	}

	private static void TryAttachAllCjvInstanceMethods(Harmony harmony, ManualLogSource log, MethodInfo postfix)
	{
		try
		{
			var t = AccessTools.TypeByName("cjv");
			if (t == null)
				return;
			var hooked = 0;
			foreach (var m in t.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
			{
				if (m.IsSpecialName)
					continue;
				if (m.GetParameters().Length != 0)
					continue;
				if (m.ReturnType != typeof(void))
					continue;
				try
				{
					harmony.Patch(m, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
					hooked++;
				}
				catch { }
			}
			log?.LogInfo("Homm3WarcryConfigInjectorProbe: hooked " + hooked + " cjv parameterless instance method(s).");
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3WarcryConfigInjectorProbe: cjv instance scan failed: " + ex.Message);
		}
	}

	private static void TryAttachSoFractionsLookup(Harmony harmony, ManualLogSource log, MethodInfo postfix)
	{
		try
		{
			var t = AccessTools.TypeByName("Hex.GameHub.UICommon.SoFractions");
			if (t == null)
			{
				log?.LogInfo("Homm3WarcryConfigInjectorProbe: type not found 'Hex.GameHub.UICommon.SoFractions'.");
				return;
			}
			var hooked = 0;
			foreach (var m in t.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
			{
				if (m.IsSpecialName)
					continue;
				var ps = m.GetParameters();
				if (ps.Length != 1 || ps[0].ParameterType != typeof(string))
					continue;
				if (m.ReturnType == typeof(void))
					continue;
				try
				{
					harmony.Patch(m, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
					hooked++;
				}
				catch (Exception ex)
				{
					log?.LogWarning("Homm3WarcryConfigInjectorProbe: SoFractions." + m.Name + " patch failed: " + ex.Message);
				}
			}
			log?.LogInfo("Homm3WarcryConfigInjectorProbe: hooked " + hooked + " SoFractions string-lookup method(s).");
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3WarcryConfigInjectorProbe: SoFractions attach failed: " + ex.Message);
		}
	}

	private static void TryAttachPropertyGetter(Harmony harmony, ManualLogSource log, MethodInfo postfix, string typeName, string propertyName)
	{
		if (postfix == null)
			return;
		try
		{
			var t = AccessTools.TypeByName(typeName);
			if (t == null)
			{
				log?.LogInfo("Homm3WarcryConfigInjectorProbe: type not found '" + typeName + "' (prop " + propertyName + ").");
				return;
			}
			var getter = AccessTools.PropertyGetter(t, propertyName);
			if (getter == null)
			{
				log?.LogInfo("Homm3WarcryConfigInjectorProbe: property getter not found '" + typeName + "." + propertyName + "'.");
				return;
			}
			harmony.Patch(getter, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
			log?.LogInfo("Homm3WarcryConfigInjectorProbe: hooked " + typeName + ".get_" + propertyName + ".");
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3WarcryConfigInjectorProbe: getter attach failed " + typeName + "." + propertyName + ": " + ex.Message);
		}
	}

	private static void TryAttach(Harmony harmony, ManualLogSource log, MethodInfo postfix, string typeName, string methodName)
	{
		if (postfix == null)
			return;
		try
		{
			var t = AccessTools.TypeByName(typeName);
			if (t == null)
			{
				log?.LogInfo("Homm3WarcryConfigInjectorProbe: type not found '" + typeName + "'.");
				return;
			}
			var m = AccessTools.Method(t, methodName);
			if (m == null)
			{
				log?.LogInfo("Homm3WarcryConfigInjectorProbe: method not found '" + typeName + "." + methodName + "'.");
				return;
			}
			harmony.Patch(m, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
			log?.LogInfo("Homm3WarcryConfigInjectorProbe: hooked " + typeName + "." + methodName + ".");
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3WarcryConfigInjectorProbe: attach failed " + typeName + "." + methodName + ": " + ex.Message);
		}
	}

	private static void TryDumpOnce(ManualLogSource log, string site)
	{
		if (_dumped)
			return;

		try
		{
			var cjvType = AccessTools.TypeByName("cjv");
			if (cjvType == null)
				return;

			var holder = ResolveHolder(cjvType);
			if (holder == null)
			{
				// Throttle "not yet" logs to one in every 250 fires so we still get a heartbeat.
				_dumpAttempts++;
				if (_dumpAttempts <= 3 || _dumpAttempts % 250 == 0)
					log?.LogInfo("Homm3WarcryConfigInjectorProbe[" + site + "]: cjv singleton not available yet (attempt " + _dumpAttempts + ").");
				return;
			}

			DumpFromHolder(log, site, cjvType, holder);
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3WarcryConfigInjectorProbe[" + site + "]: dump failed: " + ex.Message);
		}
	}

	private static void DumpFromHolder(ManualLogSource log, string site, Type cjvType, object holder)
	{
		try
		{
			var bxnh = AccessTools.Field(cjvType, "bxnh")?.GetValue(holder);
			if (bxnh == null)
			{
				log?.LogInfo("Homm3WarcryConfigInjectorProbe[" + site + "]: bxnh null on cjv (attempt " + _dumpAttempts + ").");
				return;
			}

			var listProp = AccessTools.Property(bxnh.GetType(), "bxkw");
			var list = listProp?.GetValue(bxnh) as IEnumerable
				?? AccessTools.Field(bxnh.GetType(), "<bxkw>k__BackingField")?.GetValue(bxnh) as IEnumerable
				?? AccessTools.Field(bxnh.GetType(), "_bxkw_k__BackingField")?.GetValue(bxnh) as IEnumerable;

			if (list == null)
			{
				log?.LogWarning("Homm3WarcryConfigInjectorProbe[" + site + "]: HeroAbilityConfig list (bxkw) not reachable on " + bxnh.GetType().FullName + ".");
				return;
			}

			var total = 0;
			var warcryHits = 0;
			foreach (var cfg in list)
			{
				if (cfg == null)
					continue;
				total++;
				var sid = TryGetSid(cfg);
				if (sid == null)
					continue;
				if (sid.IndexOf("ability_moral", StringComparison.OrdinalIgnoreCase) >= 0
					|| sid.IndexOf("ability_luck", StringComparison.OrdinalIgnoreCase) >= 0
					|| sid.IndexOf("ability_initiative", StringComparison.OrdinalIgnoreCase) >= 0
					|| sid.IndexOf("warcry", StringComparison.OrdinalIgnoreCase) >= 0
					|| sid.IndexOf("dungeon", StringComparison.OrdinalIgnoreCase) >= 0)
				{
					warcryHits++;
					log?.LogInfo("Homm3WarcryConfigInjectorProbe: HeroAbilityConfig candidate sid='" + sid + "' type=" + cfg.GetType().Name + ".");
				}
			}

			log?.LogInfo("Homm3WarcryConfigInjectorProbe[" + site + "]: dumped " + total + " HeroAbilityConfig entries, " + warcryHits + " warcry/dungeon candidates.");
			_dumped = true;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3WarcryConfigInjectorProbe[" + site + "]: dump-from-holder failed: " + ex.Message);
		}
	}

	private static object _capturedHolder;

	private static object ResolveHolder(Type cjvType)
	{
		if (_capturedHolder != null)
			return _capturedHolder;
		try
		{
			var fld = AccessTools.Field(cjvType, "bxky");
			if (fld != null && fld.IsStatic)
			{
				var v = fld.GetValue(null);
				if (v != null)
					return v;
			}
		}
		catch { }
		return null;
	}

	private static string TryGetSid(object cfg)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		for (var t = cfg.GetType(); t != null; t = t.BaseType)
		{
			foreach (var name in new[] { "sid", "id", "_sid", "_id", "<sid>k__BackingField", "<id>k__BackingField" })
			{
				FieldInfo f;
				try { f = t.GetField(name, flags); }
				catch { f = null; }
				if (f != null)
				{
					try
					{
						var v = f.GetValue(cfg);
						if (v is string s && s.Length > 0)
							return s;
					}
					catch { }
				}
			}
			foreach (var pname in new[] { "sid", "id", "cnaw" })
			{
				PropertyInfo p;
				try { p = t.GetProperty(pname, flags); }
				catch { p = null; }
				if (p != null && p.CanRead)
				{
					try
					{
						var v = p.GetValue(cfg);
						if (v is string s && s.Length > 0)
							return s;
					}
					catch { }
				}
			}
		}
		return null;
	}
}
