using System;
using System.Collections.Generic;
using System.Reflection;
using HarmonyLib;
using Hex.Configs;

namespace OfflineUnlockMod;

/// <summary>
/// Exact native adapter for battle event payload surfaces.
/// Source-prepared from June 18 decomp evidence. This class does not register
/// Harmony patches, dispatch events, mutate damage, or alter turn/action state.
/// It only centralizes exact payload reads for future committed-damage and
/// battle-action handlers after packet proof is promoted.
/// </summary>
internal static partial class Homm3BattleEventNativeAdapter
{
	internal readonly struct DamageEventInfo
	{
		internal readonly object Caster;
		internal readonly object Receiver;
		internal readonly object CastSource;
		internal readonly object Dealer;
		internal readonly int Damage;
		internal readonly int StacksDestroyed;
		internal readonly bool ImmuneToDamage;
		internal readonly bool Cumulative;
		internal readonly object FromMech;

		internal DamageEventInfo(
			object caster,
			object receiver,
			object castSource,
			object dealer,
			int damage,
			int stacksDestroyed,
			bool immuneToDamage,
			bool cumulative,
			object fromMech)
		{
			Caster = caster;
			Receiver = receiver;
			CastSource = castSource;
			Dealer = dealer;
			Damage = damage;
			StacksDestroyed = stacksDestroyed;
			ImmuneToDamage = immuneToDamage;
			Cumulative = cumulative;
			FromMech = fromMech;
		}

		public override string ToString()
		{
			return "damage=" + Damage
			       + " stacksDestroyed=" + StacksDestroyed
			       + " immune=" + ImmuneToDamage
			       + " cumulative=" + Cumulative
			       + " fromMech=" + FormatShortValue(FromMech)
			       + " caster=" + DescribeObject(Caster)
			       + " receiver=" + DescribeObject(Receiver)
			       + " source=" + DescribeObject(CastSource)
			       + " dealer=" + DescribeObject(Dealer);
		}
	}

	internal readonly struct DestroyedEventInfo
	{
		internal readonly object DestroyedObject;
		internal readonly bool IsTimeout;
		internal readonly object Caster;
		internal readonly object CastSource;

		internal DestroyedEventInfo(object destroyedObject, bool isTimeout, object caster, object castSource)
		{
			DestroyedObject = destroyedObject;
			IsTimeout = isTimeout;
			Caster = caster;
			CastSource = castSource;
		}

		public override string ToString()
		{
			return "destroyed=" + DescribeObject(DestroyedObject)
			       + " isTimeout=" + IsTimeout
			       + " caster=" + DescribeObject(Caster)
			       + " source=" + DescribeObject(CastSource);
		}
	}

	internal readonly struct SpawnedEventInfo
	{
		internal readonly object SpawnedObject;
		internal readonly object Caster;
		internal readonly object CastSource;

		internal SpawnedEventInfo(object spawnedObject, object caster, object castSource)
		{
			SpawnedObject = spawnedObject;
			Caster = caster;
			CastSource = castSource;
		}
	}

	internal readonly struct RoundEventInfo
	{
		internal readonly bool Started;
		internal readonly int RoundNumber;
		internal readonly object Target;

		internal RoundEventInfo(bool started, int roundNumber, object target)
		{
			Started = started;
			RoundNumber = roundNumber;
			Target = target;
		}
	}

	internal readonly struct ActionEventInfo
	{
		internal readonly bool Started;
		internal readonly int RoundNumber;
		internal readonly object Target;

		internal ActionEventInfo(bool started, int roundNumber, object target)
		{
			Started = started;
			RoundNumber = roundNumber;
			Target = target;
		}
	}

	internal readonly struct MovementEventInfo
	{
		internal readonly object TargetHex;
		internal readonly object Path;
		internal readonly int PathLength;

		internal MovementEventInfo(object targetHex, object path, int pathLength)
		{
			TargetHex = targetHex;
			Path = path;
			PathLength = pathLength;
		}

		public override string ToString()
		{
			return "targetHex=" + DescribeObject(TargetHex)
			       + " pathLength=" + PathLength
			       + " path=" + DescribeObject(Path);
		}
	}

