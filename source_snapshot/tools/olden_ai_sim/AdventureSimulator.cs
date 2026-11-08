using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Text;

namespace OldenAiSim
{
	/// <summary>
	/// Mark-centric multi-day beam over occupancy aims. Outputs biases + step records for GUI.
	/// </summary>
	public static class AdventureSimulator
	{
		public static AdventureSimResult Evaluate(AdventureSimState state, AdventureSimKnobs knobs)
		{
			var stepper = AdventureSimStepper.Run(state, knobs);
			return stepper.Result;
		}

		internal static AdventureSimResult EvaluateCore(AdventureSimState state, AdventureSimKnobs knobs, List<AdventureSimStepRecord> stepSink)
		{
			var result = new AdventureSimResult();
			if (state == null)
			{
				result.Ok = false;
				result.Error = "state is null";
				return result;
			}
			if (knobs == null)
				knobs = new AdventureSimKnobs();

			if (state.Heroes == null || state.Heroes.Count == 0)
			{
				result.Ok = false;
				result.Error = "no heroes";
				return result;
			}
			var cells = state.SizeX * state.SizeZ;
			if (state.SizeX <= 0 || state.SizeZ <= 0 || cells <= 0)
			{
				result.Ok = false;
				result.Error = "invalid map size";
				return result;
			}
			if (state.Pathable == null || state.Pathable.Length != cells)
			{
				result.Ok = false;
				result.Error = "Pathable grid missing or wrong length (fail-closed)";
				return result;
			}
			if (state.Terrain != null && state.Terrain.Length != cells)
			{
				result.Ok = false;
				result.Error = "Terrain grid wrong length (fail-closed)";
				return result;
			}
			if (state.MoveCost != null && state.MoveCost.Length != cells)
			{
				result.Ok = false;
				result.Error = "MoveCost grid wrong length (fail-closed)";
				return result;
			}
			if (state.Occupancy == null || state.Occupancy.Count == 0)
			{
				result.Ok = true;
				result.Diagnostics = "no occupancy targets; empty biases";
				return result;
			}

			NormalizeHeroes(state);
			var sw = Stopwatch.StartNew();
			var depth = knobs.BeamDepth < 1 ? 1 : knobs.BeamDepth;
			var width = knobs.BeamWidth < 1 ? 1 : knobs.BeamWidth;

			var root = BeamNode.FromState(state);
			var beam = new List<BeamNode> { root };
			var best = root;
			var diag = new StringBuilder(160);

			for (var step = 0; step < depth; step++)
			{
				if (sw.ElapsedMilliseconds > knobs.TimeBudgetMs)
				{
					diag.Append("time_budget;");
					break;
				}

				var next = new List<BeamNode>();
				for (var b = 0; b < beam.Count; b++)
				{
					var node = beam[b];
					var heroIndices = knobs.MultiHero
						? Range(node.Heroes.Count)
						: new List<int> { 0 };
					var expanded = false;
					for (var hi = 0; hi < heroIndices.Count; hi++)
					{
						var heroIndex = heroIndices[hi];
						List<AdventureSimCandidateInfo> candInfo;
						var candidates = RankCandidates(state, knobs, node, heroIndex, out candInfo);
						var take = Math.Min(width, candidates.Count);
						for (var i = 0; i < take; i++)
						{
							var child = ApplyCandidate(state, knobs, node, heroIndex, candidates[i], step, candInfo);
							if (child == null)
								continue;
							next.Add(child);
							expanded = true;
							if (child.Utility > best.Utility)
								best = child;
						}
					}
					// Non-spatial stubs once per parent (no Dijkstra); tiny utility so they do not displace occupy.
					if (state.Marks.MarkedObject != 0)
						next.Add(ApplyMarkSet(node, state, step));
					AppendTownActions(state, knobs, node, step, next, ref best);
					if (!expanded)
						next.Add(EndOfDay(node, state, knobs, step));
				}

				next.Sort((a, b2) => b2.Utility.CompareTo(a.Utility));
				if (next.Count > width)
					next.RemoveRange(width, next.Count - width);
				beam = next;
				if (beam.Count == 0)
					break;
			}

			if (best.FirstKind == AdventureSimTargetKind.Unknown && best.Trace.Count == 0)
			{
				result.Ok = true;
				result.PreferredKind = AdventureSimTargetKind.Unknown;
				result.Diagnostics = diag.Append("no_beam_selection; empty biases").ToString();
				return result;
			}

			result.Ok = true;
			result.PreferredKind = best.FirstKind;
			result.PreferredId = best.FirstId;
			result.PreferredNode = best.FirstNode;
			result.PreferredHeroId = best.FirstHeroId;
			result.PreferredUtility = best.Utility;
			result.Trace = best.Trace ?? new List<AdventureSimTraceStep>();
			BuildBiases(result, best, knobs, state);

			var overlayHero = FindHero(state, best.FirstHeroId) ?? state.Heroes[0];
			var horizon = Math.Max(overlayHero.MaxMovePoints, knobs.DefaultMoveCost) * Math.Max(1, depth);
			result.ReachOverlay = AdventurePathfinder.ReachableCosts(
				state, knobs, overlayHero.Node, horizon, state.Occupancy, result.PreferredId);

			BuildStepRecords(state, knobs, best, stepSink ?? result.Steps);
			if (stepSink != null)
				result.Steps = stepSink;

			diag.Append("ms=").Append(sw.ElapsedMilliseconds)
				.Append(" preferred=").Append(best.FirstKind).Append(':').Append(best.FirstId)
				.Append(" hero=").Append(best.FirstHeroId)
				.Append(" u=").Append(best.Utility.ToString("0.###"))
				.Append(" steps=").Append(result.Steps.Count)
				.Append(" provisional_fight_knobs");
			result.Diagnostics = diag.ToString();
			return result;
		}

