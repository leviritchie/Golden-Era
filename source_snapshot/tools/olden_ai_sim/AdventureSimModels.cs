using System;
using System.Collections.Generic;

namespace OldenAiSim
{
	/// <summary>Omniscient mark-centric adventure snapshot. Schema: homm3.adventure.sim_state.v1</summary>
	public sealed class AdventureSimState
	{
		public const string SchemaVersion = "homm3.adventure.sim_state.v1";

		public string Schema { get { return SchemaVersion; } }
		public string ScenarioName;
		public int Day;
		public int SideIndex;
		public string SideName;
		public AdventureSimMarks Marks = new AdventureSimMarks();
		public AdventureSimResources Resources = new AdventureSimResources();
		public List<AdventureSimHero> Heroes = new List<AdventureSimHero>();
		public List<AdventureSimOccupant> Occupancy = new List<AdventureSimOccupant>();
		/// <summary>Town management state keyed by town EntityId.</summary>
		public List<AdventureSimTown> Towns = new List<AdventureSimTown>();
		/// <summary>Row-major pathability: index = z * SizeX + x. True = land-pathable.</summary>
		public bool[] Pathable;
		/// <summary>Optional Olden Core tile id per cell. Length SizeX*SizeZ.</summary>
		public byte[] Terrain;
		/// <summary>Optional road id per cell (0 = none). Length SizeX*SizeZ.</summary>
		public byte[] Road;
		public int SizeX;
		public int SizeZ;
		/// <summary>When present and length-matches grid, sole CellCost authority.</summary>
		public int[] MoveCost;
		/// <summary>Base daily gold (named base). EOD adds owned mine yields on top.</summary>
		public int DailyGoldIncome = 1000;
		/// <summary>Node-indexed portal adjacency (bidirectional). Key = node, value = linked nodes.</summary>
		public Dictionary<int, List<int>> Portals = new Dictionary<int, List<int>>();
	}

	public sealed class AdventureSimMarks
	{
		public int MarkedCity;
		public int MarkedHero;
		public int MarkedObject;
		public int MarkedNode;
		public int MarkedEnemyCity;
		public List<int> MarkedSquads = new List<int>();
		public string HardStrategy;
	}

	public sealed class AdventureSimResources
	{
		public int Gold;
		public int Wood;
		public int Ore;
		public int Gemstones;
		public int Crystals;
		public int Mercury;
	}

	public sealed class AdventureSimHero
	{
		public int HeroId;
		public string Name;
		public int Node;
		public int MovePoints;
		public int MaxMovePoints = 1500;
		public int Mana;
		public List<AdventureSimStack> Party = new List<AdventureSimStack>();
	}

	public sealed class AdventureSimStack
	{
		public string UnitSid;
		public int Stacks;
		/// <summary>Per-stack engine value (squadValue). 0 → treat as 1 for estimates.</summary>
		public int UnitValue;
	}

	public enum AdventureSimTargetKind
	{
		Unknown = 0,
		Neutral = 1,
		Town = 2,
		Hero = 3,
		Pickup = 4,
		Node = 5,
		Mine = 6,
	}

	/// <summary>Typed beam action kinds. SID vocab JSON is reference-only and not dispatched.</summary>
	public enum AdventureSimActionKind
	{
		MoveToOccupy = 0,
		MarkSet = 1,
		/// <summary>Legacy alias — prefer TownHire.</summary>
		HireStub = 2,
		EndDay = 3,
		TownBuild = 4,
		TownHire = 5,
		TownGarrisonTake = 6,
	}

	public sealed class AdventureSimOccupant
	{
		public int EntityId;
		public int Node;
		public AdventureSimTargetKind Kind;
		public int StartValue;
		public bool Alive = true;
		public int OwnerSide = -1;
		public string Label;
		/// <summary>Pickup one-shot gold, or mine daily yield when owned (same field — one source).</summary>
		public int GoldReward;
	}