	internal readonly struct CastAbilityEventInfo
	{
		internal readonly object Caster;
		internal readonly object AbilityId;
		internal readonly object AbilityType;
		internal readonly object AbilityIndex;
		internal readonly string AbilityName;
		internal readonly object AttackedObjects;
		internal readonly object AttackedHexes;
		internal readonly object ImmuneObjects;
		internal readonly int RoundNumber;

		internal CastAbilityEventInfo(
			object caster,
			object abilityId,
			object abilityType,
			object abilityIndex,
			string abilityName,
			object attackedObjects,
			object attackedHexes,
			object immuneObjects,
			int roundNumber)
		{
			Caster = caster;
			AbilityId = abilityId;
			AbilityType = abilityType;
			AbilityIndex = abilityIndex;
			AbilityName = abilityName;
			AttackedObjects = attackedObjects;
			AttackedHexes = attackedHexes;
			ImmuneObjects = immuneObjects;
			RoundNumber = roundNumber;
		}

		internal int AttackedObjectCount => CountEnumerable(AttackedObjects);

		internal int AttackedHexCount => CountEnumerable(AttackedHexes);

		internal int ImmuneObjectCount => CountEnumerable(ImmuneObjects);

		internal bool HasAbilityName(string expectedAbilityName)
		{
			return !string.IsNullOrWhiteSpace(expectedAbilityName)
			       && string.Equals(AbilityName, expectedAbilityName, StringComparison.Ordinal);
		}

		public override string ToString()
		{
			return "caster=" + DescribeObject(Caster)
			       + " abilityName=" + (AbilityName ?? "null")
			       + " abilityType=" + FormatShortValue(AbilityType)
			       + " abilityIndex=" + FormatShortValue(AbilityIndex)
			       + " round=" + RoundNumber
			       + " attackedObjects=" + DescribeCollection(AttackedObjects)
			       + " attackedHexes=" + DescribeCollection(AttackedHexes)
			       + " immuneObjects=" + DescribeCollection(ImmuneObjects);
		}
	}

	internal readonly struct ChangeAbilityEventInfo
	{
		internal readonly object Target;
		internal readonly EAbilityType AbilityType;
		internal readonly int AbilityIndex;

		internal ChangeAbilityEventInfo(object target, EAbilityType abilityType, int abilityIndex)
		{
			Target = target;
			AbilityType = abilityType;
			AbilityIndex = abilityIndex;
		}

		public override string ToString()
		{
			return "target=" + DescribeObject(Target)
			       + " abilityType=" + AbilityType
			       + " abilityIndex=" + AbilityIndex;
		}
	}

	private static Type _unitPosChangedEventArgsType;
	private static Type _unitStartedMovementEventArgsType;
	private static Type _objectTookDamageEventArgsType;
	private static Type _objectDestroyedEventArgsType;
	private static Type _objectSpawnedEventArgsType;
	private static Type _castAbilityEventArgsType;
	private static bool _resolved;
	private static string _resolveFailure;

	internal static bool TryReadDamageEvent(object eventArgs, out DamageEventInfo info, out string failReason)
	{
		info = default;
		if (!TryResolve(out failReason))
			return false;
		if (!ValidateEvent(eventArgs, _objectTookDamageEventArgsType, "ObjectTookDamageEventArgs", out failReason))
			return false;

		var type = eventArgs.GetType();
		TryReadExactMember(eventArgs, type, GameSymbols.BattleEventLaws.ObjectTookDamageCasterMembers, out var caster);
		TryReadExactMember(eventArgs, type, GameSymbols.BattleEventLaws.ObjectTookDamageReceiverMembers, out var receiver);
		TryReadExactMember(eventArgs, type, GameSymbols.BattleEventLaws.ObjectTookDamageCastSourceMembers, out var castSource);
		TryReadExactMember(eventArgs, type, GameSymbols.BattleEventLaws.ObjectTookDamageDealerMembers, out var dealer);
		TryReadIntMember(eventArgs, type, new[] { "damage" }, out var damage);
		TryReadIntMember(eventArgs, type, new[] { "stacksDestroyed" }, out var stacksDestroyed);
		TryReadBoolMember(eventArgs, type, new[] { "immuneToDamage" }, out var immuneToDamage);
		TryReadBoolMember(eventArgs, type, new[] { "cumulative" }, out var cumulative);
		TryReadExactMember(eventArgs, type, new[] { "fromMech" }, out var fromMech);

		info = new DamageEventInfo(caster, receiver, castSource, dealer, damage, stacksDestroyed, immuneToDamage, cumulative, fromMech);
		failReason = null;
		return true;
	}

