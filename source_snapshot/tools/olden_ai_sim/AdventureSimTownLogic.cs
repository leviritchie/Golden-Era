using System;
using System.Collections.Generic;

namespace OldenAiSim
{
	public static class AdventureSimTownLogic
	{
		public static List<AdventureSimTown> CloneTowns(List<AdventureSimTown> source)
		{
			var list = new List<AdventureSimTown>();
			if (source == null)
				return list;
			for (var i = 0; i < source.Count; i++)
			{
				var t = source[i];
				if (t == null)
					continue;
				var clone = new AdventureSimTown
				{
					EntityId = t.EntityId,
					Faction = t.Faction,
					Buildings = t.Buildings != null ? new List<string>(t.Buildings) : new List<string>(),
					Garrison = new List<AdventureSimStack>(),
				};
				if (t.Garrison != null)
				{
					for (var g = 0; g < t.Garrison.Count; g++)
					{
						var s = t.Garrison[g];
						if (s == null)
							continue;
						clone.Garrison.Add(new AdventureSimStack
						{
							UnitSid = s.UnitSid,
							Stacks = s.Stacks,
							UnitValue = s.UnitValue,
						});
					}
				}
				list.Add(clone);
			}
			return list;
		}

		public static AdventureSimTown Find(List<AdventureSimTown> towns, int entityId)
		{
			if (towns == null)
				return null;
			for (var i = 0; i < towns.Count; i++)
			{
				if (towns[i] != null && towns[i].EntityId == entityId)
					return towns[i];
			}
			return null;
		}

		public static AdventureSimOccupant FindOwnedTownOcc(
			AdventureSimState state,
			List<AdventureSimOccupant> occupancy,
			int entityId)
		{
			if (occupancy == null)
				return null;
			for (var i = 0; i < occupancy.Count; i++)
			{
				var o = occupancy[i];
				if (o == null || o.EntityId != entityId)
					continue;
				if (o.Kind != AdventureSimTargetKind.Town || !o.Alive)
					continue;
				if (o.OwnerSide != state.SideIndex)
					continue;
				return o;
			}
			return null;
		}

		public static bool HeroAtTown(List<AdventureSimHero> heroes, int heroIndex, int townNode)
		{
			if (heroes == null || heroIndex < 0 || heroIndex >= heroes.Count)
				return false;
			return heroes[heroIndex] != null && heroes[heroIndex].Node == townNode;
		}

		public static void EnsureTownForCapture(List<AdventureSimTown> towns, int entityId)
		{
			if (Find(towns, entityId) != null)
				return;
			towns.Add(new AdventureSimTown { EntityId = entityId });
		}
	}
}