		private static void BuildStepRecords(
			AdventureSimState state,
			AdventureSimKnobs knobs,
			BeamNode best,
			List<AdventureSimStepRecord> sink)
		{
			sink.Clear();
			var world = BeamNode.FromState(state);
			for (var i = 0; i < best.Trace.Count; i++)
			{
				var t = best.Trace[i];
				var rec = new AdventureSimStepRecord
				{
					Index = i,
					ActionKind = t.ActionKind,
					HeroId = t.HeroId,
					FromNode = t.FromNode,
					ToNode = t.ToNode,
					PathCost = t.PathCost,
					TargetEntityId = t.EntityId,
					TargetKind = t.Kind,
					UtilityDelta = t.UtilityDelta,
					CumulativeUtility = t.CumulativeUtility,
					Note = t.Note,
					Candidates = t.Candidates ?? new List<AdventureSimCandidateInfo>(),
					Fight = t.Fight,
					TownEntityId = t.TownEntityId,
					BuildingId = t.BuildingId,
					UnitSid = t.UnitSid,
				};

				if (t.ActionKind == AdventureSimActionKind.EndDay)
				{
					rec.MpBefore = -1;
					rec.MpAfter = -1;
					ApplyEndOfDayInPlace(world, state, knobs);
				}
				else if (t.ActionKind == AdventureSimActionKind.MarkSet)
				{
					rec.MpBefore = -1;
					rec.MpAfter = -1;
				}
				else if (t.ActionKind == AdventureSimActionKind.TownBuild
					|| t.ActionKind == AdventureSimActionKind.TownHire
					|| t.ActionKind == AdventureSimActionKind.TownGarrisonTake
					|| t.ActionKind == AdventureSimActionKind.HireStub)
				{
					rec.MpBefore = -1;
					rec.MpAfter = -1;
					ApplyTownTraceInPlace(world, t);
				}
				else
				{
					var hero = FindHeroIn(world.Heroes, t.HeroId);
					rec.MpBefore = hero != null ? hero.MovePoints : 0;
					ApplyTraceInPlace(world, state, knobs, t);
					hero = FindHeroIn(world.Heroes, t.HeroId);
					rec.MpAfter = hero != null ? hero.MovePoints : 0;
				}

				rec.WorldAfter = SnapshotWorld(world, state.Day);
				sink.Add(rec);
			}
		}

		private static void ApplyTraceInPlace(BeamNode world, AdventureSimState state, AdventureSimKnobs knobs, AdventureSimTraceStep t)
		{
			var hero = FindHeroIn(world.Heroes, t.HeroId);
			if (hero == null)
				return;
			hero.Node = t.ToNode;
			hero.MovePoints = Math.Max(0, hero.MovePoints - t.PathCost);
			AdventureSimOccupant hit = null;
			for (var i = 0; i < world.Alive.Count; i++)
			{
				if (world.Alive[i].EntityId != t.EntityId)
					continue;
				hit = world.Alive[i];
				break;
			}
			if (hit == null)
				return;

			if (t.Fought)
			{
				var idx = IndexOfHero(world.Heroes, t.HeroId);
				if (idx >= 0)
					world.Heroes[idx] = AdventureFightEstimate.ApplyCasualties(hero, t.LossFraction);
			}

			if (hit.Kind == AdventureSimTargetKind.Pickup)
			{
				hit.Alive = false;
				if (hit.GoldReward > 0)
					world.Resources.Gold += hit.GoldReward;
			}
			else if (hit.Kind == AdventureSimTargetKind.Mine || hit.Kind == AdventureSimTargetKind.Town)
			{
				hit.OwnerSide = state.SideIndex;
				if (hit.Kind == AdventureSimTargetKind.Town)
					AdventureSimTownLogic.EnsureTownForCapture(world.Towns, hit.EntityId);
			}
			else
			{
				hit.Alive = false;
			}
		}