	internal static bool TryReadDamageApplyInvocation(object receiverUnit, object[] args, out DamageEventInfo info, out string failReason)
	{
		info = default;
		if (receiverUnit == null)
		{
			failReason = "damage-apply receiver Unit instance is null";
			return false;
		}
		if (args == null || args.Length != 8)
		{
			failReason = "damage-apply invocation requires exact 8-argument Unit damage method shape";
			return false;
		}
		if (args[3] is not int damage)
		{
			failReason = "damage-apply invocation argument 3 is not Int32 damage";
			return false;
		}
		if (args[5] is not bool immuneToDamage)
		{
			failReason = "damage-apply invocation argument 5 is not Boolean immune flag";
			return false;
		}
		if (args[7] is not bool cumulative)
		{
			failReason = "damage-apply invocation argument 7 is not Boolean cumulative flag";
			return false;
		}

		info = new DamageEventInfo(
			args[0],
			receiverUnit,
			args[1],
			args[2],
			damage,
			0,
			immuneToDamage,
			cumulative,
			args[4]);
		failReason = null;
		return true;
	}
	internal static bool TryReadDestroyedEvent(object eventArgs, out DestroyedEventInfo info, out string failReason)
	{
		info = default;
		if (!TryResolve(out failReason))
			return false;
		if (!ValidateEvent(eventArgs, _objectDestroyedEventArgsType, "ObjectDestroyedEventArgs", out failReason))
			return false;

		var type = eventArgs.GetType();
		TryReadExactMember(eventArgs, type, new[] { "destroyedObject" }, out var destroyedObject);
		TryReadBoolMember(eventArgs, type, new[] { "isTimeout" }, out var isTimeout);
		TryReadExactMember(eventArgs, type, new[] { "caster" }, out var caster);
		TryReadExactMember(eventArgs, type, new[] { "castSource" }, out var castSource);

		info = new DestroyedEventInfo(destroyedObject, isTimeout, caster, castSource);
		failReason = null;
		return true;
	}

	internal static bool TryReadSpawnedEvent(object eventArgs, out SpawnedEventInfo info, out string failReason)
	{
		info = default;
		if (!TryResolve(out failReason))
			return false;
		if (!ValidateEvent(eventArgs, _objectSpawnedEventArgsType, "ObjectSpawnedEventArgs", out failReason))
			return false;
		var type = eventArgs.GetType();
		TryReadExactMember(eventArgs, type, GameSymbols.BattleEventLaws.ObjectSpawnedObjectMembers, out var spawnedObject);
		TryReadExactMember(eventArgs, type, GameSymbols.BattleEventLaws.ObjectSpawnedCasterMembers, out var caster);
		TryReadExactMember(eventArgs, type, GameSymbols.BattleEventLaws.ObjectSpawnedCastSourceMembers, out var castSource);
		info = new SpawnedEventInfo(spawnedObject, caster, castSource);
		failReason = null;
		return true;
	}

	internal static bool TryReadRoundEvent(object eventArgs, out RoundEventInfo info, out string failReason)
	{
		info = default;
		if (!TryResolve(out failReason))
			return false;
		if (eventArgs == null)
		{
			failReason = "round event args are null";
			return false;
		}
		// Fail closed: the live interop has no typed round start/end EventArgs subclass, so a
		// type-only read cannot tell started from ended. Use the dispatcher overload.
		failReason = "typed round event read unavailable: " + GameSymbols.BattleEventLaws.RoundActionEventArgsTypesAbsentLive;
		return false;
	}

	internal static bool TryReadRoundEvent(
		object eventArgs,
		bool started,
		out RoundEventInfo info,
		out string failReason)
	{
		info = default;
		if (eventArgs == null)
		{
			failReason = "round dispatcher event args are null";
			return false;
		}
		var type = eventArgs.GetType();
		TryReadIntMember(eventArgs, type, GameSymbols.BattleEventLaws.BattleEventRoundMembers, out var round);
		TryReadExactMember(eventArgs, type, GameSymbols.BattleEventLaws.BattleEventTargetMembers, out var target);
		info = new RoundEventInfo(started, round, target);
		failReason = null;
		return true;
	}

