using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text;
using HarmonyLib;
using Il2CppInterop.Runtime.InteropTypes;
using Hex.Session.Battle;

/// <summary>
/// Volatile diagnostic: dump TransferSide native ptr vs bridged Unit.Init TransferSide,
/// wrapper localSideIndex, TransferSide.sideIdInWorld, and DataSide identity so Split
/// Assembly plan→unit match key can be chosen (side index vs DataSide vs TransferSide ptr).
/// Harmony events append to live_probe_bridge/artifacts/split_assembly_match_key.jsonl.
/// </summary>
public static class SplitAssemblyMatchKey20260725
{
	private const string HarmonyId = "offlineunlock.split.assembly.matchkey.20260725";
	private const string MarkerRelative = "artifacts/split_assembly_match_key.installed";
	private const string LogRelative = "artifacts/split_assembly_match_key.jsonl";
	private const string SummaryRelative = "artifacts/split_assembly_match_key_summary.json";

	private static readonly string[] BattleSideTransferSideMembers =
	{
		"cgle", "get_field_Public_TransferSide_0", "field_Public_TransferSide_0"
	};

	private static readonly string[] WrapperLocalSideIndexMembers =
	{
		"field_Public_Int32_0", "get_field_Public_Int32_0"
	};

	private static readonly string[] TransferSideSideIdMembers =
	{
		"sideIdInWorld", "get_sideIdInWorld", "field_Public_Int32_1", "get_field_Public_Int32_1",
		"field_Public_Int32_0", "get_field_Public_Int32_0", "cglb"
	};

	private static readonly string[] SidMembers =
	{
		"configSid", "sid", "id", "unitSid", "get_configSid", "get_sid"
	};

	private static readonly object Gate = new object();
	private static bool _patchedThisLoad;
	private static string _bridgeRoot;
	private static readonly List<string> PlanSideKeys = new List<string>(8);
	private static readonly Dictionary<string, int> PlanByTransferPtr = new Dictionary<string, int>();
	private static readonly Dictionary<int, int> PlanByLocalSideIndex = new Dictionary<int, int>();
	private static readonly Dictionary<string, int> PlanByDataSidePtr = new Dictionary<string, int>();
	private static int _unitEvents;
	private static int _matchTransferPtr;
	private static int _matchLocalSideIndex;
	private static int _matchDataSidePtr;
	private static int _factoryUnits;

	public static string Run()
	{
		return Install();
	}

	public static string Install()
	{
		try
		{
			EnsureBridgeRoot();
			Directory.CreateDirectory(Path.Combine(_bridgeRoot, "artifacts"));
			if (!File.Exists(MarkerPath()))
			{
				var harmony = new Harmony(HarmonyId);
				PatchBattleLogicInit(harmony);
				PatchUnitInit(harmony);
				WriteUtf8(MarkerPath(), DateTime.UtcNow.ToString("o"));
				AppendEvent("{\"event\":\"installed-new\"}");
			}
			else if (!_patchedThisLoad)
			{
				AppendEvent("{\"event\":\"install-skipped-already-marked\"}");
			}
			_patchedThisLoad = true;
			return Status("installed");
		}
		catch (Exception ex)
		{
			return Fail("install-failed", ex);
		}
	}

	public static string Clear()
	{
		EnsureBridgeRoot();
		Directory.CreateDirectory(Path.Combine(_bridgeRoot, "artifacts"));
		lock (Gate)
		{
			PlanSideKeys.Clear();
			PlanByTransferPtr.Clear();
			PlanByLocalSideIndex.Clear();
			PlanByDataSidePtr.Clear();
			_unitEvents = 0;
			_matchTransferPtr = 0;
			_matchLocalSideIndex = 0;
			_matchDataSidePtr = 0;
			_factoryUnits = 0;
		}
		WriteUtf8(LogPath(), "");
		TryDelete(SummaryPath());
		AppendEvent("{\"event\":\"cleared\"}");
		return Status("cleared");
	}

	public static string Dump()
	{
		WriteSummary();
		return Status("dump");
	}

