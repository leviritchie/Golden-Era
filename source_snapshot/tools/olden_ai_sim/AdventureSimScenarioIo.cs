using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;

namespace OldenAiSim
{
	/// <summary>
	/// Dependency-free scenario text format for offline save/load.
	/// Fail-closed on missing schema, bad sizes, or unparsable integers.
	/// </summary>
	public static class AdventureSimScenarioIo
	{
		public static void Save(AdventureSimState state, string path)
		{
			if (state == null)
				throw new ArgumentNullException(nameof(state));
			File.WriteAllText(path, ToText(state), Encoding.UTF8);
		}

		public static AdventureSimState Load(string path)
		{
			return FromText(File.ReadAllText(path, Encoding.UTF8));
		}

		public static string ToText(AdventureSimState state)
		{
			var sb = new StringBuilder();
			sb.AppendLine("schema=" + AdventureSimState.SchemaVersion);
			sb.AppendLine("name=" + (state.ScenarioName ?? ""));
			sb.AppendLine("day=" + state.Day);
			sb.AppendLine("side=" + state.SideIndex);
			sb.AppendLine("sideName=" + (state.SideName ?? ""));
			sb.AppendLine("sizeX=" + state.SizeX);
			sb.AppendLine("sizeZ=" + state.SizeZ);
			sb.AppendLine("dailyGold=" + state.DailyGoldIncome);
			sb.AppendLine("gold=" + state.Resources.Gold);
			sb.AppendLine("wood=" + state.Resources.Wood);
			sb.AppendLine("ore=" + state.Resources.Ore);
			sb.AppendLine("gemstones=" + state.Resources.Gemstones);
			sb.AppendLine("crystals=" + state.Resources.Crystals);
			sb.AppendLine("mercury=" + state.Resources.Mercury);
			sb.AppendLine("markedCity=" + state.Marks.MarkedCity);
			sb.AppendLine("markedHero=" + state.Marks.MarkedHero);
			sb.AppendLine("markedObject=" + state.Marks.MarkedObject);
			sb.AppendLine("markedNode=" + state.Marks.MarkedNode);
			sb.AppendLine("markedEnemyCity=" + state.Marks.MarkedEnemyCity);
			if (!string.IsNullOrEmpty(state.Marks.HardStrategy))
				sb.AppendLine("hardStrategy=" + Escape(state.Marks.HardStrategy));
			if (state.Marks.MarkedSquads != null && state.Marks.MarkedSquads.Count > 0)
				sb.AppendLine("markedSquads=" + string.Join(",", state.Marks.MarkedSquads));
			if (state.Pathable != null)
				sb.AppendLine("pathable=" + PackBools(state.Pathable));
			if (state.Terrain != null)
				sb.AppendLine("terrain=" + PackBytes(state.Terrain));
			if (state.Road != null)
				sb.AppendLine("road=" + PackBytes(state.Road));
			if (state.MoveCost != null)
				sb.AppendLine("moveCost=" + PackInts(state.MoveCost));
			if (state.Portals != null)
			{
				foreach (var kv in state.Portals)
				{
					if (kv.Value == null)
						continue;
					for (var i = 0; i < kv.Value.Count; i++)
					{
						if (kv.Key < kv.Value[i])
							sb.AppendLine("portal=" + kv.Key + "," + kv.Value[i]);
					}
				}
			}

			for (var i = 0; i < state.Heroes.Count; i++)
			{
				var h = state.Heroes[i];
				sb.Append("hero=").Append(h.HeroId).Append(',').Append(h.Node).Append(',')
					.Append(h.MovePoints).Append(',').Append(h.MaxMovePoints).Append(',')
					.Append(h.Mana).Append(',').Append(Escape(h.Name));
				if (h.Party != null)
				{
					for (var p = 0; p < h.Party.Count; p++)
					{
						var s = h.Party[p];
						if (s == null)
							continue;
						sb.Append(";stack=").Append(s.Stacks).Append(',')
							.Append(s.UnitValue).Append(',').Append(Escape(s.UnitSid ?? ""));
					}
				}
				sb.AppendLine();
			}
			for (var i = 0; i < state.Occupancy.Count; i++)
			{
				var o = state.Occupancy[i];
				sb.Append("occ=").Append(o.EntityId).Append(',').Append(o.Node).Append(',')
					.Append((int)o.Kind).Append(',').Append(o.StartValue).Append(',')
					.Append(o.Alive ? 1 : 0).Append(',').Append(o.OwnerSide).Append(',')
					.Append(o.GoldReward).Append(',').Append(Escape(o.Label))
					.AppendLine();
			}
			return sb.ToString();
		}

