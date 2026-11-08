using System;
using System.Collections.Generic;
using System.IO;
using BepInEx.Logging;
using Newtonsoft.Json.Linq;

namespace OfflineUnlockMod;

internal enum Homm3RuntimeMechanicActivationKind
{
	Unit,
	Law,
}

internal readonly struct Homm3CompiledRuntimeMechanic
{
	internal Homm3CompiledRuntimeMechanic(
		int mechanicIndex,
		string mechanicId,
		Homm3DirectStateAdapterId adapterId,
		Homm3DirectStateOperation operation,
		string trigger,
		Homm3RuntimeMechanicActivationKind activationKind,
		string unitSid,
		string factionSid,
		int lawIndex,
		int value,
		int secondaryValue,
		string stringValue,
		string abilityName)
	{
		MechanicIndex = mechanicIndex;
		MechanicId = mechanicId;
		AdapterId = adapterId;
		Operation = operation;
		Trigger = trigger;
		ActivationKind = activationKind;
		UnitSid = unitSid;
		FactionSid = factionSid;
		LawIndex = lawIndex;
		Value = value;
		SecondaryValue = secondaryValue;
		StringValue = stringValue;
		AbilityName = abilityName;
	}

	internal int MechanicIndex { get; }
	internal string MechanicId { get; }
	internal Homm3DirectStateAdapterId AdapterId { get; }
	internal Homm3DirectStateOperation Operation { get; }
	internal string Trigger { get; }
	internal Homm3RuntimeMechanicActivationKind ActivationKind { get; }
	internal string UnitSid { get; }
	internal string FactionSid { get; }
	internal int LawIndex { get; }
	internal int Value { get; }
	internal int SecondaryValue { get; }
	internal string StringValue { get; }
	internal string AbilityName { get; }
	internal int DamageDelta => Operation == Homm3DirectStateOperation.DamageFlatDelta ? Value : 0;
}

internal readonly struct Homm3RuntimeMechanicBinding
{
	internal Homm3RuntimeMechanicBinding(int unitMechanicIndex, int lawMechanicIndex)
	{
		UnitMechanicIndex = unitMechanicIndex;
		LawMechanicIndex = lawMechanicIndex;
	}

	internal int UnitMechanicIndex { get; }
	internal int LawMechanicIndex { get; }
	internal bool HasAny => UnitMechanicIndex >= 0 || LawMechanicIndex >= 0;
}

/// <summary>
/// Loads the executable runtime-mechanics contract and compiles the selected
/// diagnostic fixture into immutable indexes. Invalid selected input rejects
/// the complete snapshot; no definition is activated independently.
/// </summary>
internal static class Homm3RuntimeMechanicRegistry
{
	internal const string UnitPilotFlag = "homm3_runtime_mechanic_unit_pilot.flag";
	internal const string LawPilotFlag = "homm3_runtime_mechanic_law_pilot.flag";

	private sealed class Snapshot
	{
		internal Snapshot(
			Homm3CompiledRuntimeMechanic[] mechanics,
			Dictionary<string, Homm3RuntimeMechanicBinding> bindings,
			Dictionary<string, int[]> unitMechanics,
			ulong activeAdapterMask)
		{
			Mechanics = mechanics;
			Bindings = bindings;
			UnitMechanics = unitMechanics;
			ActiveAdapterMask = activeAdapterMask;
		}

		internal Homm3CompiledRuntimeMechanic[] Mechanics { get; }
		internal Dictionary<string, Homm3RuntimeMechanicBinding> Bindings { get; }
		internal Dictionary<string, int[]> UnitMechanics { get; }
		internal ulong ActiveAdapterMask { get; }
	}

	private static readonly object Gate = new();
	private static Snapshot _prepared;
	private static Snapshot _active;
	private static string _status = "NOT_PREPARED";

	internal static bool HasPreparedMechanics
	{
		get
		{
			lock (Gate)
				return _prepared != null && _prepared.Mechanics.Length > 0;
		}
	}

	internal static bool HasActiveMechanics
	{
		get
		{
			lock (Gate)
				return _active != null && _active.Mechanics.Length > 0;
		}
	}

	internal static bool IsAdapterPrepared(Homm3DirectStateAdapterId adapterId)
	{
		var bit = AdapterBit(adapterId);
		lock (Gate)
			return bit != 0 && _prepared != null && (_prepared.ActiveAdapterMask & bit) != 0;
	}

