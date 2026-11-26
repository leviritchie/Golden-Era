using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Battle;
using Il2CppInterop.Runtime.InteropTypes;
using DataHero = Hex.Session.Data.Hero;
using LogicHero = Hex.Session.Logic.Hero;

namespace OfflineUnlockMod;

/// <summary>
/// Mana Generator (Factory, <c>Build_Mother_Nature</c> in <c>homm3_factory_city</c>, a no-op row natively),
/// building pass 2026-11-22. In a siege of a Factory town that has it, the defending hero (garrisoned or
/// visiting) starts the battle with +20 current mana. When the battle result is applied (win, loss, retreat
/// or surrender), min(20, mana above the pre-battle value) is taken back, so unspent points are lost.
/// Hooks: BattleLogic.Init prefix (the transfer hero's mana, before Init copies it into battle state) and the
/// battles-manager ApplyBattleResult prefix/postfix (write-back to the world hero has happened by the postfix).
/// </summary>
internal static class Homm3FactoryManaGeneratorRuntime
{
	internal const string GeneratorSid = "Build_Mother_Nature";
	internal const int BonusMana = 20;
	private const int MaxPendingGrants = 8;

	private sealed class Grant
	{
		internal IntPtr LogicPointer;
		internal IntPtr TransferBattlePointer;
		internal DataHero Hero;
		internal int PreMana;
		internal string Label;
	}