		public static AdventureSimState FromText(string text)
		{
			if (string.IsNullOrWhiteSpace(text))
				throw new InvalidOperationException("empty scenario text");

			var state = new AdventureSimState();
			var lines = text.Replace("\r\n", "\n").Split('\n');
			string pathablePack = null;
			string terrainPack = null;
			string moveCostPack = null;
			string roadPack = null;
			var sawSchema = false;
			var portals = new List<int[]>();

			for (var i = 0; i < lines.Length; i++)
			{
				var line = lines[i].Trim();
				if (line.Length == 0 || line.StartsWith("#", StringComparison.Ordinal))
					continue;
				var eq = line.IndexOf('=');
				if (eq <= 0)
					throw new InvalidOperationException("malformed line " + (i + 1) + ": " + line);
				var key = line.Substring(0, eq);
				var val = line.Substring(eq + 1);
				switch (key)
				{
					case "schema":
						if (val != AdventureSimState.SchemaVersion)
							throw new InvalidOperationException("unsupported schema '" + val + "'");
						sawSchema = true;
						break;
					case "name": state.ScenarioName = val; break;
					case "day": state.Day = RequireInt(val, "day"); break;
					case "side": state.SideIndex = RequireInt(val, "side"); break;
					case "sideName": state.SideName = val; break;
					case "sizeX": state.SizeX = RequireInt(val, "sizeX"); break;
					case "sizeZ": state.SizeZ = RequireInt(val, "sizeZ"); break;
					case "dailyGold": state.DailyGoldIncome = RequireInt(val, "dailyGold"); break;
					case "gold": state.Resources.Gold = RequireInt(val, "gold"); break;
					case "wood": state.Resources.Wood = RequireInt(val, "wood"); break;
					case "ore": state.Resources.Ore = RequireInt(val, "ore"); break;
					case "gemstones": state.Resources.Gemstones = RequireInt(val, "gemstones"); break;
					case "crystals": state.Resources.Crystals = RequireInt(val, "crystals"); break;
					case "mercury": state.Resources.Mercury = RequireInt(val, "mercury"); break;
					case "markedCity": state.Marks.MarkedCity = RequireInt(val, "markedCity"); break;
					case "markedHero": state.Marks.MarkedHero = RequireInt(val, "markedHero"); break;
					case "markedObject": state.Marks.MarkedObject = RequireInt(val, "markedObject"); break;
					case "markedNode": state.Marks.MarkedNode = RequireInt(val, "markedNode"); break;
					case "markedEnemyCity": state.Marks.MarkedEnemyCity = RequireInt(val, "markedEnemyCity"); break;
					case "hardStrategy": state.Marks.HardStrategy = Unescape(val); break;
					case "markedSquads":
						ParseMarkedSquads(state, val);
						break;
					case "pathable": pathablePack = val; break;
					case "terrain": terrainPack = val; break;
					case "road": roadPack = val; break;
					case "moveCost": moveCostPack = val; break;
					case "portal":
						{
							var parts = val.Split(',');
							if (parts.Length != 2)
								throw new InvalidOperationException("portal needs a,b at line " + (i + 1));
							portals.Add(new[] { RequireInt(parts[0], "portalA"), RequireInt(parts[1], "portalB") });
							break;
						}
					case "hero":
						ParseHero(state, val, i + 1);
						break;
					case "occ":
						ParseOcc(state, val, i + 1);
						break;
					default:
						throw new InvalidOperationException("unknown key '" + key + "' at line " + (i + 1));
				}
			}

			if (!sawSchema)
				throw new InvalidOperationException("missing schema=" + AdventureSimState.SchemaVersion);
			if (state.SizeX <= 0 || state.SizeZ <= 0)
				throw new InvalidOperationException("sizeX/sizeZ must be positive");

			var cells = state.SizeX * state.SizeZ;
			if (pathablePack == null)
				throw new InvalidOperationException("missing pathable= grid");
			if (pathablePack.Length != cells)
				throw new InvalidOperationException("pathable length " + pathablePack.Length + " != " + cells);
			state.Pathable = UnpackBools(pathablePack, cells);

			if (terrainPack != null)
			{
				if (terrainPack.Length != cells * 2)
					throw new InvalidOperationException("terrain pack length mismatch");
				state.Terrain = UnpackBytes(terrainPack, cells);
			}
			else
			{
				state.Terrain = new byte[cells];
			}

			if (roadPack != null)
			{
				if (roadPack.Length != cells * 2)
					throw new InvalidOperationException("road pack length mismatch");
				state.Road = UnpackBytes(roadPack, cells);
			}
			else
			{
				state.Road = new byte[cells];
			}

			if (moveCostPack != null)
			{
				state.MoveCost = UnpackInts(moveCostPack, cells);
			}

			state.Portals = new Dictionary<int, List<int>>();
			for (var i = 0; i < portals.Count; i++)
			{
				var a = portals[i][0];
				var b = portals[i][1];
				if (a < 0 || b < 0 || a >= cells || b >= cells)
					throw new InvalidOperationException("portal out of bounds: " + a + "," + b);
				AdventurePathfinder.AddPortal(state, a, b);
			}

			return state;
		}