	internal static bool IsAdapterActive(Homm3DirectStateAdapterId adapterId)
	{
		var bit = AdapterBit(adapterId);
		lock (Gate)
			return bit != 0 && _active != null && (_active.ActiveAdapterMask & bit) != 0;
	}

	internal static Homm3DirectStateHookSurface GetPreparedHookSurfaces()
	{
		lock (Gate)
			return CollectHookSurfaces(_prepared?.ActiveAdapterMask ?? 0);
	}

	internal static string Status
	{
		get
		{
			lock (Gate)
				return _status;
		}
	}

	internal static bool PrepareFromDirectory(string runtimeMechanicDirectory, ManualLogSource log)
	{
		lock (Gate)
		{
			_prepared = null;
			_active = null;
			_status = "PREPARING";
		}

		try
		{
			var snapshot = BuildSnapshot(runtimeMechanicDirectory);
			lock (Gate)
			{
				_prepared = snapshot;
				_status = snapshot.Mechanics.Length == 0
					? "VALID_NO_SELECTED_MECHANICS"
					: "PREPARED_MECHANICS=" + snapshot.Mechanics.Length;
			}
			log?.LogInfo("HoMM3 runtime-mechanics registry " + Status + ".");
			return snapshot.Mechanics.Length > 0;
		}
		catch (Exception ex)
		{
			lock (Gate)
			{
				_prepared = null;
				_active = null;
				_status = "REJECTED: " + ex.Message;
			}
			log?.LogError("HoMM3 runtime-mechanics registry rejected the complete selected snapshot: " + ex.Message);
			return false;
		}
	}

	internal static bool PublishPreparedSnapshot()
	{
		lock (Gate)
		{
			if (_prepared == null || _prepared.Mechanics.Length == 0)
				return false;
			_active = _prepared;
			_status = "ACTIVE_MECHANICS=" + _active.Mechanics.Length;
			return true;
		}
	}

	internal static void DisablePreparedSnapshot(string reason)
	{
		lock (Gate)
		{
			_active = null;
			_status = "DISABLED: " + (reason ?? "unspecified");
		}
	}

	internal static bool TryGetActiveBinding(string configSid, out Homm3RuntimeMechanicBinding binding)
	{
		binding = default;
		if (string.IsNullOrWhiteSpace(configSid))
			return false;
		lock (Gate)
		{
			return _active != null
			       && _active.Bindings.TryGetValue(configSid.Trim(), out binding)
			       && binding.HasAny;
		}
	}

	internal static bool TryGetActiveMechanic(int mechanicIndex, out Homm3CompiledRuntimeMechanic mechanic)
	{
		lock (Gate)
		{
			if (_active == null || mechanicIndex < 0 || mechanicIndex >= _active.Mechanics.Length)
			{
				mechanic = default;
				return false;
			}
			mechanic = _active.Mechanics[mechanicIndex];
			return true;
		}
	}

	internal static bool TryGetActiveMechanicsForUnitSid(string unitSid, out int[] mechanicIndexes)
	{
		mechanicIndexes = null;
		if (string.IsNullOrWhiteSpace(unitSid))
			return false;
		lock (Gate)
		{
			return _active != null
			       && _active.UnitMechanics.TryGetValue(unitSid.Trim(), out mechanicIndexes)
			       && mechanicIndexes != null
			       && mechanicIndexes.Length > 0;
		}
	}

	internal static string DescribeActiveMechanic(int mechanicIndex)
	{
		return TryGetActiveMechanic(mechanicIndex, out var mechanic)
			? mechanic.MechanicId
			: "unknown:" + mechanicIndex.ToString(System.Globalization.CultureInfo.InvariantCulture);
	}