	internal static bool TryReadActionEvent(object eventArgs, out ActionEventInfo info, out string failReason)
	{
		info = default;
		if (!TryResolve(out failReason))
			return false;
		if (eventArgs == null)
		{
			failReason = "action event args are null";
			return false;
		}
		// Fail closed: the live interop has no typed action start/end EventArgs subclass, so a
		// type-only read cannot tell started from ended. Use the dispatcher overload.
		failReason = "typed action event read unavailable: " + GameSymbols.BattleEventLaws.RoundActionEventArgsTypesAbsentLive;
		return false;
	}

	internal static bool TryReadActionEvent(
		object eventArgs,
		bool started,
		out ActionEventInfo info,
		out string failReason)
	{
		info = default;
		if (eventArgs == null)
		{
			failReason = "action dispatcher event args are null";
			return false;
		}
		var type = eventArgs.GetType();
		TryReadIntMember(eventArgs, type, GameSymbols.BattleEventLaws.BattleEventRoundMembers, out var round);
		TryReadExactMember(eventArgs, type, GameSymbols.BattleEventLaws.BattleEventTargetMembers, out var target);
		info = new ActionEventInfo(started, round, target);
		failReason = null;
		return true;
	}

	internal static bool TryReadMovementEvent(object eventArgs, out MovementEventInfo info, out string failReason)
	{
		info = default;
		if (!TryResolve(out failReason))
			return false;
		if (eventArgs == null)
		{
			failReason = "battle movement event args are null";
			return false;
		}

		var type = eventArgs.GetType();
		if (_unitPosChangedEventArgsType.IsInstanceOfType(eventArgs))
		{
			TryReadExactMember(eventArgs, type, GameSymbols.BattleEventLaws.UnitPosChangedTargetHexMembers, out var targetHex);
			info = new MovementEventInfo(targetHex, null, 0);
			failReason = null;
			return true;
		}
		if (_unitStartedMovementEventArgsType.IsInstanceOfType(eventArgs))
		{
			TryReadExactMember(eventArgs, type, GameSymbols.BattleEventLaws.UnitStartedMovementPathMembers, out var path);
			info = new MovementEventInfo(null, path, CountEnumerable(path));
			failReason = null;
			return true;
		}

		failReason = "event args are not a resolved movement event type";
		return false;
	}

	internal static bool TryReadCastAbilityEvent(object eventArgs, out CastAbilityEventInfo info, out string failReason)
	{
		info = default;
		if (!TryResolve(out failReason))
			return false;
		if (!ValidateEvent(eventArgs, _castAbilityEventArgsType, "CastAbilityEventArgs", out failReason))
			return false;

		var type = eventArgs.GetType();
		TryReadExactMember(eventArgs, type, GameSymbols.BattleEventLaws.CastAbilityCasterMembers, out var caster);
		TryReadExactMember(eventArgs, type, GameSymbols.BattleEventLaws.CastAbilityIdMembers, out var abilityId);
		TryReadExactMember(eventArgs, type, GameSymbols.BattleEventLaws.CastAbilityNameMembers, out var abilityNameRaw);
		TryReadExactMember(eventArgs, type, GameSymbols.BattleEventLaws.CastAbilityAttackedObjectsMembers, out var attackedObjects);
		TryReadExactMember(eventArgs, type, GameSymbols.BattleEventLaws.CastAbilityAttackedHexesMembers, out var attackedHexes);
		TryReadExactMember(eventArgs, type, GameSymbols.BattleEventLaws.CastAbilityImmuneObjectsMembers, out var immuneObjects);
		TryReadIntMember(eventArgs, type, GameSymbols.BattleEventLaws.BattleEventRoundMembers, out var roundNumber);

		object abilityType = null;
		object abilityIndex = null;
		if (abilityId != null)
		{
			var abilityIdType = abilityId.GetType();
			TryReadExactMember(abilityId, abilityIdType, GameSymbols.BattleEventLaws.AbilityIdTypeMembers, out abilityType);
			TryReadExactMember(abilityId, abilityIdType, GameSymbols.BattleEventLaws.AbilityIdIndexMembers, out abilityIndex);
		}

		info = new CastAbilityEventInfo(
			caster,
			abilityId,
			abilityType,
			abilityIndex,
			abilityNameRaw as string,
			attackedObjects,
			attackedHexes,
			immuneObjects,
			roundNumber);
		failReason = null;
		return true;
	}