	private static readonly object Gate = new();
	private static readonly List<Grant> Grants = new();
	private static bool _attempted;
	private static ManualLogSource _log;
	private static int _logged;
	private static MethodInfo _dataHeroGetter;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_attempted || harmony == null)
			return;
		_attempted = true;
		_log = log;
		try
		{
			var hexAssembly = typeof(TransferBattle).Assembly;
			Type logicType = null;
			foreach (var hint in GameSymbols.InfernoGating.BattleLogicTypeHints ?? Array.Empty<string>())
			{
				if (!string.IsNullOrWhiteSpace(hint) && hexAssembly.GetType(hint) is { } type)
				{
					logicType = type;
					break;
				}
			}
			if (logicType == null)
				throw new TypeLoadException("BattleLogic type not found");
			var init = logicType.GetMethod("Init", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null,
				           new[] { typeof(int), typeof(TransferBattle), typeof(bool), typeof(bool) }, null)
			           ?? throw new MissingMethodException("BattleLogic.Init(int, TransferBattle, bool, bool)");
			var applyResult = Homm3BattleResultSurface.ResolveApplyBattleResultMethod()
			                  ?? throw new MissingMethodException("battles-manager ApplyBattleResult(BattleLogic[, bool])");
			_dataHeroGetter = Homm3TowerArtificingRuntime.ResolveExactMethod(typeof(LogicHero), typeof(DataHero), Type.EmptyTypes,
				GameSymbols.CastleEliteStrategem.LogicHeroDataHeroGetter);
			Patch(harmony, init, nameof(PrefixBattleLogicInit), null);
			Patch(harmony, applyResult, nameof(PrefixApplyBattleResult), nameof(PostfixApplyBattleResult));
			_log?.LogInfo("HoMM3 Factory Mana Generator registered: +" + BonusMana + " battle mana for the defender of a Factory siege.");
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 Factory Mana Generator NOT registered (the building does nothing): " + ex.GetBaseException().Message);
		}
	}

	private static void PrefixBattleLogicInit(object __instance, TransferBattle __1)
	{
		try
		{
			if (__1?.sides == null || (__1.arenaLogicSid ?? "").IndexOf("siege", StringComparison.OrdinalIgnoreCase) < 0)
				return;
			if (__instance is not Il2CppObjectBase logic)
				return;
			lock (Gate)
			{
				// Init can run again for the same transfer battle (loader paths): grant once.
				foreach (var g in Grants)
				{
					if (g.TransferBattlePointer == __1.Pointer)
						return;
				}
			}
			if (!Homm3TownBuildingReader.TryGetBesiegedCity(__1, out var city) || city == null)
			{
				LogLimited("siege battle (" + __1.arenaLogicSid + ") but the besieged town was not resolved; no Mana Generator check.");
				return;
			}
			if (!Homm3FactoryTownFacts.IsFactoryCity(city) || !Homm3TownBuildingReader.CityHasBuilding(city, GeneratorSid))
				return;
			var objCity = Homm3FactoryTownFacts.ResolveObjCity(city);
			if (objCity == null)
			{
				LogLimited("besieged Factory town has the Mana Generator but its ObjCity (owner side) is unreadable; grant skipped.");
				return;
			}
			var owner = objCity.ownerSide;
			TransferSide defender = null;
			foreach (var side in __1.sides)
			{
				if (side != null && side.sideIdInWorld == owner && side.hero != null && side.logicHero != null)
				{
					defender = side;
					break;
				}
			}
			if (defender == null)
				return; // no defending hero: nothing to grant (HotA: the bonus is the hero's)
			if (_dataHeroGetter.Invoke(defender.logicHero, null) is not DataHero dataHero)
			{
				LogLimited("defending hero's data hero is unreadable; Mana Generator grant skipped.");
				return;
			}
			var pre = dataHero.mana;
			var transferBefore = defender.hero.mana;
			defender.hero.mana = transferBefore + BonusMana;
			var label = "side " + owner + " hero " + (defender.hero.configId ?? "?");
			lock (Gate)
			{
				Grants.Add(new Grant
				{
					LogicPointer = logic.Pointer,
					TransferBattlePointer = __1.Pointer,
					Hero = dataHero,
					PreMana = pre,
					Label = label,
				});
				while (Grants.Count > MaxPendingGrants)
				{
					LogLimited("dropping an unsettled Mana Generator grant (" + Grants[0].Label + "); its battle never applied a result.");
					Grants.RemoveAt(0);
				}
			}
			_log?.LogInfo("HoMM3 Factory Mana Generator: " + label + " defends " + (objCity.cityName ?? "a Factory town") + "; battle mana "
			              + transferBefore + " -> " + defender.hero.mana + " (world mana " + pre + ", max " + defender.hero.manaMax + ").");
		}
		catch (Exception ex)
		{
			LogLimited("Init prefix failed closed: " + ex.GetBaseException().Message);
		}
	}

	/// <summary>Settle only on the call that applies the result (alreadyApplied false), or when it is unreadable.</summary>
	private static void PrefixApplyBattleResult(object __0, out bool __state)
	{
		__state = false;
		try
		{
			if (!Homm3BattleResultSurface.TryReadBattleResultAlreadyApplied(__0, out var alreadyApplied))
			{
				LogLimited("battle result alreadyApplied unreadable; settling any Mana Generator grant on this call.");
				__state = true;
				return;
			}
			__state = !alreadyApplied;
		}
		catch (Exception ex)
		{
			LogLimited("ApplyBattleResult prefix failed closed: " + ex.GetBaseException().Message);
		}
	}

	private static void PostfixApplyBattleResult(object __0, bool __state)
	{
		if (!__state || __0 is not Il2CppObjectBase logic)
			return;
		Grant grant = null;
		lock (Gate)
		{
			for (var i = 0; i < Grants.Count; i++)
			{
				if (Grants[i].LogicPointer == logic.Pointer)
				{
					grant = Grants[i];
					Grants.RemoveAt(i);
					break;
				}
			}
		}
		if (grant == null)
			return;
		try
		{
			var after = grant.Hero.mana;
			var remove = Math.Min(BonusMana, after - grant.PreMana);
			if (remove > 0)
				grant.Hero.mana = after - remove;
			_log?.LogInfo("HoMM3 Factory Mana Generator settled for " + grant.Label + ": world mana " + grant.PreMana + " before, " + after
			              + " after battle, " + Math.Max(0, remove) + " unspent removed, now " + grant.Hero.mana + ".");
		}
		catch (Exception ex)
		{
			LogLimited("settling the Mana Generator grant for " + grant.Label + " failed: " + ex.GetBaseException().Message);
		}
	}

	private static void Patch(Harmony harmony, MethodInfo target, string prefixName, string postfixName)
	{
		const BindingFlags flags = BindingFlags.Static | BindingFlags.NonPublic;
		var prefix = prefixName == null ? null : typeof(Homm3FactoryManaGeneratorRuntime).GetMethod(prefixName, flags) ?? throw new MissingMethodException(prefixName);
		var postfix = postfixName == null ? null : typeof(Homm3FactoryManaGeneratorRuntime).GetMethod(postfixName, flags) ?? throw new MissingMethodException(postfixName);
		if (prefix != null && !GameMember.IsHarmonyPatchCompatible(target, prefix, out var prefixReason))
			throw new MissingMethodException("prefix incompatible for " + target.DeclaringType?.FullName + "." + target.Name + ": " + prefixReason);
		if (postfix != null && !GameMember.IsHarmonyPatchCompatible(target, postfix, out var postfixReason))
			throw new MissingMethodException("postfix incompatible for " + target.DeclaringType?.FullName + "." + target.Name + ": " + postfixReason);
		harmony.Patch(target,
			prefix: prefix == null ? null : new HarmonyMethod(prefix),
			postfix: postfix == null ? null : new HarmonyMethod(postfix) { priority = Priority.Last });
	}

	private static void LogLimited(string message)
	{
		if (_logged++ < 40)
			_log?.LogWarning("HoMM3 Factory Mana Generator: " + message);
	}
}
