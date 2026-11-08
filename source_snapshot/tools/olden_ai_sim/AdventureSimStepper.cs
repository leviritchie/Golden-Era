using System;
using System.Collections.Generic;

namespace OldenAiSim
{
	/// <summary>
	/// Step-debug wrapper around Evaluate. Fail-closed on empty session / out-of-range steps.
	/// </summary>
	public sealed class AdventureSimStepper
	{
		private readonly AdventureSimState _initial;
		private readonly AdventureSimKnobs _knobs;
		private readonly AdventureSimWorldSnapshot _world0;
		private readonly List<AdventureSimStepRecord> _records = new List<AdventureSimStepRecord>();
		private int _index = -1;

		public AdventureSimResult Result { get; private set; }
		public IReadOnlyList<AdventureSimStepRecord> Records { get { return _records; } }
		public int CurrentIndex { get { return _index; } }
		public int StepCount { get { return _records.Count; } }
		public bool IsComplete { get { return _records.Count > 0 && _index >= _records.Count - 1; } }

		private AdventureSimStepper(AdventureSimState initial, AdventureSimKnobs knobs)
		{
			_initial = initial;
			_knobs = knobs ?? new AdventureSimKnobs();
			_world0 = CaptureInitial(initial);
			Result = new AdventureSimResult();
		}

		public static AdventureSimStepper Run(AdventureSimState state, AdventureSimKnobs knobs)
		{
			if (state == null)
				throw new ArgumentNullException(nameof(state));
			var stepper = new AdventureSimStepper(CloneStateShallow(state), knobs);
			stepper.Result = AdventureSimulator.EvaluateCore(stepper._initial, stepper._knobs, stepper._records);
			stepper._index = -1;
			return stepper;
		}

		public void Reset()
		{
			_index = -1;
		}

		public bool TryStepForward(out string error)
		{
			error = null;
			if (_records.Count == 0)
			{
				error = "empty session: no step records (Evaluate produced no actions)";
				return false;
			}
			if (_index >= _records.Count - 1)
			{
				error = "already at end (index=" + _index + ", count=" + _records.Count + ")";
				return false;
			}
			_index++;
			return true;
		}

		public bool TryStepBack(out string error)
		{
			error = null;
			if (_index < 0)
			{
				error = "already at start (index=-1)";
				return false;
			}
			_index--;
			return true;
		}

		public void RunToEnd()
		{
			if (_records.Count == 0)
				return;
			_index = _records.Count - 1;
		}

		public AdventureSimWorldSnapshot WorldAt(int index)
		{
			if (index < -1 || index >= _records.Count)
				throw new ArgumentOutOfRangeException(nameof(index), "index=" + index + " count=" + _records.Count);
			if (index < 0)
				return CloneSnapshot(_world0);
			return CloneSnapshot(_records[index].WorldAfter);
		}

		public AdventureSimWorldSnapshot CurrentWorld()
		{
			return WorldAt(_index);
		}

		public AdventureSimStepRecord CurrentRecord()
		{
			if (_index < 0 || _index >= _records.Count)
				return null;
			return _records[_index];
		}

		private static AdventureSimWorldSnapshot CaptureInitial(AdventureSimState state)
		{
			return new AdventureSimWorldSnapshot
			{
				Day = state.Day,
				Resources = new AdventureSimResources
				{
					Gold = state.Resources.Gold,
					Wood = state.Resources.Wood,
					Ore = state.Resources.Ore,
					Gemstones = state.Resources.Gemstones,
					Crystals = state.Resources.Crystals,
					Mercury = state.Resources.Mercury,
				},
				Marks = new AdventureSimMarks
				{
					MarkedCity = state.Marks.MarkedCity,
					MarkedHero = state.Marks.MarkedHero,
					MarkedObject = state.Marks.MarkedObject,
					MarkedNode = state.Marks.MarkedNode,
					MarkedEnemyCity = state.Marks.MarkedEnemyCity,
					HardStrategy = state.Marks.HardStrategy,
					MarkedSquads = state.Marks.MarkedSquads != null
						? new List<int>(state.Marks.MarkedSquads)
						: new List<int>(),
				},
				Heroes = CloneHeroes(state.Heroes),
				Occupancy = CloneOcc(state.Occupancy),
				Towns = AdventureSimTownLogic.CloneTowns(state.Towns),
			};
		}