		private static void ApplyEndOfDayInPlace(BeamNode world, AdventureSimState state, AdventureSimKnobs knobs)
		{
			if (knobs.ApplyEndOfDayIncome)
			{
				var income = AdventureSimEconomy.ComputeEndOfDayGold(state, world.Alive, world.Towns);
				world.Resources.Gold += income;
			}
			for (var i = 0; i < world.Heroes.Count; i++)
				world.Heroes[i].MovePoints = world.Heroes[i].MaxMovePoints > 0 ? world.Heroes[i].MaxMovePoints : 1500;
		}

		private static void ApplyTownTraceInPlace(BeamNode world, AdventureSimTraceStep t)
		{
			if (t.ActionKind == AdventureSimActionKind.TownBuild)
			{
				var offer = FindBuild(t.BuildingId);
				if (offer != null)
					AdventureSimTownCatalog.Pay(world.Resources, offer.Gold, offer.Wood, offer.Ore);
				var town = AdventureSimTownLogic.Find(world.Towns, t.TownEntityId);
				if (town != null && !string.IsNullOrEmpty(t.BuildingId))
					town.AddBuilding(t.BuildingId);
				return;
			}
			if (t.ActionKind == AdventureSimActionKind.TownHire)
			{
				var hire = FindHire(t.BuildingId, t.UnitSid);
				if (hire != null)
					AdventureSimTownCatalog.Pay(world.Resources, hire.GoldCost, 0, 0);
				var stack = new AdventureSimStack
				{
					UnitSid = t.UnitSid,
					Stacks = hire != null ? hire.Stacks : 1,
					UnitValue = hire != null ? hire.UnitValue : 1,
				};
				var hero = FindHeroIn(world.Heroes, t.HeroId);
				if (hero != null)
					hero.Party.Add(stack);
				else
				{
					var town = AdventureSimTownLogic.Find(world.Towns, t.TownEntityId);
					if (town != null)
						town.Garrison.Add(stack);
				}
				return;
			}
			if (t.ActionKind == AdventureSimActionKind.TownGarrisonTake)
			{
				var town = AdventureSimTownLogic.Find(world.Towns, t.TownEntityId);
				var hero = FindHeroIn(world.Heroes, t.HeroId);
				if (town == null || hero == null || town.Garrison == null)
					return;
				for (var i = 0; i < town.Garrison.Count; i++)
				{
					var s = town.Garrison[i];
					if (s == null)
						continue;
					hero.Party.Add(new AdventureSimStack
					{
						UnitSid = s.UnitSid,
						Stacks = s.Stacks,
						UnitValue = s.UnitValue,
					});
				}
				town.Garrison.Clear();
			}
		}

		private static AdventureSimTownCatalog.BuildOffer FindBuild(string id)
		{
			for (var i = 0; i < AdventureSimTownCatalog.Builds.Length; i++)
			{
				if (AdventureSimTownCatalog.Builds[i].BuildingId == id)
					return AdventureSimTownCatalog.Builds[i];
			}
			return null;
		}

		private static AdventureSimTownCatalog.HireOffer FindHire(string buildingId, string unitSid)
		{
			for (var i = 0; i < AdventureSimTownCatalog.Hires.Length; i++)
			{
				var h = AdventureSimTownCatalog.Hires[i];
				if (h.BuildingId == buildingId && h.UnitSid == unitSid)
					return h;
			}
			return null;
		}

		private static AdventureSimWorldSnapshot SnapshotWorld(BeamNode world, int day)
		{
			return new AdventureSimWorldSnapshot
			{
				Day = day,
				Resources = CloneResources(world.Resources),
				Marks = CloneMarks(world.Marks),
				Heroes = CloneHeroes(world.Heroes),
				Occupancy = CloneOccupancy(world.Alive),
				Towns = AdventureSimTownLogic.CloneTowns(world.Towns),
			};
		}

		private static AdventureSimMarks CloneMarks(AdventureSimMarks m)
		{
			m = m ?? new AdventureSimMarks();
			var c = new AdventureSimMarks
			{
				MarkedCity = m.MarkedCity,
				MarkedHero = m.MarkedHero,
				MarkedObject = m.MarkedObject,
				MarkedNode = m.MarkedNode,
				MarkedEnemyCity = m.MarkedEnemyCity,
				HardStrategy = m.HardStrategy,
			};
			if (m.MarkedSquads != null)
				c.MarkedSquads = new List<int>(m.MarkedSquads);
			return c;
		}

