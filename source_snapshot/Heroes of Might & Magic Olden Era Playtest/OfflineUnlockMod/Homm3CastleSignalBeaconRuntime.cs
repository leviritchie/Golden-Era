using System;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using BuffDuration = Hex.Session.Data.BuffDuration;
using DataHero = Hex.Session.Data.Hero;
using LogicHero = Hex.Session.Logic.Hero;

namespace OfflineUnlockMod;

/// <summary>
/// Castle Signal Beacon (building pass 2026-11-22; the land-safe substitute for the HoMM3 Lighthouse, castle.md):
/// every hero of a side owning at least one Castle city with <c>Build_Mycelium_Roots</c> keeps the hero buff
/// <see cref="BeaconBuffSid"/> (heroStat movementPerBonus 0.10, Infinite; a Core heroes_buffs row). It does not stack
/// across several Beacons.
///
/// Trigger: the shared day-start hero bus (<see cref="Homm3SwashbucklerGoldHook.TryRegisterDayStartHeroConsumer"/>),
/// which hands each active hero of a side at that side's day start. The buff is set or cleared there, so building,
/// capturing or losing a Beacon city, and hiring a hero, take effect from the next day start (the player text says so).
/// No save state: the buff is native hero data, and the next day start corrects it either way.
/// </summary>
internal static class Homm3CastleSignalBeaconRuntime
{
	internal const string BeaconSid = "Build_Mycelium_Roots";
	internal const string CastleCitySid = "homm3_castle_city";
	internal const string BeaconBuffSid = "homm3_signal_beacon_buff";
	private const string LogPrefix = "HoMM3 Castle Signal Beacon: ";

	private static ManualLogSource _log;
	private static bool _attempted;
	private static int _logged;
	private static bool _missingRowWarned;
	private static PropertyInfo _buffManagerProperty;
	private static MethodInfo _buffAdd, _buffRemove, _buffGet, _logicHeroDataHeroGetter;

	private static void Info(string message)
	{
		if (_logged++ < 120)
			_log?.LogInfo(LogPrefix + message);
	}

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_attempted)
			return;
		_attempted = true;
		_log = log;
		try
		{
			_buffManagerProperty = typeof(LogicHero).GetProperty(GameSymbols.DungeonCaptives.LogicHeroBuffManagerMembers[0], BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
			                       ?? throw new MissingMemberException("logic hero buff manager");
			var managerType = _buffManagerProperty.PropertyType;
			_buffAdd = Homm3TowerArtificingRuntime.ResolveExactMethod(managerType, typeof(void), new[] { typeof(string), typeof(Il2CppReferenceArray<BuffDuration>) }, GameSymbols.DungeonCaptives.BuffManagerAdd);
			_buffRemove = Homm3TowerArtificingRuntime.ResolveExactMethod(managerType, typeof(void), new[] { typeof(string) }, GameSymbols.DungeonCaptives.BuffManagerRemove);
			_buffGet = Homm3TowerArtificingRuntime.ResolveExactMethod(managerType, null, new[] { typeof(string) }, GameSymbols.DungeonCaptives.BuffManagerGet);
			_logicHeroDataHeroGetter = Homm3TowerArtificingRuntime.ResolveExactMethod(typeof(LogicHero), typeof(DataHero), Type.EmptyTypes, GameSymbols.CastleEliteStrategem.LogicHeroDataHeroGetter);
			if (!Homm3SwashbucklerGoldHook.TryRegisterDayStartHeroConsumer("homm3.castle.signalBeacon", OnDayStartHero, out var failure))
				throw new InvalidOperationException("day-start bus: " + failure);
			_log?.LogInfo(LogPrefix + "registered on the day-start hero bus.");
		}
		catch (Exception ex)
		{
			_buffManagerProperty = null;
			_log?.LogWarning(LogPrefix + "NOT registered (no Beacon movement buff): " + ex.GetBaseException().Message);
		}
	}

	private static int OnDayStartHero(object entry)
	{
		if (_buffManagerProperty == null)
			return 0;
		try
		{
			// The bus hands the logic hero unless the side's list holds data heroes; the buff manager needs the logic hero.
			if (entry is not LogicHero hero || hero.Pointer == IntPtr.Zero)
				return 0;
			var dataHero = _logicHeroDataHeroGetter.Invoke(hero, Array.Empty<object>()) as DataHero;
			if (dataHero == null)
				return 0;
			var wanted = Homm3TownBuildingReader.SideHasBuilding(dataHero, BeaconSid, CastleCitySid);
			var manager = _buffManagerProperty.GetValue(hero);
			if (manager == null)
				return 0;
			var has = _buffGet.Invoke(manager, new object[] { BeaconBuffSid }) != null;
			if (has == wanted)
				return 0;
			if (wanted)
			{
				var durations = new Il2CppReferenceArray<BuffDuration>(1);
				durations[0] = new BuffDuration(EBuffDurationType.Infinite, -1);
				_buffAdd.Invoke(manager, new object[] { BeaconBuffSid, durations });
			}
			else
			{
				_buffRemove.Invoke(manager, new object[] { BeaconBuffSid });
			}
			var now = _buffGet.Invoke(manager, new object[] { BeaconBuffSid }) != null;
			if (now == wanted)
				Info("hero " + dataHero.configSid + (wanted ? " gains" : " loses") + " the Signal Beacon buff (+10% movement points).");
			else if (!_missingRowWarned)
			{
				_missingRowWarned = true;
				_log?.LogWarning(LogPrefix + BeaconBuffSid + " did not " + (wanted ? "stick" : "clear") + " on hero " + dataHero.configSid + " (heroes_buffs row missing from the Core?). The Beacon gives no movement.");
			}
		}
		catch (Exception ex)
		{
			if (_logged++ < 120)
				_log?.LogWarning(LogPrefix + "day-start refresh threw " + ex.GetBaseException().Message + ".");
		}
		return 0;
	}
}