		private static void ParseMarkedSquads(AdventureSimState state, string val)
		{
			if (string.IsNullOrWhiteSpace(val))
				return;
			var parts = val.Split(',');
			for (var i = 0; i < parts.Length; i++)
				state.Marks.MarkedSquads.Add(RequireInt(parts[i].Trim(), "markedSquads"));
		}

		private static void ParseHero(AdventureSimState state, string val, int line)
		{
			var semi = val.Split(new[] { ';' }, StringSplitOptions.None);
			var p = SplitCsv(semi[0]);
			if (p.Count < 5)
				throw new InvalidOperationException("hero record too short at line " + line);
			var h = new AdventureSimHero
			{
				HeroId = RequireInt(p[0], "heroId"),
				Node = RequireInt(p[1], "heroNode"),
				MovePoints = RequireInt(p[2], "movePoints"),
				MaxMovePoints = RequireInt(p[3], "maxMovePoints"),
				Mana = RequireInt(p[4], "mana"),
				Name = p.Count > 5 ? Unescape(p[5]) : null,
			};
			for (var i = 1; i < semi.Length; i++)
			{
				var part = semi[i];
				if (!part.StartsWith("stack=", StringComparison.Ordinal))
					throw new InvalidOperationException("expected stack= at line " + line);
				var sp = SplitCsv(part.Substring(6));
				if (sp.Count < 3)
					throw new InvalidOperationException("stack record too short at line " + line);
				h.Party.Add(new AdventureSimStack
				{
					Stacks = RequireInt(sp[0], "stacks"),
					UnitValue = RequireInt(sp[1], "unitValue"),
					UnitSid = Unescape(sp[2]),
				});
			}
			state.Heroes.Add(h);
		}