	public static string Snapshot()
	{
		return DumpRegistrySnapshot();
	}

	private static void PatchBattleLogicInit(Harmony harmony)
	{
		var battleLogicType = ResolveType(
			typeof(TransferBattle).Assembly,
			"ObjectPublicPrcfInPrcfSiBoPrcfInUnique",
			"eep",
			"eeh",
			"eeo");
		if (battleLogicType == null)
			throw new MissingMemberException("BattleLogic type not found");

		MethodInfo init = null;
		foreach (var method in battleLogicType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
		{
			if (!string.Equals(method.Name, "Init", StringComparison.Ordinal))
				continue;
			var ps = method.GetParameters();
			if (ps.Length == 4
			    && ps[0].ParameterType == typeof(int)
			    && ps[1].ParameterType == typeof(TransferBattle)
			    && ps[2].ParameterType == typeof(bool)
			    && ps[3].ParameterType == typeof(bool)
			    && method.ReturnType == typeof(void))
			{
				init = method;
				break;
			}
		}
		if (init == null)
			throw new MissingMethodException("BattleLogic.Init(int,TransferBattle,bool,bool) not found");

		// PREFIX: capture TransferBattle.sides keys before nested Unit.Init runs.
		var prefix = AccessTools.Method(typeof(SplitAssemblyMatchKey20260725), nameof(PrefixBattleLogicInit));
		var postfix = AccessTools.Method(typeof(SplitAssemblyMatchKey20260725), nameof(PostfixBattleLogicInit));
		harmony.Patch(
			init,
			prefix: new HarmonyMethod(prefix) { priority = Priority.Low },
			postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
	}

	private static void PatchUnitInit(Harmony harmony)
	{
		MethodInfo init = null;
		// Prefer product shared resolver when available (live Init shape gate).
		try
		{
			var mod = FindAssembly("OfflineUnlockMod");
			var surface = mod?.GetType("OfflineUnlockMod.Homm3BattleUnitInitSurface", false);
			var find = surface?.GetMethod("FindUnitInitMethod", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
			if (find != null)
				init = find.Invoke(null, new object[] { typeof(Unit) }) as MethodInfo;
		}
		catch
		{
		}

		if (init == null)
		{
			var unitType = typeof(Unit);
			foreach (var method in unitType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
			{
				if (method == null || method.ReturnType != typeof(void))
					continue;
				var ps = method.GetParameters();
				if (ps.Length != 10)
					continue;
				if (ps[0].ParameterType != typeof(int))
					continue;
				if (!string.Equals(ps[3].ParameterType.FullName, "Hex.Session.Battle.Hex", StringComparison.Ordinal))
					continue;
				if (ps[8].ParameterType != typeof(bool) || ps[9].ParameterType != typeof(bool))
					continue;
				var nameOk = string.Equals(method.Name, "Init", StringComparison.Ordinal)
				             || method.Name.IndexOf("Init", StringComparison.Ordinal) >= 0;
				if (!nameOk)
					continue;
				init = method;
				break;
			}
		}

		if (init == null)
		{
			var names = new StringBuilder();
			foreach (var method in typeof(Unit).GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
			{
				if (method.Name.IndexOf("Init", StringComparison.Ordinal) < 0 && method.GetParameters().Length != 10)
					continue;
				if (names.Length > 0)
					names.Append(';');
				names.Append(method.Name).Append('/').Append(method.GetParameters().Length);
			}
			throw new MissingMethodException("Unit.Init not found; candidates=" + names);
		}

		var postfix = AccessTools.Method(typeof(SplitAssemblyMatchKey20260725), nameof(PostfixUnitInit));
		harmony.Patch(init, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
	}

	private static void PrefixBattleLogicInit(object __instance, object __1)
	{
		CapturePlanSides("battleLogicInitPrefix", __instance, __1 as TransferBattle, recordPlans: true);
	}

	private static void PostfixBattleLogicInit(object __instance, object __1)
	{
		// Re-dump sides + registry after Unit.Init nested calls; do not clear plan maps.
		CapturePlanSides("battleLogicInitPostfix", __instance, __1 as TransferBattle, recordPlans: false);
		DumpRegistrySnapshotQuiet();
		WriteSummary();
	}

	private static void CapturePlanSides(string stage, object battleLogic, TransferBattle transferBattle, bool recordPlans)
	{
		try
		{
			var sb = new StringBuilder(1024);
			sb.Append("{\"event\":").Append(Json(stage))
				.Append(",\"battleLogicPtr\":").Append(Json(PtrHex(battleLogic)))
				.Append(",\"sides\":[");

			if (recordPlans)
			{
				lock (Gate)
				{
					PlanSideKeys.Clear();
					PlanByTransferPtr.Clear();
					PlanByLocalSideIndex.Clear();
					PlanByDataSidePtr.Clear();
					_unitEvents = 0;
					_matchTransferPtr = 0;
					_matchLocalSideIndex = 0;
					_matchDataSidePtr = 0;
					_factoryUnits = 0;
				}
			}

			var sides = transferBattle?.sides;
			var first = true;
			if (sides != null)
			{
				for (var i = 0; i < sides.Length; i++)
				{
					var side = sides[i];
					if (side == null)
						continue;
					var transferPtr = PtrHex(side);
					var sideId = TryReadInt(side, TransferSideSideIdMembers);
					var dataSide = TryResolveDataSideViaMod(side);
					var dataSidePtr = PtrHex(dataSide);
					var dataSideIndex = dataSide != null
						? TryReadInt(dataSide, new[] { "index", "get_index", "field_Public_Int32_0", "get_field_Public_Int32_0" })
						: null;
					var unitSids = CollectUnitSids(side);
					var factoryLike = false;
					foreach (var sid in unitSids)
					{
						if (sid != null && sid.StartsWith("h3_", StringComparison.Ordinal))
						{
							factoryLike = true;
							break;
						}
					}
					if (!first)
						sb.Append(',');
					first = false;
					sb.Append('{')
						.Append("\"sideArrayIndex\":").Append(i).Append(',')
						.Append("\"factoryLike\":").Append(factoryLike ? "true" : "false").Append(',')
						.Append("\"transferSidePtr\":").Append(Json(transferPtr)).Append(',')
						.Append("\"sideIdInWorld\":").Append(sideId.HasValue ? sideId.Value.ToString() : "null").Append(',')
						.Append("\"dataSidePtr\":").Append(Json(dataSidePtr)).Append(',')
						.Append("\"dataSideIndex\":").Append(dataSideIndex.HasValue ? dataSideIndex.Value.ToString() : "null").Append(',')
						.Append("\"unitSids\":").Append(JsonArray(unitSids))
						.Append('}');

					if (recordPlans && factoryLike)
					{
						lock (Gate)
						{
							PlanSideKeys.Add(transferPtr ?? "null");
							if (!string.IsNullOrEmpty(transferPtr))
								PlanByTransferPtr[transferPtr] = i;
							// Candidate Death March key: battle-local side index ~= TransferBattle.sides index.
							PlanByLocalSideIndex[i] = i;
							if (dataSideIndex.HasValue)
								PlanByLocalSideIndex[dataSideIndex.Value] = i;
							if (!string.IsNullOrEmpty(dataSidePtr))
								PlanByDataSidePtr[dataSidePtr] = i;
						}
					}
				}
			}
			sb.Append("]}");
			AppendEvent(sb.ToString());
			if (recordPlans)
				WriteSummary();
		}
		catch (Exception ex)
		{
			AppendEvent("{\"event\":" + Json(stage + "-error") + ",\"exception\":" + Json(ex.GetType().Name + ":" + ex.Message) + "}");
		}
	}

	private static void DumpRegistrySnapshotQuiet()
	{
		try
		{
			DumpRegistrySnapshot();
		}
		catch
		{
		}
	}

	private static void PostfixUnitInit(object __instance, object[] __args)
	{
		try
		{
			if (__instance == null || __args == null || __args.Length < 3)
				return;
			var battleSideArg = __args[2];
			if (battleSideArg == null)
				return;

			var unitSid = TryResolveUnitSid(__instance) ?? "?";
			var isFactory = unitSid.StartsWith("h3_", StringComparison.Ordinal);
			var wrapperType = battleSideArg.GetType().FullName ?? "?";
			var wrapperPtr = PtrHex(battleSideArg);
			var localSideIndex = TryReadInt(battleSideArg, WrapperLocalSideIndexMembers);
			object bridgedTransfer = null;
			if (battleSideArg is TransferSide typed)
				bridgedTransfer = typed;
			else
				bridgedTransfer = ReadFirst(battleSideArg, BattleSideTransferSideMembers);
			var bridgedPtr = PtrHex(bridgedTransfer);
			var sideId = bridgedTransfer != null ? TryReadInt(bridgedTransfer, TransferSideSideIdMembers) : null;
			var dataSide = TryResolveDataSideViaMod(battleSideArg) ?? TryResolveDataSideViaMod(bridgedTransfer);
			var dataSidePtr = PtrHex(dataSide);

			var matchTransfer = false;
			var matchLocal = false;
			var matchData = false;
			lock (Gate)
			{
				_unitEvents++;
				if (isFactory)
					_factoryUnits++;
				if (!string.IsNullOrEmpty(bridgedPtr) && PlanByTransferPtr.ContainsKey(bridgedPtr))
				{
					matchTransfer = true;
					_matchTransferPtr++;
				}
				if (localSideIndex.HasValue && PlanByLocalSideIndex.ContainsKey(localSideIndex.Value))
				{
					matchLocal = true;
					_matchLocalSideIndex++;
				}
				if (!string.IsNullOrEmpty(dataSidePtr) && PlanByDataSidePtr.ContainsKey(dataSidePtr))
				{
					matchData = true;
					_matchDataSidePtr++;
				}
			}

			if (!isFactory && _unitEvents > 24)
				return;

			var sb = new StringBuilder(512);
			sb.Append("{\"event\":\"unitInit\"")
				.Append(",\"unitSid\":").Append(Json(unitSid))
				.Append(",\"factoryLike\":").Append(isFactory ? "true" : "false")
				.Append(",\"wrapperType\":").Append(Json(wrapperType))
				.Append(",\"wrapperPtr\":").Append(Json(wrapperPtr))
				.Append(",\"bridgedTransferSidePtr\":").Append(Json(bridgedPtr))
				.Append(",\"localSideIndex\":").Append(localSideIndex.HasValue ? localSideIndex.Value.ToString() : "null")
				.Append(",\"sideIdInWorld\":").Append(sideId.HasValue ? sideId.Value.ToString() : "null")
				.Append(",\"dataSidePtr\":").Append(Json(dataSidePtr))
				.Append(",\"matchTransferSidePtr\":").Append(matchTransfer ? "true" : "false")
				.Append(",\"matchLocalSideIndex\":").Append(matchLocal ? "true" : "false")
				.Append(",\"matchDataSidePtr\":").Append(matchData ? "true" : "false")
				.Append('}');
			AppendEvent(sb.ToString());
			if (isFactory || _unitEvents <= 8)
				WriteSummary();
		}
		catch (Exception ex)
		{
			AppendEvent("{\"event\":\"unitInit-error\",\"exception\":" + Json(ex.GetType().Name + ":" + ex.Message) + "}");
		}
	}

	private static string DumpRegistrySnapshot()
	{
		try
		{
			EnsureBridgeRoot();
			var mod = FindAssembly("OfflineUnlockMod");
			if (mod == null)
				return FailMsg("OfflineUnlockMod not loaded");
			var registryType = mod.GetType("OfflineUnlockMod.Homm3BattleUnitLawOwnerRegistry", false);
			var snapshotMethod = registryType?.GetMethod("SnapshotUnits", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
			if (snapshotMethod == null)
				return FailMsg("SnapshotUnits missing");
			var list = snapshotMethod.Invoke(null, new object[] { 64 }) as IEnumerable;
			if (list == null)
				return FailMsg("SnapshotUnits returned null");

			var sb = new StringBuilder(2048);
			sb.Append("{\"ok\":true,\"event\":\"registrySnapshot\",\"units\":[");
			var first = true;
			var count = 0;
			foreach (var snap in list)
			{
				count++;
				var unit = ReadMember(snap, "Unit");
				var transferSide = ReadMember(snap, "TransferSide");
				var sideIndexKnown = ReadBoolMember(snap, "SideIndexKnown");
				var sideIndex = ReadIntMember(snap, "SideIndex", -1);
				var dataSideKnown = ReadBoolMember(snap, "DataSideKnown");
				var dataSide = ReadMember(snap, "DataSide");
				var bridged = transferSide;
				if (transferSide != null && !(transferSide is TransferSide))
					bridged = ReadFirst(transferSide, BattleSideTransferSideMembers) ?? transferSide;
				var localSideIndex = transferSide != null ? TryReadInt(transferSide, WrapperLocalSideIndexMembers) : null;
				var unitSid = TryResolveUnitSid(unit) ?? "?";
				if (!first)
					sb.Append(',');
				first = false;
				sb.Append('{')
					.Append("\"unitSid\":").Append(Json(unitSid)).Append(',')
					.Append("\"storedSideType\":").Append(Json(transferSide?.GetType().FullName)).Append(',')
					.Append("\"storedSidePtr\":").Append(Json(PtrHex(transferSide))).Append(',')
					.Append("\"bridgedTransferSidePtr\":").Append(Json(PtrHex(bridged))).Append(',')
					.Append("\"localSideIndex\":").Append(localSideIndex.HasValue ? localSideIndex.Value.ToString() : "null").Append(',')
					.Append("\"sideIndexKnown\":").Append(sideIndexKnown ? "true" : "false").Append(',')
					.Append("\"sideIndex\":").Append(sideIndex).Append(',')
					.Append("\"dataSideKnown\":").Append(dataSideKnown ? "true" : "false").Append(',')
					.Append("\"dataSidePtr\":").Append(Json(PtrHex(dataSide)))
					.Append('}');
			}
			sb.Append("],\"count\":").Append(count).Append('}');
			AppendEvent(sb.ToString());
			WriteSummary();
			return sb.ToString();
		}
		catch (Exception ex)
		{
			return Fail("snapshot-failed", ex);
		}
	}

	private static void WriteSummary()
	{
		EnsureBridgeRoot();
		int unitEvents, factoryUnits, matchTransfer, matchLocal, matchData;
		string planKeys;
		lock (Gate)
		{
			unitEvents = _unitEvents;
			factoryUnits = _factoryUnits;
			matchTransfer = _matchTransferPtr;
			matchLocal = _matchLocalSideIndex;
			matchData = _matchDataSidePtr;
			planKeys = string.Join(",", PlanSideKeys);
		}

		string recommended;
		string confidence;
		if (factoryUnits == 0 && unitEvents == 0)
		{
			recommended = "pending_combat";
			confidence = "none";
		}
		else if (matchTransfer > 0 && matchTransfer == factoryUnits)
		{
			recommended = "transferSideNativePtr";
			confidence = "high";
		}
		else if (matchLocal > 0 && matchLocal >= Math.Max(1, factoryUnits / 2) && matchTransfer == 0)
		{
			recommended = "localSideIndex";
			confidence = matchLocal == factoryUnits ? "high" : "medium";
		}
		else if (matchData > 0 && matchData >= Math.Max(1, factoryUnits / 2) && matchTransfer == 0)
		{
			recommended = "dataSidePtr";
			confidence = matchData == factoryUnits ? "high" : "medium";
		}
		else if (matchTransfer == 0 && matchLocal == 0 && matchData == 0 && factoryUnits > 0)
		{
			recommended = "inconclusive_no_key_matched";
			confidence = "low";
		}
		else
		{
			recommended = "mixed_or_partial";
			confidence = "medium";
		}

		var json = new StringBuilder(512);
		json.Append('{')
			.Append("\"ok\":true")
			.Append(",\"planTransferSidePtrs\":").Append(Json(planKeys))
			.Append(",\"unitEvents\":").Append(unitEvents)
			.Append(",\"factoryLikeUnits\":").Append(factoryUnits)
			.Append(",\"matchTransferSidePtr\":").Append(matchTransfer)
			.Append(",\"matchLocalSideIndex\":").Append(matchLocal)
			.Append(",\"matchDataSidePtr\":").Append(matchData)
			.Append(",\"recommendedMatchKey\":").Append(Json(recommended))
			.Append(",\"confidence\":").Append(Json(confidence))
			.Append(",\"note\":").Append(Json("Plan side-index candidate uses TransferBattle.sides array index; wrapper localSideIndex is compared to that. DataSide keys come from OfflineUnlockMod TryResolveDataSideFromBattleTransferSide when available."))
			.Append('}');
		WriteUtf8(SummaryPath(), json.ToString());
	}

	private static object TryResolveDataSideViaMod(object battleSide)
	{
		if (battleSide == null)
			return null;
		try
		{
			var mod = FindAssembly("OfflineUnlockMod");
			var registryType = mod?.GetType("OfflineUnlockMod.Homm3BattleUnitLawOwnerRegistry", false);
			var method = registryType?.GetMethod(
				"TryResolveDataSideFromBattleSide",
				BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
			if (method == null)
				return null;
			var args = new object[] { battleSide, null };
			var ok = method.Invoke(null, args) as bool?;
			return ok == true ? args[1] : null;
		}
		catch
		{
			return null;
		}
	}

	private static List<string> CollectUnitSids(TransferSide side)
	{
		var list = new List<string>();
		if (side?.units == null)
			return list;
		foreach (var unit in side.units)
		{
			if (unit == null)
				continue;
			var sid = unit.configSid;
			if (!string.IsNullOrWhiteSpace(sid))
				list.Add(sid.Trim());
		}
		return list;
	}

	private static string TryResolveUnitSid(object unit)
	{
		if (unit == null)
			return null;
		var direct = ReadFirst(unit, SidMembers) as string;
		if (!string.IsNullOrWhiteSpace(direct))
			return direct.Trim();
		foreach (var name in new[]
		         {
			         "Method_Public_get_UnitLogicConfig_0", "chgu", "bewi", "chfz", "bevj",
			         "Method_Public_get_UnitData_0", "chjr", "beyi"
		         })
		{
			var nested = ReadMember(unit, name);
			var sid = ReadFirst(nested, SidMembers) as string;
			if (!string.IsNullOrWhiteSpace(sid))
				return sid.Trim();
		}
		return null;
	}

	private static Type ResolveType(Assembly assembly, params string[] names)
	{
		foreach (var name in names)
		{
			var type = assembly.GetType(name);
			if (type != null)
				return type;
		}
		return null;
	}

	private static Assembly FindAssembly(string simpleName)
	{
		foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
		{
			if (string.Equals(assembly.GetName().Name, simpleName, StringComparison.Ordinal))
				return assembly;
		}
		return null;
	}

	private static object ReadFirst(object target, string[] names)
	{
		if (target == null || names == null)
			return null;
		foreach (var name in names)
		{
			var value = ReadMember(target, name);
			if (value != null)
				return value;
		}
		return null;
	}

	private static object ReadMember(object target, string name)
	{
		if (target == null || string.IsNullOrWhiteSpace(name))
			return null;
		var type = target.GetType();
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		for (var current = type; current != null && current != typeof(object); current = current.BaseType)
		{
			try
			{
				var property = current.GetProperty(name, flags);
				if (property != null && property.CanRead && property.GetIndexParameters().Length == 0)
					return property.GetValue(target, null);
			}
			catch
			{
			}
			try
			{
				var field = current.GetField(name, flags);
				if (field != null)
					return field.GetValue(target);
			}
			catch
			{
			}
			try
			{
				var method = current.GetMethod(name, flags, null, Type.EmptyTypes, null);
				if (method != null && method.ReturnType != typeof(void))
					return method.Invoke(target, Array.Empty<object>());
			}
			catch
			{
			}
		}
		return null;
	}

	private static int? TryReadInt(object target, string[] names)
	{
		var value = ReadFirst(target, names);
		if (value is int i)
			return i;
		return null;
	}

	private static int ReadIntMember(object target, string name, int fallback)
	{
		var value = ReadMember(target, name);
		return value is int i ? i : fallback;
	}

	private static bool ReadBoolMember(object target, string name)
	{
		var value = ReadMember(target, name);
		return value is bool b && b;
	}

	private static string PtrHex(object target)
	{
		if (target == null)
			return null;
		try
		{
			if (target is Il2CppObjectBase native)
			{
				var ptr = native.Pointer;
				return ptr == IntPtr.Zero ? null : "0x" + ptr.ToInt64().ToString("x");
			}
		}
		catch
		{
		}
		return null;
	}

	private static void EnsureBridgeRoot()
	{
		if (!string.IsNullOrEmpty(_bridgeRoot))
			return;
		_bridgeRoot = Path.GetFullPath(Path.Combine(
			AppDomain.CurrentDomain.BaseDirectory ?? ".",
			"..",
			"..",
			"BepInEx",
			"plugins",
			"OfflineUnlockMod",
			"live_probe_bridge"));
		var fallback = @"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\BepInEx\plugins\OfflineUnlockMod\live_probe_bridge";
		if (!Directory.Exists(_bridgeRoot))
			_bridgeRoot = fallback;
	}

	private static string MarkerPath() => Path.Combine(_bridgeRoot, MarkerRelative);
	private static string LogPath() => Path.Combine(_bridgeRoot, LogRelative);
	private static string SummaryPath() => Path.Combine(_bridgeRoot, SummaryRelative);

	private static void AppendEvent(string jsonLine)
	{
		EnsureBridgeRoot();
		Directory.CreateDirectory(Path.Combine(_bridgeRoot, "artifacts"));
		File.AppendAllText(LogPath(), jsonLine + "\n", Encoding.UTF8);
	}

	private static void WriteUtf8(string path, string text)
	{
		File.WriteAllText(path, text ?? "", Encoding.UTF8);
	}

	private static void TryDelete(string path)
	{
		try
		{
			if (File.Exists(path))
				File.Delete(path);
		}
		catch
		{
		}
	}

	private static string Status(string state)
	{
		WriteSummary();
		var summary = File.Exists(SummaryPath()) ? File.ReadAllText(SummaryPath(), Encoding.UTF8) : "{}";
		return "{\"ok\":true,\"state\":" + Json(state) + ",\"summary\":" + summary + ",\"logPath\":" + Json(LogPath()) + "}";
	}

	private static string Fail(string code, Exception ex)
	{
		return "{\"ok\":false,\"error\":" + Json(code) + ",\"exception\":" + Json(ex.GetType().Name + ":" + ex.Message) + "}";
	}

	private static string FailMsg(string message)
	{
		return "{\"ok\":false,\"error\":" + Json(message) + "}";
	}

	private static string Json(string value)
	{
		if (value == null)
			return "null";
		var sb = new StringBuilder(value.Length + 2);
		sb.Append('"');
		foreach (var ch in value)
		{
			switch (ch)
			{
				case '\\': sb.Append("\\\\"); break;
				case '"': sb.Append("\\\""); break;
				case '\n': sb.Append("\\n"); break;
				case '\r': sb.Append("\\r"); break;
				case '\t': sb.Append("\\t"); break;
				default: sb.Append(ch); break;
			}
		}
		sb.Append('"');
		return sb.ToString();
	}

	private static string JsonArray(List<string> values)
	{
		var sb = new StringBuilder();
		sb.Append('[');
		for (var i = 0; i < values.Count; i++)
		{
			if (i > 0)
				sb.Append(',');
			sb.Append(Json(values[i]));
		}
		sb.Append(']');
		return sb.ToString();
	}
}
