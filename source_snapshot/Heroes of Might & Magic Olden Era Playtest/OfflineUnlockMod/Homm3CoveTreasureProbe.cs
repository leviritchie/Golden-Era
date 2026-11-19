using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using BepInEx.Logging;
using DataHero = Hex.Session.Data.Hero;
using DataRoot = Hex.Session.Data.Data;
using LogicHero = Hex.Session.Logic.Hero;

namespace OfflineUnlockMod;

/// <summary>
/// Cove Treasure Hunting, step 1 (docs/cove_treasure_hunting_design.md section 10): logging-only probe.
/// At the first day start of each loaded game it logs every native region (Data.areas.list) with its tile count,
/// biome and the native value fields the treasure value is scaled from, then each hero's region for the first days.
/// Changes no game state. Every line starts "HoMM3 Cove Treasure probe: " so the log is greppable.
/// </summary>
internal static class Homm3CoveTreasureProbe
{
	private const string LogPrefix = "HoMM3 Cove Treasure probe: ";
	private const int HeroLineCap = 40;

	private static ManualLogSource _log;
	private static IntPtr _dumpedData;
	private static Dictionary<int, int> _areaOfNode;
	private static int _heroLines;

	internal static void TryRegister(ManualLogSource log)
	{
		_log = log;
		if (Homm3SwashbucklerGoldHook.TryRegisterDayStartHeroConsumer("homm3.cove.treasureProbe", OnDayStartHero, out var failure))
			log?.LogInfo(LogPrefix + "registered on the day-start hero bus.");
		else
			log?.LogWarning(LogPrefix + "NOT registered (" + failure + ").");
	}

	private static int OnDayStartHero(object entry)
	{
		try
		{
			if (!Homm3FactoryLogisticsEffects.TryGetData(out var data, out var fail) || data == null)
			{
				if (_heroLines++ < 3)
					_log?.LogWarning(LogPrefix + "session data unavailable: " + fail);
				return 0;
			}
			if (data.Pointer != _dumpedData)
			{
				_dumpedData = data.Pointer;
				_heroLines = 0;
				DumpAreas(data);
			}
			if (_heroLines >= HeroLineCap || _areaOfNode == null)
				return 0;
			var logicHero = entry as LogicHero;
			var hero = logicHero != null ? Homm3FactoryLogisticsRuntime.DataHeroOf(logicHero) : entry as DataHero;
			if (hero == null)
				return 0;
			_heroLines++;
			var area = _areaOfNode.TryGetValue(hero.node, out var id) ? id.ToString(CultureInfo.InvariantCulture) : "none";
			_log?.LogInfo(LogPrefix + "hero " + hero.configSid + " side=" + hero.sideId.ToString(CultureInfo.InvariantCulture)
				+ " node=" + hero.node.ToString(CultureInfo.InvariantCulture) + " area=" + area + ".");
		}
		catch (Exception ex)
		{
			if (_heroLines++ < 3)
				_log?.LogWarning(LogPrefix + "threw " + ex.GetBaseException().GetType().Name + ": " + ex.GetBaseException().Message);
		}
		return 0;
	}

	private static void DumpAreas(DataRoot data)
	{
		_areaOfNode = null;
		var areas = data.areas;
		var list = areas?.list;
		if (list == null)
		{
			_log?.LogWarning(LogPrefix + "Data.areas" + (areas == null ? "" : ".list") + " is null: no native regions on this map.");
			return;
		}
		var watch = System.Diagnostics.Stopwatch.StartNew();
		var map = new Dictionary<int, int>();
		var count = list.Count;
		_log?.LogInfo(LogPrefix + "areas=" + count.ToString(CultureInfo.InvariantCulture)
			+ " startSumValue=" + areas.startSumValue.ToString(CultureInfo.InvariantCulture) + ".");
		for (var i = 0; i < count; i++)
		{
			var area = list[i];
			if (area == null)
				continue;
			var nodes = area.nodes;
			var tiles = nodes == null ? 0 : nodes.Count;
			for (var n = 0; n < tiles; n++)
				map[nodes[n]] = area.field_Public_Int32_0;
			var objects = new StringBuilder();
			var byType = area.objectsByType;
			if (byType != null)
			{
				for (var t = 0; t < byType.Count; t++)
				{
					var group = byType[t];
					if (group == null)
						continue;
					var ids = group.field_Public_List_1_Int32_0;
					if (objects.Length > 0)
						objects.Append(' ');
					objects.Append(group.type.ToString()).Append('=').Append(ids == null ? 0 : ids.Count);
				}
			}
			_log?.LogInfo(LogPrefix + "area id=" + area.field_Public_Int32_0.ToString(CultureInfo.InvariantCulture)
				+ " tiles=" + tiles.ToString(CultureInfo.InvariantCulture)
				+ " root=" + area.rootNode.ToString(CultureInfo.InvariantCulture)
				+ " keyObject=" + area.keyObjectId.ToString(CultureInfo.InvariantCulture)
				+ " biome=" + (area.biome ?? "?")
				+ " neighbors=" + (area.neighbors == null ? 0 : area.neighbors.Count).ToString(CultureInfo.InvariantCulture)
				+ " valueOnStart=" + area.pickableObjectsValuesOnStart.ToString(CultureInfo.InvariantCulture)
				+ " valueLeft=" + area.pickableObjectsValuesLeft.ToString(CultureInfo.InvariantCulture)
				+ " objects=[" + objects + "].");
		}
		watch.Stop();
		_areaOfNode = map;
		_log?.LogInfo(LogPrefix + "node->area map tiles=" + map.Count.ToString(CultureInfo.InvariantCulture)
			+ " built in " + watch.Elapsed.TotalMilliseconds.ToString("0.0", CultureInfo.InvariantCulture) + " ms.");
	}
}