		private static void ParseOcc(AdventureSimState state, string val, int line)
		{
			var p = SplitCsv(val);
			if (p.Count < 8)
				throw new InvalidOperationException("occ record too short at line " + line);
			state.Occupancy.Add(new AdventureSimOccupant
			{
				EntityId = RequireInt(p[0], "entityId"),
				Node = RequireInt(p[1], "occNode"),
				Kind = (AdventureSimTargetKind)RequireInt(p[2], "kind"),
				StartValue = RequireInt(p[3], "startValue"),
				Alive = RequireInt(p[4], "alive") != 0,
				OwnerSide = RequireInt(p[5], "ownerSide"),
				GoldReward = RequireInt(p[6], "goldReward"),
				Label = Unescape(p[7]),
			});
		}

		private static List<string> SplitCsv(string val)
		{
			var list = new List<string>();
			var sb = new StringBuilder();
			for (var i = 0; i < val.Length; i++)
			{
				var c = val[i];
				if (c == '\\' && i + 1 < val.Length)
				{
					sb.Append(val[++i]);
					continue;
				}
				if (c == ',')
				{
					list.Add(sb.ToString());
					sb.Clear();
					continue;
				}
				sb.Append(c);
			}
			list.Add(sb.ToString());
			return list;
		}

		private static string Escape(string s)
		{
			if (string.IsNullOrEmpty(s))
				return "";
			return s.Replace("\\", "\\\\").Replace(",", "\\,").Replace(";", "\\;").Replace("\n", " ");
		}

		private static string Unescape(string s)
		{
			if (string.IsNullOrEmpty(s))
				return "";
			var sb = new StringBuilder(s.Length);
			for (var i = 0; i < s.Length; i++)
			{
				if (s[i] == '\\' && i + 1 < s.Length)
				{
					sb.Append(s[++i]);
					continue;
				}
				sb.Append(s[i]);
			}
			return sb.ToString();
		}

		private static int RequireInt(string s, string field)
		{
			int v;
			if (!int.TryParse(s, NumberStyles.Integer, CultureInfo.InvariantCulture, out v))
				throw new InvalidOperationException("invalid int for " + field + ": '" + s + "'");
			return v;
		}

		private static string PackBools(bool[] a)
		{
			var sb = new StringBuilder(a.Length);
			for (var i = 0; i < a.Length; i++)
				sb.Append(a[i] ? '1' : '0');
			return sb.ToString();
		}

		private static bool[] UnpackBools(string pack, int len)
		{
			var a = new bool[len];
			for (var i = 0; i < len; i++)
			{
				var c = pack[i];
				if (c != '0' && c != '1')
					throw new InvalidOperationException("pathable digit must be 0/1");
				a[i] = c == '1';
			}
			return a;
		}

		private static string PackBytes(byte[] a)
		{
			var sb = new StringBuilder(a.Length * 2);
			for (var i = 0; i < a.Length; i++)
				sb.Append(a[i].ToString("x2", CultureInfo.InvariantCulture));
			return sb.ToString();
		}

		private static byte[] UnpackBytes(string pack, int len)
		{
			var a = new byte[len];
			for (var i = 0; i < len; i++)
			{
				var ix = i * 2;
				byte b;
				if (!byte.TryParse(pack.Substring(ix, 2), NumberStyles.HexNumber, CultureInfo.InvariantCulture, out b))
					throw new InvalidOperationException("bad terrain byte at index " + i);
				a[i] = b;
			}
			return a;
		}

		private static string PackInts(int[] a)
		{
			var sb = new StringBuilder();
			for (var i = 0; i < a.Length; i++)
			{
				if (i > 0)
					sb.Append(',');
				sb.Append(a[i].ToString(CultureInfo.InvariantCulture));
			}
			return sb.ToString();
		}

		private static int[] UnpackInts(string pack, int len)
		{
			var parts = pack.Split(',');
			if (parts.Length != len)
				throw new InvalidOperationException("moveCost length " + parts.Length + " != " + len);
			var a = new int[len];
			for (var i = 0; i < len; i++)
				a[i] = RequireInt(parts[i], "moveCost");
			return a;
		}
	}
}