		private static AdventureSimWorldSnapshot CloneSnapshot(AdventureSimWorldSnapshot s)
		{
			if (s == null)
				return null;
			return new AdventureSimWorldSnapshot
			{
				Day = s.Day,
				Resources = new AdventureSimResources
				{
					Gold = s.Resources.Gold,
					Wood = s.Resources.Wood,
					Ore = s.Resources.Ore,
					Gemstones = s.Resources.Gemstones,
					Crystals = s.Resources.Crystals,
					Mercury = s.Resources.Mercury,
				},
				Marks = new AdventureSimMarks
				{
					MarkedCity = s.Marks.MarkedCity,
					MarkedHero = s.Marks.MarkedHero,
					MarkedObject = s.Marks.MarkedObject,
					MarkedNode = s.Marks.MarkedNode,
					MarkedEnemyCity = s.Marks.MarkedEnemyCity,
					HardStrategy = s.Marks.HardStrategy,
					MarkedSquads = s.Marks.MarkedSquads != null
						? new List<int>(s.Marks.MarkedSquads)
						: new List<int>(),
				},
				Heroes = CloneHeroes(s.Heroes),
				Occupancy = CloneOcc(s.Occupancy),
				Towns = AdventureSimTownLogic.CloneTowns(s.Towns),
			};
		}

		private static List<AdventureSimHero> CloneHeroes(List<AdventureSimHero> source)
		{
			var list = new List<AdventureSimHero>();
			if (source == null)
				return list;
			for (var i = 0; i < source.Count; i++)
			{
				var h = source[i];
				if (h == null)
					continue;
				var clone = AdventureFightEstimate.CloneHeroShallow(h);
				if (h.Party != null)
				{
					for (var p = 0; p < h.Party.Count; p++)
					{
						var s = h.Party[p];
						if (s == null)
							continue;
						clone.Party.Add(new AdventureSimStack
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

		private static List<AdventureSimOccupant> CloneOcc(List<AdventureSimOccupant> source)
		{
			var list = new List<AdventureSimOccupant>();
			if (source == null)
				return list;
			for (var i = 0; i < source.Count; i++)
			{
				var o = source[i];
				if (o == null)
					continue;
				list.Add(new AdventureSimOccupant
				{
					EntityId = o.EntityId,
					Node = o.Node,
					Kind = o.Kind,
					StartValue = o.StartValue,
					Alive = o.Alive,
					OwnerSide = o.OwnerSide,
					Label = o.Label,
					GoldReward = o.GoldReward,
				});
			}
			return list;
		}

		private static AdventureSimState CloneStateShallow(AdventureSimState s)
		{
			// Evaluate mutates hero MP normalization only; grids shared read-only.
			return new AdventureSimState
			{
				ScenarioName = s.ScenarioName,
				Day = s.Day,
				SideIndex = s.SideIndex,
				SideName = s.SideName,
				Marks = s.Marks,
				Resources = s.Resources,
				Heroes = CloneHeroes(s.Heroes),
				Occupancy = CloneOcc(s.Occupancy),
				Pathable = s.Pathable,
				Terrain = s.Terrain,
				Road = s.Road,
				SizeX = s.SizeX,
				SizeZ = s.SizeZ,
				MoveCost = s.MoveCost,
				DailyGoldIncome = s.DailyGoldIncome,
				Portals = s.Portals,
				Towns = AdventureSimTownLogic.CloneTowns(s.Towns),
			};
		}
	}
}