	public sealed class AdventureSimKnobs
	{
		public int BeamDepth = 3;
		public int BeamWidth = 12;
		public int TimeBudgetMs = 50;
		public int DefaultMoveCost = 100;
		public float WinPowerRatio = 1.15f;
		public float PreferredBiasMultiplier = 2.5f;
		public float SecondaryBiasMultiplier = 1.35f;
		public bool MultiHero = true;
		public bool ApplyEndOfDayIncome = true;
		/// <summary>When MoveCost is absent, use OldenTileMp / legacy terrain fallback.</summary>
		public bool UseTerrainCosts = true;
		/// <summary>PROVISIONAL DifficultyAi-style scalar on hero power. Default 1.</summary>
		public float HeroPowerMultiplier = 1f;
		/// <summary>PROVISIONAL DifficultyAi-style scalar on mob/startValue threat. Default 1.</summary>
		public float ValuesVsMobsMultiplier = 1f;
	}

	public sealed class AdventureSimBiasEntry
	{
		public AdventureSimTargetKind TargetKind;
		public int TargetId;
		public float Multiplier = 1f;
	}

	public sealed class AdventureSimTraceStep
	{
		public int Depth;
		public int HeroId;
		public AdventureSimTargetKind Kind;
		public int EntityId;
		public int FromNode;
		public int ToNode;
		public int PathCost;
		public float UtilityDelta;
		public float CumulativeUtility;
		public bool Fought;
		public float LossFraction;
		public string Note;
		public AdventureSimActionKind ActionKind;
		public List<AdventureSimCandidateInfo> Candidates;
		public AdventureSimFightBreakdown Fight;
		public int TownEntityId;
		public string BuildingId;
		public string UnitSid;
	}

	public sealed class AdventureSimCandidateInfo
	{
		public int EntityId;
		public AdventureSimTargetKind Kind;
		public float Utility;
		public bool Accepted;
		public string RejectReason;
		public int PathCost;
		public bool RequiresFight;
	}

	public sealed class AdventureSimFightBreakdown
	{
		public int Power;
		public int Threat;
		public float Ratio;
		public bool CanWin;
		public float LossFraction;
		public float HeroPowerMultiplier = 1f;
		public float ValuesVsMobsMultiplier = 1f;
		public string Summary;
	}

	/// <summary>One recorded beam expansion for step-debug GUI.</summary>
	public sealed class AdventureSimStepRecord
	{
		public int Index;
		public AdventureSimActionKind ActionKind;
		public int HeroId;
		public int FromNode;
		public int ToNode;
		public int PathCost;
		public int MpBefore;
		public int MpAfter;
		public int TargetEntityId;
		public AdventureSimTargetKind TargetKind;
		public float UtilityDelta;
		public float CumulativeUtility;
		public string Note;
		public AdventureSimFightBreakdown Fight;
		public List<AdventureSimCandidateInfo> Candidates = new List<AdventureSimCandidateInfo>();
		public AdventureSimWorldSnapshot WorldAfter;
		public int TownEntityId;
		public string BuildingId;
		public string UnitSid;
	}

	public sealed class AdventureSimWorldSnapshot
	{
		public int Day;
		public AdventureSimResources Resources = new AdventureSimResources();
		public AdventureSimMarks Marks = new AdventureSimMarks();
		public List<AdventureSimHero> Heroes = new List<AdventureSimHero>();
		public List<AdventureSimOccupant> Occupancy = new List<AdventureSimOccupant>();
		public List<AdventureSimTown> Towns = new List<AdventureSimTown>();
	}

	public sealed class AdventureSimResult
	{
		public bool Ok;
		public string Error;
		public AdventureSimTargetKind PreferredKind;
		public int PreferredId;
		public int PreferredNode;
		public int PreferredHeroId;
		public float PreferredUtility;
		public List<AdventureSimBiasEntry> Biases = new List<AdventureSimBiasEntry>();
		public List<AdventureSimTraceStep> Trace = new List<AdventureSimTraceStep>();
		public string Diagnostics;
		public Dictionary<int, int> ReachOverlay = new Dictionary<int, int>();
		public List<AdventureSimStepRecord> Steps = new List<AdventureSimStepRecord>();
	}