		internal static AdventureSimHero FindHero(AdventureSimState state, int heroId)
		{
			return FindHeroIn(state.Heroes, heroId);
		}

		private static AdventureSimHero FindHeroIn(List<AdventureSimHero> heroes, int heroId)
		{
			if (heroes == null)
				return null;
			for (var i = 0; i < heroes.Count; i++)
			{
				if (heroes[i] != null && heroes[i].HeroId == heroId)
					return heroes[i];
			}
			return null;
		}

		private static int IndexOfHero(List<AdventureSimHero> heroes, int heroId)
		{
			for (var i = 0; i < heroes.Count; i++)
			{
				if (heroes[i] != null && heroes[i].HeroId == heroId)
					return i;
			}
			return -1;
		}

		private static void NormalizeHeroes(AdventureSimState state)
		{
			for (var i = 0; i < state.Heroes.Count; i++)
			{
				var h = state.Heroes[i];
				if (h.MaxMovePoints <= 0)
					h.MaxMovePoints = 1500;
				if (h.MovePoints <= 0)
					h.MovePoints = h.MaxMovePoints;
			}
		}

		private static List<int> Range(int n)
		{
			var list = new List<int>(n);
			for (var i = 0; i < n; i++)
				list.Add(i);
			return list;
		}

		private static void BuildBiases(AdventureSimResult result, BeamNode best, AdventureSimKnobs knobs, AdventureSimState state)
		{
			if (best.FirstKind == AdventureSimTargetKind.Unknown)
				return;
			result.Biases.Add(new AdventureSimBiasEntry
			{
				TargetKind = best.FirstKind,
				TargetId = best.FirstId,
				Multiplier = knobs.PreferredBiasMultiplier > 0f ? knobs.PreferredBiasMultiplier : 2.5f,
			});
			MaybeSecondary(result, knobs, AdventureSimTargetKind.Town, state.Marks.MarkedCity);
			MaybeSecondary(result, knobs, AdventureSimTargetKind.Hero, state.Marks.MarkedHero);
			MaybeSecondary(result, knobs, AdventureSimTargetKind.Pickup, state.Marks.MarkedObject);
			MaybeSecondary(result, knobs, AdventureSimTargetKind.Node, state.Marks.MarkedNode);
			MaybeSecondary(result, knobs, AdventureSimTargetKind.Mine, state.Marks.MarkedObject);
			if (state.Marks.MarkedSquads != null)
			{
				for (var i = 0; i < state.Marks.MarkedSquads.Count && i < 3; i++)
					MaybeSecondary(result, knobs, AdventureSimTargetKind.Neutral, state.Marks.MarkedSquads[i]);
			}
		}

		private static void MaybeSecondary(AdventureSimResult result, AdventureSimKnobs knobs, AdventureSimTargetKind kind, int id)
		{
			if (id == 0)
				return;
			if (kind == result.PreferredKind && id == result.PreferredId)
				return;
			for (var i = 0; i < result.Biases.Count; i++)
			{
				if (result.Biases[i].TargetKind == kind && result.Biases[i].TargetId == id)
					return;
			}
			result.Biases.Add(new AdventureSimBiasEntry
			{
				TargetKind = kind,
				TargetId = id,
				Multiplier = knobs.SecondaryBiasMultiplier > 0f ? knobs.SecondaryBiasMultiplier : 1.35f,
			});
		}

		private sealed class Candidate
		{
			public int EntityId;
			public int Node;
			public AdventureSimTargetKind Kind;
			public float Utility;
			public float LossFraction;
			public bool RequiresFight;
			public int PathCost;
			public string Note;
			public AdventureSimFightBreakdown Fight;
		}

		internal sealed class BeamNode
		{
			public List<AdventureSimHero> Heroes;
			public List<AdventureSimOccupant> Alive;
			public List<AdventureSimTown> Towns;
			public AdventureSimResources Resources;
			public AdventureSimMarks Marks;
			public float Utility;
			public AdventureSimTargetKind FirstKind;
			public int FirstId;
			public int FirstNode;
			public int FirstHeroId;
			public int Steps;
			public List<AdventureSimTraceStep> Trace;

			public static BeamNode FromState(AdventureSimState state)
			{
				return new BeamNode
				{
					Heroes = CloneHeroes(state.Heroes),
					Alive = CloneOccupancy(state.Occupancy),
					Towns = AdventureSimTownLogic.CloneTowns(state.Towns),
					Resources = CloneResources(state.Resources),
					Marks = CloneMarksStatic(state.Marks),
					Utility = 0f,
					FirstKind = AdventureSimTargetKind.Unknown,
					Trace = new List<AdventureSimTraceStep>(),
				};
			}