	private static Snapshot BuildSnapshot(string runtimeMechanicDirectory)
	{
		if (string.IsNullOrWhiteSpace(runtimeMechanicDirectory))
			throw new InvalidOperationException("runtime-mechanics directory was not provided");

		var fullDirectory = Path.GetFullPath(runtimeMechanicDirectory);
		if (!Directory.Exists(fullDirectory))
			throw new InvalidOperationException("runtime-mechanics directory is missing: " + fullDirectory);

		var paths = Directory.GetFiles(fullDirectory, "homm3_*.json", SearchOption.TopDirectoryOnly);
		Array.Sort(paths, StringComparer.OrdinalIgnoreCase);
		if (paths.Length == 0)
			throw new InvalidOperationException("runtime-mechanics directory has no homm3_*.json contracts: " + fullDirectory);

		var selected = new List<PendingDefinition>();
		var mechanicIds = new HashSet<string>(StringComparer.Ordinal);
		var manifestValidated = false;
		foreach (var path in paths)
		{
			var root = ParseRoot(path);
			if (RequiredInt(root, "schemaVersion", path) != 2)
				throw new InvalidOperationException(path + ": schemaVersion must be 2");
			if (string.Equals(OptionalString(root, "kind"), "adapterManifest", StringComparison.Ordinal))
			{
				ValidateAdapterManifest(path, root);
				manifestValidated = true;
				continue;
			}
			if (!RequiredBool(root, "enabled", path))
				continue;
			var definitions = RequiredArray(root, "definitions", path);

			for (var i = 0; i < definitions.Count; i++)
			{
				var definition = RequiredObject(
					definitions[i],
					path + ": definitions[" + i + "]");
				if (!RequiredBool(definition, "enabled", path))
					continue;
				var pending = ParseDefinition(path, i, definition);
				if (!mechanicIds.Add(pending.MechanicId))
					throw new InvalidOperationException(path + ": duplicate mechanicId '" + pending.MechanicId + "'");
				if (Homm3DiagnosticFlags.IsEnabled(pending.DiagnosticFlag))
					selected.Add(pending);
			}
		}

		if (!manifestValidated)
			throw new InvalidOperationException("runtime-mechanics adapter manifest is missing");
		if (selected.Count > 16)
			throw new InvalidOperationException("selected runtime-mechanics fixture count exceeds hard cap 16");

		var mechanics = new Homm3CompiledRuntimeMechanic[selected.Count];
		ulong activeAdapterMask = 0;
		for (var i = 0; i < selected.Count; i++)
		{
			var item = selected[i];
			mechanics[i] = new Homm3CompiledRuntimeMechanic(
				i,
				item.MechanicId,
				item.AdapterId,
				item.Operation,
				item.Trigger,
				item.ActivationKind,
				item.UnitSid,
				item.FactionSid,
				item.LawIndex,
				item.Value,
				item.SecondaryValue,
				item.StringValue,
				item.AbilityName);
			activeAdapterMask |= AdapterBit(item.AdapterId);
		}

		var bindings = BuildBindings(mechanics);
		var unitMechanics = BuildUnitMechanics(mechanics);
		return new Snapshot(mechanics, bindings, unitMechanics, activeAdapterMask);
	}

	private static Dictionary<string, int[]> BuildUnitMechanics(Homm3CompiledRuntimeMechanic[] mechanics)
	{
		var pending = new Dictionary<string, List<int>>(StringComparer.OrdinalIgnoreCase);
		for (var i = 0; i < mechanics.Length; i++)
		{
			var mechanic = mechanics[i];
			if (mechanic.ActivationKind != Homm3RuntimeMechanicActivationKind.Unit
			    || string.IsNullOrWhiteSpace(mechanic.UnitSid))
				continue;
			if (!pending.TryGetValue(mechanic.UnitSid, out var indexes))
			{
				indexes = new List<int>();
				pending[mechanic.UnitSid] = indexes;
			}
			indexes.Add(mechanic.MechanicIndex);
		}
		var result = new Dictionary<string, int[]>(StringComparer.OrdinalIgnoreCase);
		foreach (var pair in pending)
			result[pair.Key] = pair.Value.ToArray();
		return result;
	}

	private static Dictionary<string, Homm3RuntimeMechanicBinding> BuildBindings(
		Homm3CompiledRuntimeMechanic[] mechanics)
	{
		var bindings = new Dictionary<string, Homm3RuntimeMechanicBinding>(StringComparer.OrdinalIgnoreCase);
		for (var i = 0; i < mechanics.Length; i++)
		{
			var mechanic = mechanics[i];
			if (mechanic.AdapterId != Homm3DirectStateAdapterId.Damage)
				continue;
			if (mechanic.ActivationKind == Homm3RuntimeMechanicActivationKind.Unit)
			{
				MergeBinding(bindings, mechanic.UnitSid, mechanic.MechanicIndex, -1);
				continue;
			}

			foreach (var unitSid in Homm3CustomFactionRegistry.EnumerateCustomUnitSids())
			{
				if (!Homm3CustomFactionRegistry.TryGetFactionSidForCustomUnitSid(unitSid, out var factionSid)
				    || !string.Equals(factionSid, mechanic.FactionSid, StringComparison.Ordinal))
					continue;
				MergeBinding(bindings, unitSid, -1, mechanic.MechanicIndex);
			}
		}
		return bindings;
	}