	internal static bool TryReadChangeAbilityEvent(object eventArgs, out ChangeAbilityEventInfo info, out string failReason)
	{
		info = default;
		if (eventArgs == null)
		{
			failReason = "ChangeAbilityEventArgs instance is null";
			return false;
		}
		if (!string.Equals(eventArgs.GetType().FullName, "Hex.Session.Battle.ChangeAbilityEventArgs", StringComparison.Ordinal)
		    && !string.Equals(eventArgs.GetType().Name, "ChangeAbilityEventArgs", StringComparison.Ordinal))
		{
			failReason = "object is not ChangeAbilityEventArgs";
			return false;
		}

		var type = eventArgs.GetType();
		if (!TryReadExactMember(eventArgs, type, GameSymbols.BattleEventLaws.ChangeAbilityTargetMembers, out var target)
		    || target == null)
		{
			failReason = "ChangeAbilityEventArgs did not expose exact target";
			return false;
		}
		if (!TryReadExactMember(eventArgs, type, GameSymbols.BattleEventLaws.ChangeAbilityTypeMembers, out var rawAbilityType)
		    || rawAbilityType is not EAbilityType abilityType)
		{
			failReason = "ChangeAbilityEventArgs did not expose exact EAbilityType";
			return false;
		}
		if (!TryReadIntMember(eventArgs, type, GameSymbols.BattleEventLaws.ChangeAbilityIndexMembers, out var abilityIndex))
		{
			failReason = "ChangeAbilityEventArgs did not expose exact ability index";
			return false;
		}

		info = new ChangeAbilityEventInfo(target, abilityType, abilityIndex);
		failReason = null;
		return true;
	}

	internal static bool TryDescribeBattleEventSurfaces(out string description, out string failReason)
	{
		description = null;
		if (!TryResolve(out failReason))
			return false;

		description =
			"unitPosChanged=" + DescribeType(_unitPosChangedEventArgsType)
			+ " unitStartedMovement=" + DescribeType(_unitStartedMovementEventArgsType)
			+ " objectTookDamage=" + DescribeType(_objectTookDamageEventArgsType)
			+ " objectDestroyed=" + DescribeType(_objectDestroyedEventArgsType)
			+ " castAbility=" + DescribeType(_castAbilityEventArgsType);
		failReason = null;
		return true;
	}

	internal static bool TryGetTypedEventType(
		Homm3DirectStateHookSurface surface,
		out Type eventType,
		out string failReason)
	{
		eventType = null;
		if (!TryResolve(out failReason))
			return false;
		switch (surface)
		{
			case Homm3DirectStateHookSurface.CastCommitted:
				eventType = _castAbilityEventArgsType;
				break;
			case Homm3DirectStateHookSurface.MovementCommitted:
				eventType = _unitPosChangedEventArgsType;
				break;
			case Homm3DirectStateHookSurface.ObjectDestroyed:
				eventType = _objectDestroyedEventArgsType;
				break;
			case Homm3DirectStateHookSurface.ObjectSpawned:
				eventType = _objectSpawnedEventArgsType;
				break;
			case Homm3DirectStateHookSurface.RoundStart:
			case Homm3DirectStateHookSurface.RoundEnd:
			case Homm3DirectStateHookSurface.ActionStart:
			case Homm3DirectStateHookSurface.ActionEnd:
				failReason = "typed event context is unresolved for " + surface + ": "
					+ GameSymbols.BattleEventLaws.RoundActionEventArgsTypesAbsentLive;
				return false;
			default:
				failReason = "no exact typed event context is wired for " + surface;
				return false;
		}
		if (eventType == null)
		{
			failReason = "typed event context is unresolved for " + surface;
			return false;
		}
		failReason = null;
		return true;
	}