			private static AdventureSimMarks CloneMarksStatic(AdventureSimMarks m)
			{
				m = m ?? new AdventureSimMarks();
				var c = new AdventureSimMarks
				{
					MarkedCity = m.MarkedCity,
					MarkedHero = m.MarkedHero,
					MarkedObject = m.MarkedObject,
					MarkedNode = m.MarkedNode,
					MarkedEnemyCity = m.MarkedEnemyCity,
					HardStrategy = m.HardStrategy,
				};
				if (m.MarkedSquads != null)
					c.MarkedSquads = new List<int>(m.MarkedSquads);
				return c;
			}
		}

		private static List<Candidate> RankCandidates(
			AdventureSimState state,
			AdventureSimKnobs knobs,
			BeamNode node,
			int heroIndex,
			out List<AdventureSimCandidateInfo> info)
		{
			info = new List<AdventureSimCandidateInfo>();
			var list = new List<Candidate>();
			if (heroIndex < 0 || heroIndex >= node.Heroes.Count)
				return list;
			var hero = node.Heroes[heroIndex];
			var horizonMp = Math.Max(hero.MaxMovePoints, knobs.DefaultMoveCost) * 3;

			for (var i = 0; i < node.Alive.Count; i++)
			{
				var occ = node.Alive[i];
				if (occ == null || !occ.Alive)
					continue;

				// Reachability allowing this target as destination (occupancy blockers otherwise).
				var costsTo = AdventurePathfinder.ReachableCosts(
					state, knobs, hero.Node, horizonMp, node.Alive, occ.EntityId);
				int pathCost;
				if (!costsTo.TryGetValue(occ.Node, out pathCost))
				{
					info.Add(new AdventureSimCandidateInfo
					{
						EntityId = occ.EntityId,
						Kind = occ.Kind,
						Accepted = false,
						RejectReason = "unreachable",
					});
					continue;
				}

				var daysAway = Math.Max(1, (pathCost + Math.Max(1, hero.MovePoints) - 1) / Math.Max(1, hero.MovePoints));
				var utility = 0f;
				var loss = 0f;
				var fight = false;
				var note = occ.Label ?? occ.Kind.ToString();
				AdventureSimFightBreakdown breakdown = null;

				switch (occ.Kind)
				{
					case AdventureSimTargetKind.Neutral:
					case AdventureSimTargetKind.Hero:
						{
							fight = true;
							var outcome = AdventureFightEstimate.Estimate(hero, occ, knobs);
							breakdown = AdventureFightEstimate.ToBreakdown(outcome, knobs);
							if (!outcome.CanWin)
							{
								info.Add(new AdventureSimCandidateInfo
								{
									EntityId = occ.EntityId,
									Kind = occ.Kind,
									Accepted = false,
									RejectReason = "unwinnable " + outcome.Summary,
									PathCost = pathCost,
									RequiresFight = true,
								});
								continue;
							}
							loss = outcome.ExpectedLossFraction;
							utility = occ.StartValue * (1f - loss) / daysAway + 80f / daysAway;
							note = outcome.Summary;
							break;
						}
					case AdventureSimTargetKind.Town:
						utility = 6000f / daysAway + (occ.OwnerSide == state.SideIndex ? -2000f : 0f);
						break;
					case AdventureSimTargetKind.Mine:
						utility = 2500f / daysAway + occ.GoldReward * 0.5f;
						break;
					case AdventureSimTargetKind.Pickup:
						utility = 900f / daysAway + occ.GoldReward;
						break;
					default:
						utility = 200f / daysAway;
						break;
				}

				if (IsMarked(state.Marks, occ))
					utility *= 1.15f;

				list.Add(new Candidate
				{
					EntityId = occ.EntityId,
					Node = occ.Node,
					Kind = occ.Kind,
					Utility = utility,
					LossFraction = loss,
					RequiresFight = fight,
					PathCost = pathCost,
					Note = note,
					Fight = breakdown,
				});
				info.Add(new AdventureSimCandidateInfo
				{
					EntityId = occ.EntityId,
					Kind = occ.Kind,
					Utility = utility,
					Accepted = true,
					PathCost = pathCost,
					RequiresFight = fight,
				});
			}

			list.Sort((a, b) => b.Utility.CompareTo(a.Utility));
			info.Sort((a, b) =>
			{
				if (a.Accepted != b.Accepted)
					return a.Accepted ? -1 : 1;
				return b.Utility.CompareTo(a.Utility);
			});
			return list;
		}

		private static bool IsMarked(AdventureSimMarks marks, AdventureSimOccupant occ)
		{
			if (marks == null || occ == null)
				return false;
			if (occ.EntityId == marks.MarkedCity || occ.EntityId == marks.MarkedHero
				|| occ.EntityId == marks.MarkedObject || occ.EntityId == marks.MarkedEnemyCity)
				return true;
			if (marks.MarkedSquads != null && marks.MarkedSquads.Contains(occ.EntityId))
				return true;
			return false;
		}