	private static void MergeBinding(
		Dictionary<string, Homm3RuntimeMechanicBinding> bindings,
		string unitSid,
		int unitMechanicIndex,
		int lawMechanicIndex)
	{
		if (!bindings.TryGetValue(unitSid, out var existing))
			existing = new Homm3RuntimeMechanicBinding(-1, -1);
		bindings[unitSid] = new Homm3RuntimeMechanicBinding(
			unitMechanicIndex >= 0 ? unitMechanicIndex : existing.UnitMechanicIndex,
			lawMechanicIndex >= 0 ? lawMechanicIndex : existing.LawMechanicIndex);
	}

	private static PendingDefinition ParseDefinition(string path, int index, JObject definition)
	{
		var context = path + ": definitions[" + index + "]";
		var mechanicId = RequiredString(definition, "mechanicId", context);
		if (!mechanicId.StartsWith("diagnostic.", StringComparison.Ordinal))
			throw new InvalidOperationException(context + ": pilot mechanicId must start with diagnostic.");
		foreach (var forbiddenKey in new[] { "effectPayload", "effectKey", "donor", "spellSid" })
		{
			if (definition[forbiddenKey] != null)
				throw new InvalidOperationException(context + ": unsupported native/donor payload key '" + forbiddenKey + "'");
		}
		var adapterContractId = RequiredString(definition, "adapterId", context);
		if (!Homm3DirectStateAdapterManifest.TryGet(adapterContractId, out var adapterRecord))
			throw new InvalidOperationException(context + ": unknown adapterId '" + adapterContractId + "'");
		var diagnosticFlag = RequiredString(definition, "diagnosticFlag", context);
		if (!string.Equals(diagnosticFlag, adapterRecord.FixtureFlag, StringComparison.Ordinal)
		    && !string.Equals(
			    diagnosticFlag,
			    Homm3RuntimeMechanicFixtureHarness.AggregateStressFlag,
			    StringComparison.Ordinal)
		    && !(adapterRecord.AdapterId == Homm3DirectStateAdapterId.Damage
		         && (string.Equals(diagnosticFlag, UnitPilotFlag, StringComparison.Ordinal)
		             || string.Equals(diagnosticFlag, LawPilotFlag, StringComparison.Ordinal))))
			throw new InvalidOperationException(context + ": unsupported diagnosticFlag '" + diagnosticFlag + "'");
		var trigger = RequiredString(definition, "trigger", context);
		if (!IsAllowedTrigger(adapterRecord.AdapterId, trigger))
			throw new InvalidOperationException(
				context + ": trigger '" + trigger + "' is not allow-listed for adapter " + adapterRecord.ContractId);

		var operationObject = RequiredObject(definition, "operation", context);
		var operationName = RequiredString(operationObject, "kind", context);
		if (!TryParseOperation(operationName, out var operation)
		    || !Contains(adapterRecord.Operations, operation))
			throw new InvalidOperationException(context + ": operation '" + operationName + "' is not wired for adapter " + adapterRecord.ContractId);
		var value = OptionalInt(operationObject, "value", 0, context);
		var secondaryValue = OptionalInt(operationObject, "secondaryValue", 0, context);
		var stringValue = OptionalString(operationObject, "stringValue");
		var abilityName = OptionalString(operationObject, "abilityName");
		if (string.Equals(trigger, "castCommitted", StringComparison.Ordinal)
		    && string.IsNullOrWhiteSpace(abilityName))
			throw new InvalidOperationException(
				context + ": castCommitted mechanics require operation.abilityName (use \"*\" only for explicit any-cast diagnostics)");
		if (operation == Homm3DirectStateOperation.DamageFlatDelta && value == 0)
			throw new InvalidOperationException(context + ": damage flat delta value cannot be zero");

		var activation = RequiredObject(definition, "activation", context);
		var activationKind = RequiredString(activation, "kind", context);
		if (string.Equals(activationKind, "unit", StringComparison.Ordinal))
		{
			var unitSid = RequiredString(activation, "unitSid", context);
			if (!Homm3CustomFactionRegistry.IsCustomUnitSid(unitSid))
				throw new InvalidOperationException(context + ": activation.unitSid is not a registered custom unit: " + unitSid);
			return new PendingDefinition(
				mechanicId,
				diagnosticFlag,
				adapterRecord.AdapterId,
				operation,
				trigger,
				Homm3RuntimeMechanicActivationKind.Unit,
				unitSid,
				null,
				0,
				value,
				secondaryValue,
				stringValue,
				abilityName);
		}

		if (string.Equals(activationKind, "law", StringComparison.Ordinal))
		{
			var factionSid = RequiredString(activation, "factionSid", context);
			var lawIndex = RequiredInt(activation, "lawIndex", context);
			if (!string.Equals(factionSid, "homm3_castle", StringComparison.Ordinal) || lawIndex != 6)
				throw new InvalidOperationException(context + ": the only supported law fixture is homm3_castle law index 6");
			if (adapterRecord.AdapterId != Homm3DirectStateAdapterId.Damage)
				throw new InvalidOperationException(context + ": law activation is currently restricted to the damage ownership fixture");
			return new PendingDefinition(
				mechanicId,
				diagnosticFlag,
				adapterRecord.AdapterId,
				operation,
				trigger,
				Homm3RuntimeMechanicActivationKind.Law,
				null,
				factionSid,
				lawIndex,
				value,
				secondaryValue,
				stringValue,
				abilityName);
		}

		throw new InvalidOperationException(context + ": activation.kind must be unit or law");
	}