	/// <summary>
	/// Offline terrain ids. Prefer Olden Core tile ids (1+) when filling MoveCost via OldenTileMp.
	/// Legacy 0-9 VCMI-ish ids remain only as authoring fallback when MoveCost is null.
	/// </summary>
	public static class AdventureSimTerrain
	{
		// Legacy offline authoring ids (NOT Olden Core ids)
		public const byte Dirt = 0;
		public const byte Sand = 1;
		public const byte Grass = 2;
		public const byte Snow = 3;
		public const byte Swamp = 4;
		public const byte Rough = 5;
		public const byte Subterranean = 6;
		public const byte Lava = 7;
		public const byte Water = 8;
		public const byte Rock = 9;

		// Olden Core tile ids (from Core.zip tiles.json)
		public const byte OldenGrass = 1;
		public const byte OldenSand = 2;
		public const byte OldenSnow = 4;
		public const byte OldenDirt = 7;
		public const byte OldenSwamp = 8;
		public const byte OldenWasteland = 11;
		public const byte OldenWater = 18;
		public const byte OldenRockBlocked = 255;

		public static int CostMultiplier(byte terrainId)
		{
			// Legacy fallback only when MoveCost absent.
			switch (terrainId)
			{
				case Sand: return 125;
				case Snow: return 150;
				case Swamp: return 175;
				case Rough: return 125;
				case Subterranean: return 100;
				case Lava: return 100;
				case Water: return 1000;
				case Rock: return 1000;
				default: return 100;
			}
		}

		public static string Name(byte terrainId)
		{
			switch (terrainId)
			{
				case Sand: return "sand(legacy)";
				case Grass: return "grass(legacy)";
				case Snow: return "snow(legacy)";
				case Swamp: return "swamp(legacy)";
				case Rough: return "rough(legacy)";
				case Subterranean: return "subterra(legacy)";
				case Lava: return "lava(legacy)";
				case Water: return "water(legacy)";
				case Rock: return "rock(legacy)";
				case OldenRockBlocked: return "blocked";
				default:
					if (terrainId >= 1 && terrainId <= 23)
						return "olden_tile_" + terrainId;
					return "dirt(legacy)";
			}
		}
	}

	public static class AdventureSimEconomy
	{
		/// <summary>Base DailyGoldIncome + owned mines + owned town buildings (provisional).</summary>
		public static int ComputeEndOfDayGold(AdventureSimState state, List<AdventureSimOccupant> occupancy, List<AdventureSimTown> towns)
		{
			if (state == null)
				return 0;
			var gold = state.DailyGoldIncome;
			if (occupancy != null)
			{
				for (var i = 0; i < occupancy.Count; i++)
				{
					var o = occupancy[i];
					if (o == null || !o.Alive)
						continue;
					if (o.Kind != AdventureSimTargetKind.Mine)
						continue;
					if (o.OwnerSide != state.SideIndex)
						continue;
					gold += o.GoldReward;
				}
			}
			if (towns != null && occupancy != null)
			{
				for (var t = 0; t < towns.Count; t++)
				{
					var town = towns[t];
					if (town == null)
						continue;
					var occ = FindOcc(occupancy, town.EntityId);
					if (occ == null || !occ.Alive || occ.OwnerSide != state.SideIndex)
						continue;
					gold += AdventureSimTownCatalog.DailyTownGold(town);
				}
			}
			return gold;
		}

		/// <summary>Back-compat overload used by older call sites.</summary>
		public static int ComputeEndOfDayGold(AdventureSimState state, List<AdventureSimOccupant> occupancy)
		{
			return ComputeEndOfDayGold(state, occupancy, state != null ? state.Towns : null);
		}

		private static AdventureSimOccupant FindOcc(List<AdventureSimOccupant> occupancy, int entityId)
		{
			for (var i = 0; i < occupancy.Count; i++)
			{
				if (occupancy[i] != null && occupancy[i].EntityId == entityId)
					return occupancy[i];
			}
			return null;
		}
	}
}