		private static void AppendTownActions(
			AdventureSimState state,
			AdventureSimKnobs knobs,
			BeamNode parent,
			int depth,
			List<BeamNode> next,
			ref BeamNode best)
		{
			if (parent.Towns == null || parent.Alive == null)
				return;
			for (var ti = 0; ti < parent.Towns.Count; ti++)
			{
				var town = parent.Towns[ti];
				if (town == null)
					continue;
				var occ = AdventureSimTownLogic.FindOwnedTownOcc(state, parent.Alive, town.EntityId);
				if (occ == null)
					continue;

				for (var b = 0; b < AdventureSimTownCatalog.Builds.Length; b++)
				{
					var offer = AdventureSimTownCatalog.Builds[b];
					if (town.Has(offer.BuildingId))
						continue;
					if (!string.IsNullOrEmpty(offer.Requires) && !town.Has(offer.Requires))
						continue;
					if (!AdventureSimTownCatalog.CanAfford(parent.Resources, offer.Gold, offer.Wood, offer.Ore))
						continue;
					var child = ApplyTownBuild(parent, town.EntityId, offer, depth);
					next.Add(child);
					if (child.Utility > best.Utility)
						best = child;
				}

				for (var h = 0; h < AdventureSimTownCatalog.Hires.Length; h++)
				{
					var hire = AdventureSimTownCatalog.Hires[h];
					if (!town.Has(hire.BuildingId))
						continue;
					if (!AdventureSimTownCatalog.CanAfford(parent.Resources, hire.GoldCost, 0, 0))
						continue;
					// Prefer hiring onto a hero currently at the town; else into garrison.
					var heroIndex = 0;
					for (var i = 0; i < parent.Heroes.Count; i++)
					{
						if (AdventureSimTownLogic.HeroAtTown(parent.Heroes, i, occ.Node))
						{
							heroIndex = i;
							break;
						}
					}
					var child = ApplyTownHire(parent, town.EntityId, hire, heroIndex, occ.Node, depth);
					next.Add(child);
					if (child.Utility > best.Utility)
						best = child;
				}

				if (town.Garrison != null && town.Garrison.Count > 0)
				{
					for (var i = 0; i < parent.Heroes.Count; i++)
					{
						if (!AdventureSimTownLogic.HeroAtTown(parent.Heroes, i, occ.Node))
							continue;
						var child = ApplyTownGarrisonTake(parent, town.EntityId, i, depth);
						next.Add(child);
						if (child.Utility > best.Utility)
							best = child;
						break;
					}
				}
			}
		}

		private static BeamNode ApplyTownBuild(BeamNode parent, int townId, AdventureSimTownCatalog.BuildOffer offer, int depth)
		{
			var child = CloneBeamShell(parent);
			child.Utility = parent.Utility + offer.UtilityBonus;
			child.Steps = parent.Steps + 1;
			AdventureSimTownCatalog.Pay(child.Resources, offer.Gold, offer.Wood, offer.Ore);
			var town = AdventureSimTownLogic.Find(child.Towns, townId);
			if (town != null)
				town.AddBuilding(offer.BuildingId);
			child.Trace.Add(new AdventureSimTraceStep
			{
				Depth = depth,
				HeroId = -1,
				Kind = AdventureSimTargetKind.Town,
				EntityId = townId,
				ActionKind = AdventureSimActionKind.TownBuild,
				TownEntityId = townId,
				BuildingId = offer.BuildingId,
				UtilityDelta = offer.UtilityBonus,
				CumulativeUtility = child.Utility,
				Note = "PROVISIONAL town build " + offer.Label + " (-" + offer.Gold + "g)",
				Candidates = new List<AdventureSimCandidateInfo>(),
			});
			return child;
		}