	private static void ValidateAdapterManifest(string path, JObject root)
	{
		if (!Homm3DirectStateAdapterManifest.ValidateExhaustive(out var codeFailure))
			throw new InvalidOperationException(path + ": code manifest is incomplete: " + codeFailure);
		var adapters = RequiredArray(root, "adapters", path);
		if (adapters.Count != Homm3DirectStateAdapterManifest.Count)
			throw new InvalidOperationException(
				path + ": adapter row count must be " + Homm3DirectStateAdapterManifest.Count);
		var seen = new HashSet<int>();
		for (var i = 0; i < adapters.Count; i++)
		{
			var context = path + ": adapters[" + i + "]";
			var row = RequiredObject(adapters[i], context);
			var stableId = RequiredInt(row, "stableId", context);
			if (!seen.Add(stableId))
				throw new InvalidOperationException(context + ": duplicate stableId " + stableId);
			var adapterId = (Homm3DirectStateAdapterId)stableId;
			if (!Homm3DirectStateAdapterManifest.TryGet(adapterId, out var codeRecord))
				throw new InvalidOperationException(context + ": stableId has no code record");
			if (!string.Equals(RequiredString(row, "adapterId", context), codeRecord.ContractId, StringComparison.Ordinal)
			    || !string.Equals(RequiredString(row, "family", context), codeRecord.FamilyKey, StringComparison.Ordinal)
			    || !string.Equals(RequiredString(row, "fixtureFlag", context), codeRecord.FixtureFlag, StringComparison.Ordinal)
			    || !string.Equals(RequiredString(row, "proofLabel", context), codeRecord.ProofLabel, StringComparison.Ordinal)
			    || !string.Equals(
				    RequiredString(row, "reconciliationPolicy", context),
				    codeRecord.ReconciliationPolicy,
				    StringComparison.Ordinal))
				throw new InvalidOperationException(context + ": JSON row does not match stable code manifest");
			var operations = RequiredArray(row, "operations", context);
			if (operations.Count != codeRecord.Operations.Length)
				throw new InvalidOperationException(context + ": operations must exhaustively match code wiring");
			for (var operationIndex = 0; operationIndex < operations.Count; operationIndex++)
			{
				var operationName = operations[operationIndex]?.Type == JTokenType.String
					? (string)operations[operationIndex]
					: null;
				if (!TryParseOperation(operationName, out var parsed)
				    || !Contains(codeRecord.Operations, parsed))
					throw new InvalidOperationException(context + ": operation is not wired: " + (operationName ?? "null"));
			}
			var caps = RequiredObject(row, "caps", context);
			if (RequiredInt(caps, "maxRootWork", context) != codeRecord.Caps.MaxRootWork
			    || RequiredInt(caps, "maxDepth", context) != codeRecord.Caps.MaxDepth
			    || RequiredInt(caps, "maxJournalEntries", context) != codeRecord.Caps.MaxJournalEntries
			    || RequiredInt(caps, "maxFanout", context) != codeRecord.Caps.MaxFanout
			    || RequiredInt(caps, "maxDirtyIdentities", context) != codeRecord.Caps.MaxDirtyIdentities
			    || RequiredInt(caps, "maxQueueSpan", context) != codeRecord.Caps.MaxQueueSpan)
				throw new InvalidOperationException(context + ": caps do not match code manifest");
		}
	}