	internal static bool TryResolveLawOwnerFromBattleObject(
		object battleObject,
		int lawIndex,
		out object lawOwner,
		out string failReason)
	{
		lawOwner = null;
		if (battleObject == null)
		{
			failReason = "battle object is null";
			return false;
		}
		if (lawIndex <= 0)
		{
			failReason = "law index must be positive";
			return false;
		}

		if (!TryGetLawOwnerProbeHandlerKey(lawIndex, out var handlerKey, out failReason))
		{
			lawOwner = null;
			return false;
		}
		if (!TryResolveDataSideFromBattleLawSource(battleObject, out var dataSide, out var dataSideFailReason))
		{
			lawOwner = null;
			failReason = dataSideFailReason;
			return false;
		}
		if (!Homm3CustomLawHandlerRegistry.TryProbeHandler(dataSide, handlerKey, lawIndex, out _, out failReason))
		{
			lawOwner = null;
			failReason = "central battle-unit Data.Side law-owner probe failed: " + failReason;
			return false;
		}

		lawOwner = dataSide;
		failReason = null;
		return true;
	}

	internal static bool TryResolveDataSideFromBattleObject(
		object battleObject,
		out object dataSide,
		out string failReason)
	{
		return TryResolveDataSideFromBattleLawSource(battleObject, out dataSide, out failReason);
	}
	private static bool TryResolveDataSideFromBattleLawSource(object source, out object dataSide, out string failReason)
	{
		dataSide = null;
		if (Homm3BattleUnitLawOwnerRegistry.TryResolveDataSide(source, out dataSide))
		{
			failReason = null;
			return true;
		}
		var sourceType = source?.GetType();
		if (TryReadExactMember(source, sourceType, GameSymbols.BattleEventLaws.CasterBattleSideMembers, out var battleSide)
		    && Homm3BattleUnitLawOwnerRegistry.TryResolveDataSideFromBattleSide(battleSide, out dataSide))
		{
			Homm3BattleUnitLawOwnerRegistry.RegisterBattleObjectTransferSide(source, battleSide, "exact caster battle-side member");
			failReason = null;
			return true;
		}
		failReason = "central battle law-owner registry could not resolve a Data.Side for "
		             + DescribeObject(source)
		             + "; unit route failed and exact caster battle-side route failed";
		return false;
	}

	private static bool TryGetLawOwnerProbeHandlerKey(int lawIndex, out string handlerKey, out string failReason)
	{
		switch (lawIndex)
		{
			case Homm3CustomFactionLawRuntime.HeroPrimaryStatTrainingIndex:
				handlerKey = "damage.training";
				failReason = null;
				return true;
			case Homm3CustomFactionLawRuntime.CounterstrokeDoctrineIndex:
				handlerKey = "counterattack.doctrine";
				failReason = null;
				return true;
			case Homm3CustomFactionLawRuntime.MeleeFormationIndex:
				handlerKey = "battle.melee-formation";
				failReason = null;
				return true;
			case Homm3CustomFactionLawRuntime.RangedFormationIndex:
				handlerKey = "battle.ranged-formation";
				failReason = null;
				return true;
			case Homm3CustomFactionLawRuntime.MoraleFlatIndex:
				handlerKey = "morale.package";
				failReason = null;
				return true;
			case Homm3CustomFactionLawRuntime.MoraleTriggerIndex:
				handlerKey = "morale.trigger";
				failReason = null;
				return true;
			default:
				handlerKey = null;
				failReason = "no battle-object law-owner probe handler is registered for law index "
				             + lawIndex.ToString(System.Globalization.CultureInfo.InvariantCulture);
				return false;
		}
	}