		private static BeamNode ApplyTownHire(
			BeamNode parent,
			int townId,
			AdventureSimTownCatalog.HireOffer hire,
			int heroIndex,
			int townNode,
			int depth)
		{
			var child = CloneBeamShell(parent);
			child.Utility = parent.Utility + hire.UtilityBonus;
			child.Steps = parent.Steps + 1;
			AdventureSimTownCatalog.Pay(child.Resources, hire.GoldCost, 0, 0);
			var stack = new AdventureSimStack
			{
				UnitSid = hire.UnitSid,
				Stacks = hire.Stacks,
				UnitValue = hire.UnitValue,
			};
			var atTown = AdventureSimTownLogic.HeroAtTown(child.Heroes, heroIndex, townNode);
			string dest;
			if (atTown && heroIndex >= 0 && heroIndex < child.Heroes.Count)
			{
				child.Heroes[heroIndex].Party.Add(stack);
				dest = "hero " + child.Heroes[heroIndex].HeroId;
			}
			else
			{
				var town = AdventureSimTownLogic.Find(child.Towns, townId);
				if (town != null)
					town.Garrison.Add(stack);
				dest = "garrison";
			}
			child.Trace.Add(new AdventureSimTraceStep
			{
				Depth = depth,
				HeroId = atTown && heroIndex >= 0 && heroIndex < child.Heroes.Count
					? child.Heroes[heroIndex].HeroId
					: -1,
				Kind = AdventureSimTargetKind.Town,
				EntityId = townId,
				ActionKind = AdventureSimActionKind.TownHire,
				TownEntityId = townId,
				UnitSid = hire.UnitSid,
				BuildingId = hire.BuildingId,
				UtilityDelta = hire.UtilityBonus,
				CumulativeUtility = child.Utility,
				Note = "PROVISIONAL hire " + hire.Stacks + "x " + hire.UnitSid + " -> " + dest + " (-" + hire.GoldCost + "g)",
				Candidates = new List<AdventureSimCandidateInfo>(),
			});
			return child;
		}

		private static BeamNode ApplyTownGarrisonTake(BeamNode parent, int townId, int heroIndex, int depth)
		{
			var child = CloneBeamShell(parent);
			child.Utility = parent.Utility + 80f;
			child.Steps = parent.Steps + 1;
			var town = AdventureSimTownLogic.Find(child.Towns, townId);
			var hero = child.Heroes[heroIndex];
			var moved = 0;
			if (town != null && town.Garrison != null)
			{
				for (var i = 0; i < town.Garrison.Count; i++)
				{
					var s = town.Garrison[i];
					if (s == null)
						continue;
					hero.Party.Add(new AdventureSimStack
					{
						UnitSid = s.UnitSid,
						Stacks = s.Stacks,
						UnitValue = s.UnitValue,
					});
					moved++;
				}
				town.Garrison.Clear();
			}
			child.Trace.Add(new AdventureSimTraceStep
			{
				Depth = depth,
				HeroId = hero.HeroId,
				Kind = AdventureSimTargetKind.Town,
				EntityId = townId,
				ActionKind = AdventureSimActionKind.TownGarrisonTake,
				TownEntityId = townId,
				FromNode = hero.Node,
				ToNode = hero.Node,
				UtilityDelta = 80f,
				CumulativeUtility = child.Utility,
				Note = "take garrison stacks=" + moved,
				Candidates = new List<AdventureSimCandidateInfo>(),
			});
			return child;
		}

		private static BeamNode CloneBeamShell(BeamNode parent)
		{
			return new BeamNode
			{
				Heroes = CloneHeroes(parent.Heroes),
				Alive = CloneOccupancy(parent.Alive),
				Towns = AdventureSimTownLogic.CloneTowns(parent.Towns),
				Resources = CloneResources(parent.Resources),
				Marks = parent.Marks,
				Utility = parent.Utility,
				FirstKind = parent.FirstKind,
				FirstId = parent.FirstId,
				FirstNode = parent.FirstNode,
				FirstHeroId = parent.FirstHeroId,
				Steps = parent.Steps,
				Trace = new List<AdventureSimTraceStep>(parent.Trace),
			};
		}

		private static BeamNode ApplyMarkSet(BeamNode parent, AdventureSimState state, int depth)
		{
			var child = CloneBeamShell(parent);
			child.Utility = parent.Utility + 0.01f;
			child.Steps = parent.Steps + 1;
			child.Trace.Add(new AdventureSimTraceStep
			{
				Depth = depth,
				HeroId = -1,
				Kind = AdventureSimTargetKind.Node,
				EntityId = state.Marks.MarkedObject,
				ActionKind = AdventureSimActionKind.MarkSet,
				UtilityDelta = 0.01f,
				CumulativeUtility = child.Utility,
				Note = "mark-set reinforce (no pathing)",
				Candidates = new List<AdventureSimCandidateInfo>(),
			});
			return child;
		}