	private static bool TryParseOperation(string value, out Homm3DirectStateOperation operation)
	{
		operation = Homm3DirectStateOperation.None;
		return !string.IsNullOrWhiteSpace(value)
		       && Enum.TryParse(value.Trim(), ignoreCase: false, out operation)
		       && operation != Homm3DirectStateOperation.None;
	}

	private static bool IsAllowedTrigger(Homm3DirectStateAdapterId adapterId, string trigger)
	{
		return adapterId switch
		{
			Homm3DirectStateAdapterId.Damage => trigger == "damageApplying",
			Homm3DirectStateAdapterId.Cast => trigger == "castCommitted",
			Homm3DirectStateAdapterId.Focus => trigger == "castCommitted",
			Homm3DirectStateAdapterId.Cooldown => trigger == "castCommitted",
			Homm3DirectStateAdapterId.Status => trigger == "castCommitted" || trigger == "roundStart" || trigger == "roundEnd",
			Homm3DirectStateAdapterId.Movement => trigger == "damageApplied" || trigger == "movementCommitted",
			Homm3DirectStateAdapterId.Summon => trigger == "castCommitted",
			Homm3DirectStateAdapterId.Trap => trigger == "castCommitted" || trigger == "movementCommitted" || trigger == "roundEnd",
			Homm3DirectStateAdapterId.Corpse => trigger == "objectDestroyed",
			Homm3DirectStateAdapterId.NestedDamage => trigger == "damageApplying" || trigger == "damageApplied",
			Homm3DirectStateAdapterId.Kill => trigger == "objectDestroyed",
			Homm3DirectStateAdapterId.AllyDeath => trigger == "objectDestroyed",
			Homm3DirectStateAdapterId.ActionQueue => trigger == "actionEnd",
			Homm3DirectStateAdapterId.TurnOrder => trigger == "roundStart",
			Homm3DirectStateAdapterId.Aura => trigger == "unitInit"
			                                        || trigger == "movementCommitted"
			                                        || trigger == "objectDestroyed"
			                                        || trigger == "roundStart",
			_ => false,
		};
	}


	/// <summary>
	/// Cast-ability gate for castCommitted mechanics.
	/// Explicit "*" means any cast (diagnostic only). Empty expected names never match.
	/// </summary>
	internal static bool MatchesCastAbility(string expectedAbilityName, string observedAbilityName)
	{
		if (string.IsNullOrWhiteSpace(expectedAbilityName))
			return false;
		if (string.Equals(expectedAbilityName.Trim(), "*", StringComparison.Ordinal))
			return true;
		return Homm3BattleEventNativeAdapter.IsAbilityNameMatch(expectedAbilityName, observedAbilityName);
	}

	private static bool Contains(Homm3DirectStateOperation[] operations, Homm3DirectStateOperation operation)
	{
		for (var i = 0; i < operations.Length; i++)
		{
			if (operations[i] == operation)
				return true;
		}
		return false;
	}

	private static ulong AdapterBit(Homm3DirectStateAdapterId adapterId)
	{
		var value = (int)adapterId;
		return value <= 0 || value >= 64 ? 0UL : 1UL << value;
	}

	private static Homm3DirectStateHookSurface CollectHookSurfaces(ulong adapterMask)
	{
		var result = Homm3DirectStateHookSurface.None;
		for (var value = 1; value <= Homm3DirectStateAdapterManifest.Count; value++)
		{
			var adapterId = (Homm3DirectStateAdapterId)value;
			if ((adapterMask & AdapterBit(adapterId)) == 0
			    || !Homm3DirectStateAdapterManifest.TryGet(adapterId, out var record))
				continue;
			result |= record.HookSurfaces;
		}
		return result;
	}