	internal static bool TryResolve(out string failReason)
	{
		if (_resolved)
		{
			failReason = _resolveFailure;
			return _resolveFailure == null;
		}

		_resolved = true;
		using var loadTiming = Homm3LoadTiming.Scope("Homm3BattleEventNativeAdapter.TryResolve (battle-event law type hints)");
		_unitPosChangedEventArgsType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.BattleEventLawsUnitPosChangedEventArgs);
		_unitStartedMovementEventArgsType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.BattleEventLawsUnitStartedMovementEventArgs);
		_objectTookDamageEventArgsType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.BattleEventLawsObjectTookDamageEventArgs);
		_objectDestroyedEventArgsType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.BattleEventLawsObjectDestroyedEventArgs);
		_objectSpawnedEventArgsType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.BattleEventLawsObjectSpawnedEventArgs);
		_castAbilityEventArgsType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.BattleEventLawsCastAbilityEventArgs);

		if (_unitPosChangedEventArgsType == null)
			return FailResolve("UnitPosChangedEventArgs type was not found", out failReason);
		if (_unitStartedMovementEventArgsType == null)
			return FailResolve("UnitStartedMovementEventArgs type was not found", out failReason);
		if (_objectTookDamageEventArgsType == null)
			return FailResolve("ObjectTookDamageEventArgs type was not found", out failReason);
		if (_objectDestroyedEventArgsType == null)
			return FailResolve("ObjectDestroyedEventArgs type was not found", out failReason);
		if (_objectSpawnedEventArgsType == null)
			return FailResolve("ObjectSpawnedEventArgs type was not found", out failReason);
		if (_castAbilityEventArgsType == null)
			return FailResolve("CastAbilityEventArgs type was not found", out failReason);

		failReason = null;
		return true;
	}

	private static bool ValidateEvent(object eventArgs, Type expectedType, string label, out string failReason)
	{
		if (eventArgs == null)
		{
			failReason = label + " instance is null";
			return false;
		}
		if (expectedType == null)
		{
			failReason = label + " type is unresolved";
			return false;
		}
		if (!expectedType.IsInstanceOfType(eventArgs))
		{
			failReason = "object is not a resolved " + label + " instance";
			return false;
		}
		failReason = null;
		return true;
	}

	private static bool FailResolve(string reason, out string failReason)
	{
		_resolveFailure = reason;
		failReason = reason;
		return false;
	}

	private static bool TryReadIntMember(object value, Type type, string[] names, out int result)
	{
		result = 0;
		if (!TryReadExactMember(value, type, names, out var raw) || raw == null)
			return false;
		try
		{
			result = Convert.ToInt32(raw, System.Globalization.CultureInfo.InvariantCulture);
			return true;
		}
		catch
		{
			return false;
		}
	}

	private static bool TryReadBoolMember(object value, Type type, string[] names, out bool result)
	{
		result = false;
		if (!TryReadExactMember(value, type, names, out var raw) || raw == null)
			return false;
		if (raw is bool b)
		{
			result = b;
			return true;
		}
		return false;
	}

	private static bool TryReadExactMember(object value, Type type, string[] names, out object raw)
	{
		raw = null;
		if (value == null || type == null || names == null)
			return false;
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			for (var current = type; current != null && current != typeof(object); current = current.BaseType)
			{
				const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
				try
				{
					var field = current.GetField(name, flags);
					if (field != null)
					{
						raw = field.GetValue(value);
						return true;
					}
				}
				catch
				{
				}
				try
				{
					var property = current.GetProperty(name, flags);
					if (property != null && property.GetIndexParameters().Length == 0)
					{
						raw = property.GetValue(value, null);
						return true;
					}
				}
				catch
				{
				}
				try
				{
					var method = current.GetMethod(name, flags, null, Type.EmptyTypes, null);
					if (method != null && method.ReturnType != typeof(void) && !method.ContainsGenericParameters)
					{
						raw = method.Invoke(value, null);
						return true;
					}
				}
				catch
				{
				}
			}
		}
		return false;
	}

	private static int CountEnumerable(object value)
	{
		if (value is not System.Collections.IEnumerable enumerable)
			return 0;
		var count = 0;
		foreach (var _ in enumerable)
		{
			count++;
			if (count > 512)
				break;
		}
		return count;
	}

	private static string DescribeCollection(object value)
	{
		if (value == null)
			return "null";
		if (value is not System.Collections.IEnumerable enumerable || value is string)
			return DescribeObject(value);
		var count = 0;
		var samples = new List<string>(3);
		foreach (var item in enumerable)
		{
			if (samples.Count < 3)
				samples.Add(DescribeObject(item));
			count++;
			if (count > 512)
				break;
		}
		return "{count=" + count + ";sample=[" + string.Join(",", samples) + "]}";
	}

	private static string DescribeType(Type type)
	{
		return type?.FullName ?? "unresolved";
	}

	private static string DescribeObject(object value)
	{
		if (value == null)
			return "null";
		var type = value.GetType();
		return type.FullName ?? type.Name;
	}

	private static string FormatShortValue(object value)
	{
		if (value == null)
			return "null";
		var text = value.ToString();
		if (string.IsNullOrEmpty(text))
			text = "(empty)";
		return text.Length <= 80 ? text : text.Substring(0, 80) + "...";
	}
}
