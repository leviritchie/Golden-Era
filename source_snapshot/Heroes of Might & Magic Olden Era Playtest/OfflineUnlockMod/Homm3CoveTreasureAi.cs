using System;
using System.Collections.Generic;
using DataHero = Hex.Session.Data.Hero;
using Plan = OfflineUnlockMod.Homm3CoveTreasurePlan;

namespace OfflineUnlockMod;

/// <summary>
/// AI digging. Computer heroes never cast Dig and never walk to a treasure tile, so the rule is simpler than the
/// player's: when a computer hero with Treasure Hunting steps within <see cref="SearchRadius"/> tiles of a treasure
/// site its side's map pieces show (the true tile or a false lead still on its map), it digs that site. One dig per
/// hero per day, no movement spent. A false lead leaves a hole, the true tile pays the treasure to that side.
///
/// The dig itself (hole / dug state) is committed in the enter-node hook; the payout (army, artifact, resources) is
/// queued and paid from the marker host's Update, outside the native move.
/// </summary>
internal static partial class Homm3CoveTreasureRuntime
{
	private static readonly Dictionary<int, int> _aiDugDay = new();
	private static readonly Dictionary<int, bool> _aiSide = new();
	private static readonly List<(object WorldHero, Plan.Contents Contents, int Side)> _aiPayouts = new();
	private static int _aiHunters;

	private static bool IsAiSide(int side)
	{
		if (side < 0)
			return false;
		if (_aiSide.TryGetValue(side, out var ai))
			return ai;
		if (!Homm3FactoryLogisticsState.TryResolveSide(side, out var resolved, out _) || resolved == null)
			return false;
		ai = !Homm3FactoryLogisticsRuntime.IsLocalHuman(resolved);
		_aiSide[side] = ai;
		return ai;
	}

	private static void CountAiHunters()
	{
		_aiHunters = 0;
		foreach (var hero in _coveHeroes)
			if (IsAiSide(hero.sideId))
				_aiHunters++;
	}

	private static void AiEnterNode(object worldHero)
	{
		var map = _map;
		if (_aiHunters == 0 || worldHero == null || map == null || map.Failed || map.Regions.Count == 0)
			return;
		if (!Homm3FactoryLogisticsRuntime.TryResolveHeroFromWorldHero(worldHero, out _, out var hero) || hero == null)
			return;
		var side = hero.sideId;
		var id = hero.field_Public_Int32_0;
		if (!_rankCache.TryGetValue(id, out var rank) || rank.Rank <= 0 || !IsAiSide(side))
			return;
		if (!Homm3FactoryLogisticsEffects.TryGetData(out var data, out _) || data == null || data.Pointer != map.DataPointer)
			return;
		var day = data.daysInGameCount;
		if (_aiDugDay.TryGetValue(id, out var dug) && dug == day)
			return;
		var from = hero.node;
		var best = -1;
		var bestDistance = SearchRadius + 1;
		foreach (var areaId in AreasInSearchRange(map, from))
		{
			if (!map.Regions.TryGetValue(areaId, out var region) || region.Dug || region.Plan.TrueNode < 0)
				continue;
			region.PiecesBySide.TryGetValue(side, out var pieces);
			if (pieces <= 0)
				continue;
			AiConsider(map, from, region.Plan.TrueNode, ref best, ref bestDistance);
			// The same leads the side's own map would show (CollectMarkers).
			var falseNodes = region.Plan.FalseNodes;
			for (var i = Math.Max(0, pieces - 1); i < falseNodes.Length && LeadCount(pieces) > 1; i++)
				AiConsider(map, from, falseNodes[i], ref best, ref bestDistance);
		}
		if (best < 0)
			return;
		_aiDugDay[id] = day;
		var outcome = CommitDigAt(hero, best, out var contents, out _);
		if (outcome != DigOutcome.Treasure || contents == null)
			return;
		_aiPayouts.Add((worldHero, contents, side));
		Homm3CoveTreasureMarkers.EnsureHost();
	}

	private static void AiConsider(MapState map, int from, int node, ref int best, ref int bestDistance)
	{
		if (node < 0 || map.Holes.Contains(node))
			return;
		var d = Plan.Distance(from, node, map.Width);
		if (d >= bestDistance)
			return;
		bestDistance = d;
		best = node;
	}

	/// <summary>Pays queued computer-side treasures. Called from the marker host's Update.</summary>
	internal static void FlushAiPayouts()
	{
		if (_aiPayouts.Count == 0 || _inTick)
			return;
		var due = new List<(object WorldHero, Plan.Contents Contents, int Side)>(_aiPayouts);
		_aiPayouts.Clear();
		foreach (var p in due)
			Homm3CoveTreasureDig.PayAi(p.WorldHero, p.Contents, p.Side);
	}
}