		private static BeamNode ApplyCandidate(
			AdventureSimState state,
			AdventureSimKnobs knobs,
			BeamNode parent,
			int heroIndex,
			Candidate c,
			int depth,
			List<AdventureSimCandidateInfo> candInfo)
		{
			var heroes = CloneHeroes(parent.Heroes);
			var hero = heroes[heroIndex];
			var from = hero.Node;
			var mpBefore = hero.MovePoints;
			hero.Node = c.Node;
			hero.MovePoints = Math.Max(0, hero.MovePoints - c.PathCost);

			var alive = CloneOccupancy(parent.Alive);
			AdventureSimOccupant hit = null;
			for (var i = 0; i < alive.Count; i++)
			{
				if (alive[i].EntityId == c.EntityId)
				{
					hit = alive[i];
					break;
				}
			}

			var resources = CloneResources(parent.Resources);
			var towns = AdventureSimTownLogic.CloneTowns(parent.Towns);
			if (hit != null)
			{
				if (c.RequiresFight)
					heroes[heroIndex] = AdventureFightEstimate.ApplyCasualties(hero, c.LossFraction);

				if (hit.Kind == AdventureSimTargetKind.Pickup)
				{
					hit.Alive = false;
					if (hit.GoldReward > 0)
						resources.Gold += hit.GoldReward;
				}
				else if (hit.Kind == AdventureSimTargetKind.Mine || hit.Kind == AdventureSimTargetKind.Town)
				{
					hit.OwnerSide = state.SideIndex;
					if (hit.Kind == AdventureSimTargetKind.Town)
						AdventureSimTownLogic.EnsureTownForCapture(towns, hit.EntityId);
				}
				else
				{
					hit.Alive = false;
				}
			}

			var child = new BeamNode
			{
				Heroes = heroes,
				Alive = alive,
				Towns = towns,
				Resources = resources,
				Marks = parent.Marks,
				Utility = parent.Utility + c.Utility,
				Steps = parent.Steps + 1,
				FirstKind = parent.Steps == 0 ? c.Kind : parent.FirstKind,
				FirstId = parent.Steps == 0 ? c.EntityId : parent.FirstId,
				FirstNode = parent.Steps == 0 ? c.Node : parent.FirstNode,
				FirstHeroId = parent.Steps == 0 ? hero.HeroId : parent.FirstHeroId,
				Trace = new List<AdventureSimTraceStep>(parent.Trace),
			};
			child.Trace.Add(new AdventureSimTraceStep
			{
				Depth = depth,
				HeroId = hero.HeroId,
				Kind = c.Kind,
				EntityId = c.EntityId,
				FromNode = from,
				ToNode = c.Node,
				PathCost = c.PathCost,
				UtilityDelta = c.Utility,
				CumulativeUtility = child.Utility,
				Fought = c.RequiresFight,
				LossFraction = c.LossFraction,
				Note = c.Note,
				ActionKind = AdventureSimActionKind.MoveToOccupy,
				Candidates = candInfo,
				Fight = c.Fight,
			});

			if (heroes[heroIndex].MovePoints <= knobs.DefaultMoveCost / 2)
				return EndOfDay(child, state, knobs, depth);
			return child;
		}

		private static BeamNode EndOfDay(BeamNode node, AdventureSimState state, AdventureSimKnobs knobs, int depth)
		{
			var clone = new BeamNode
			{
				Heroes = CloneHeroes(node.Heroes),
				Alive = CloneOccupancy(node.Alive),
				Towns = AdventureSimTownLogic.CloneTowns(node.Towns),
				Resources = CloneResources(node.Resources),
				Marks = node.Marks,
				Utility = node.Utility,
				Steps = node.Steps,
				FirstKind = node.FirstKind,
				FirstId = node.FirstId,
				FirstNode = node.FirstNode,
				FirstHeroId = node.FirstHeroId,
				Trace = new List<AdventureSimTraceStep>(node.Trace),
			};
			var income = 0;
			if (knobs.ApplyEndOfDayIncome)
			{
				income = AdventureSimEconomy.ComputeEndOfDayGold(state, clone.Alive, clone.Towns);
				clone.Resources.Gold += income;
				clone.Utility += income * 0.001f;
			}
			for (var i = 0; i < clone.Heroes.Count; i++)
				clone.Heroes[i].MovePoints = clone.Heroes[i].MaxMovePoints > 0 ? clone.Heroes[i].MaxMovePoints : 1500;
			clone.Trace.Add(new AdventureSimTraceStep
			{
				Depth = depth,
				HeroId = -1,
				Kind = AdventureSimTargetKind.Unknown,
				ActionKind = AdventureSimActionKind.EndDay,
				Note = "end_of_day gold+=" + income + " (base " + state.DailyGoldIncome + " + mines + towns)",
				UtilityDelta = income * 0.001f,
				CumulativeUtility = clone.Utility,
				Candidates = new List<AdventureSimCandidateInfo>(),
			});
			return clone;
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

		private static List<AdventureSimOccupant> CloneOccupancy(List<AdventureSimOccupant> source)
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

		private static AdventureSimResources CloneResources(AdventureSimResources r)
		{
			r = r ?? new AdventureSimResources();
			return new AdventureSimResources
			{
				Gold = r.Gold,
				Wood = r.Wood,
				Ore = r.Ore,
				Gemstones = r.Gemstones,
				Crystals = r.Crystals,
				Mercury = r.Mercury,
			};
		}
	}
}