	private static JObject ParseRoot(string path)
	{
		try
		{
			return JObject.Parse(File.ReadAllText(path));
		}
		catch (Exception ex)
		{
			throw new InvalidOperationException(path + ": parse failed: " + ex.Message, ex);
		}
	}

	private static JArray RequiredArray(JObject owner, string name, string context)
	{
		var token = owner[name];
		if (token == null || token.Type != JTokenType.Array)
			throw new InvalidOperationException(context + ": " + name + " must be an array");
		try
		{
			// IL2CPP Newtonsoft JToken proxies do not reliably cast to JArray.
			return JArray.Parse(token.ToString());
		}
		catch (Exception ex)
		{
			throw new InvalidOperationException(context + ": " + name + " array parse failed: " + ex.Message, ex);
		}
	}

	private static JObject RequiredObject(JObject owner, string name, string context)
	{
		return RequiredObject(owner[name], context + ": " + name);
	}

	private static JObject RequiredObject(JToken token, string context)
	{
		if (token == null || token.Type != JTokenType.Object)
			throw new InvalidOperationException(context + " must be an object");
		try
		{
			// IL2CPP Newtonsoft JToken proxies do not reliably cast to JObject.
			return JObject.Parse(token.ToString());
		}
		catch (Exception ex)
		{
			throw new InvalidOperationException(context + " object parse failed: " + ex.Message, ex);
		}
	}

	private static string RequiredString(JObject owner, string name, string context)
	{
		var value = owner[name]?.Type == JTokenType.String ? (string)owner[name] : null;
		if (string.IsNullOrWhiteSpace(value))
			throw new InvalidOperationException(context + ": " + name + " must be a non-empty string");
		return value.Trim();
	}

	private static int RequiredInt(JObject owner, string name, string context)
	{
		if (owner[name]?.Type != JTokenType.Integer)
			throw new InvalidOperationException(context + ": " + name + " must be an integer");
		return (int)owner[name];
	}

	private static int OptionalInt(JObject owner, string name, int defaultValue, string context)
	{
		if (owner[name] == null)
			return defaultValue;
		if (owner[name]?.Type != JTokenType.Integer)
			throw new InvalidOperationException(context + ": " + name + " must be an integer");
		return (int)owner[name];
	}

	private static string OptionalString(JObject owner, string name)
	{
		return owner[name]?.Type == JTokenType.String
			? ((string)owner[name])?.Trim()
			: null;
	}

	private static bool RequiredBool(JObject owner, string name, string context)
	{
		if (owner[name]?.Type != JTokenType.Boolean)
			throw new InvalidOperationException(context + ": " + name + " must be a Boolean");
		return (bool)owner[name];
	}

	private readonly struct PendingDefinition
	{
		internal PendingDefinition(
			string mechanicId,
			string diagnosticFlag,
			Homm3DirectStateAdapterId adapterId,
			Homm3DirectStateOperation operation,
			string trigger,
			Homm3RuntimeMechanicActivationKind activationKind,
			string unitSid,
			string factionSid,
			int lawIndex,
			int value,
			int secondaryValue,
			string stringValue,
			string abilityName)
		{
			MechanicId = mechanicId;
			DiagnosticFlag = diagnosticFlag;
			AdapterId = adapterId;
			Operation = operation;
			Trigger = trigger;
			ActivationKind = activationKind;
			UnitSid = unitSid;
			FactionSid = factionSid;
			LawIndex = lawIndex;
			Value = value;
			SecondaryValue = secondaryValue;
			StringValue = stringValue;
			AbilityName = abilityName;
		}

		internal string MechanicId { get; }
		internal string DiagnosticFlag { get; }
		internal Homm3DirectStateAdapterId AdapterId { get; }
		internal Homm3DirectStateOperation Operation { get; }
		internal string Trigger { get; }
		internal Homm3RuntimeMechanicActivationKind ActivationKind { get; }
		internal string UnitSid { get; }
		internal string FactionSid { get; }
		internal int LawIndex { get; }
		internal int Value { get; }
		internal int SecondaryValue { get; }
		internal string StringValue { get; }
		internal string AbilityName { get; }
	}
}
