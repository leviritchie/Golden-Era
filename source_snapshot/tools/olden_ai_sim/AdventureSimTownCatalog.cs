using System;
using System.Collections.Generic;

namespace OldenAiSim
{
	/// <summary>
	/// PROVISIONAL town management catalog (not Core-proven build costs).
	/// Ask when Olden construction / hire prices are known from live evidence.
	/// </summary>
	public static class AdventureSimTownCatalog
	{
		public const string VillageHall = "village_hall";
		public const string Fort = "fort";
		public const string Tavern = "tavern";
		public const string Marketplace = "marketplace";
		public const string DwellingT1 = "dwelling_t1";
		public const string DwellingT2 = "dwelling_t2";

		public sealed class BuildOffer
		{
			public string BuildingId;
			public string Label;
			public int Gold;
			public int Wood;
			public int Ore;
			public string Requires;
			public int UtilityBonus;
		}

		public sealed class HireOffer
		{
			public string BuildingId;
			public string UnitSid;
			public int Stacks;
			public int UnitValue;
			public int GoldCost;
			public int UtilityBonus;
		}

		public static readonly BuildOffer[] Builds =
		{
			new BuildOffer { BuildingId = Fort, Label = "Fort", Gold = 1500, Wood = 5, Ore = 5, Requires = VillageHall, UtilityBonus = 400 },
			new BuildOffer { BuildingId = Tavern, Label = "Tavern", Gold = 500, Wood = 5, Ore = 0, Requires = VillageHall, UtilityBonus = 120 },
			new BuildOffer { BuildingId = Marketplace, Label = "Marketplace", Gold = 500, Wood = 5, Ore = 0, Requires = VillageHall, UtilityBonus = 150 },
			new BuildOffer { BuildingId = DwellingT1, Label = "Guardhouse", Gold = 500, Wood = 5, Ore = 0, Requires = Fort, UtilityBonus = 300 },
			new BuildOffer { BuildingId = DwellingT2, Label = "Archers' Tower", Gold = 1000, Wood = 5, Ore = 5, Requires = DwellingT1, UtilityBonus = 450 },
		};

		public static readonly HireOffer[] Hires =
		{
			new HireOffer { BuildingId = DwellingT1, UnitSid = "pikeman", Stacks = 10, UnitValue = 50, GoldCost = 400, UtilityBonus = 350 },
			new HireOffer { BuildingId = DwellingT2, UnitSid = "archer", Stacks = 8, UnitValue = 80, GoldCost = 600, UtilityBonus = 420 },
		};

		/// <summary>Daily gold from an owned town based on buildings (provisional).</summary>
		public static int DailyTownGold(AdventureSimTown town)
		{
			if (town == null)
				return 0;
			var gold = 500; // village hall baseline
			if (town.Has(Fort))
				gold += 250;
			if (town.Has(Marketplace))
				gold += 150;
			if (town.Has(DwellingT1))
				gold += 50;
			if (town.Has(DwellingT2))
				gold += 100;
			return gold;
		}

		public static bool CanAfford(AdventureSimResources res, int gold, int wood, int ore)
		{
			if (res == null)
				return false;
			return res.Gold >= gold && res.Wood >= wood && res.Ore >= ore;
		}

		public static void Pay(AdventureSimResources res, int gold, int wood, int ore)
		{
			res.Gold -= gold;
			res.Wood -= wood;
			res.Ore -= ore;
		}
	}

	public sealed class AdventureSimTown
	{
		public int EntityId;
		public string Faction = "castle";
		public List<string> Buildings = new List<string> { AdventureSimTownCatalog.VillageHall };
		public List<AdventureSimStack> Garrison = new List<AdventureSimStack>();

		public bool Has(string buildingId)
		{
			if (Buildings == null || buildingId == null)
				return false;
			for (var i = 0; i < Buildings.Count; i++)
			{
				if (string.Equals(Buildings[i], buildingId, StringComparison.Ordinal))
					return true;
			}
			return false;
		}

		public void AddBuilding(string buildingId)
		{
			if (string.IsNullOrEmpty(buildingId) || Has(buildingId))
				return;
			Buildings.Add(buildingId);
		}
	}
}
