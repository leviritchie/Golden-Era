using System;

using System.Reflection;

using HarmonyLib;



namespace OfflineUnlockMod;



/// <summary>

/// Publishes OnUnitChangedHex after a successful hex occupancy write so battle

/// views refresh. Logic hex alone does not move the ecz placement transform.

/// </summary>

internal static class Homm3DirectStateMovementPublish

{

	private static Type _unitPosChangedEventArgsType;

	private static ConstructorInfo _unitPosChangedCtor;

	private static MethodInfo _positionChangedDispatch;

	private static string _resolveFailure;

	private static string _resolvedDispatchName;



	internal static bool TryPublishUnitPosChanged(object unit, object destinationHex, out string failReason)

	{

		if (unit == null || destinationHex == null)

		{

			failReason = "unit pos publish requires unit and destination hex";

			return false;

		}



		if (!TryResolveEventContextAndHub(unit, out var eventContext, out var eventHub, out failReason))

			return false;

		if (!TryResolveDispatch(eventHub, out failReason))

			return false;



		object eventArgs;

		try

		{

			eventArgs = _unitPosChangedCtor.Invoke(new[] { unit, destinationHex });

		}

		catch (Exception ex)

		{

			failReason = "UnitPosChangedEventArgs construction failed: "

			             + ex.GetBaseException().GetType().Name + ": " + ex.GetBaseException().Message;

			return false;

		}



		if (eventArgs == null)

		{

			failReason = "UnitPosChangedEventArgs construction returned null";

			return false;

		}



		try

		{

			if (_positionChangedDispatch != null)

			{

				// Preferred: hub dispatcher Method_20 (OnUnitChangedHex) / Method_45 (UnitPosChanged).

				_positionChangedDispatch.Invoke(eventHub, new[] { eventContext, eventArgs });

			}

			else

			{

				// Fallback: invoke the OnUnitChangedHex EventHandler property directly.

				if (!TryInvokeChangedHexEventHandler(eventHub, eventContext, eventArgs, out failReason))

					return false;

			}

			failReason = null;

			return true;

		}

		catch (Exception ex)

		{

			failReason = "UnitPosChanged dispatch failed via "

			             + (_resolvedDispatchName ?? "unknown")

			             + ": "

			             + ex.GetBaseException().GetType().Name + ": " + ex.GetBaseException().Message;

			return false;

		}

	}



	private static bool TryResolveEventContextAndHub(

		object unit,

		out object eventContext,

		out object eventHub,

		out string failReason)

	{

		eventContext = null;

		eventHub = null;

		var abilityManager = ReadFirstMember(unit, GameSymbols.DirectStateLaws.UnitAbilityManagerMembers)

		                     ?? ReadFirstMember(unit, GameSymbols.BuffDebuffLaws.BuffSourceAbilityManagerMembers);

		if (abilityManager == null)

		{

			failReason = "unit ability manager unavailable for movement publish";

			return false;

		}



		eventContext = ReadFirstMember(

			abilityManager,

			GameSymbols.BuffDebuffLaws.BuffAbilityManagerEventContextMembers);

		if (eventContext == null)

		{

			failReason = "unit event context (dxx.ceih) unavailable for movement publish";

			return false;

		}



		eventHub = ReadFirstMember(

			eventContext,

			GameSymbols.BuffDebuffLaws.BuffEventContextEventHubMembers);

		if (eventHub == null)

		{

			failReason = "battle event hub (ecz.cfhc) unavailable for movement publish";

			return false;

		}



		failReason = null;

		return true;

	}



	private static bool TryResolveDispatch(object eventHub, out string failReason)

	{

		if ((_positionChangedDispatch != null || string.Equals(_resolvedDispatchName, "EventHandler_21", StringComparison.Ordinal))

		    && _unitPosChangedCtor != null)

		{

			failReason = null;

			return true;

		}



		if (!string.IsNullOrEmpty(_resolveFailure))

		{

			failReason = _resolveFailure;

			return false;

		}



		_unitPosChangedEventArgsType = null;

		foreach (var hint in GameSymbols.BattleEventLaws.UnitPosChangedEventArgsTypeHints)

		{

			_unitPosChangedEventArgsType =

				GameMember.FindType(GameSymbols.BattleEventLaws.UnitPosChangedEventArgsTypeId + "." + hint, hint)

				?? AccessTools.TypeByName(hint);

			if (_unitPosChangedEventArgsType != null)

				break;

		}

		if (_unitPosChangedEventArgsType == null)

		{

			_resolveFailure = "UnitPosChangedEventArgs type was not found";

			failReason = _resolveFailure;

			return false;

		}



		_unitPosChangedCtor = ResolveUnitHexConstructor(_unitPosChangedEventArgsType);

		if (_unitPosChangedCtor == null)

		{

			_resolveFailure = "UnitPosChangedEventArgs(Unit, Hex) constructor was not found";

			failReason = _resolveFailure;

			return false;

		}



		var hubType = eventHub.GetType();

		// Combat push presentation: OnUnitChangedHex first (Method_20 / field_21).

		_positionChangedDispatch = ResolveDispatchMethod(

			hubType,

			GameSymbols.DirectStateLaws.MovementChangedHexDispatch);

		if (_positionChangedDispatch != null)

		{

			_resolvedDispatchName = _positionChangedDispatch.Name;

			failReason = null;

			return true;

		}



		// Native UnitPosChangedEventArgs path (ISIL bcqv / field_46 / Method_45).

		_positionChangedDispatch = ResolveDispatchMethod(

			hubType,

			GameSymbols.DirectStateLaws.MovementPositionChangedDispatch);

		if (_positionChangedDispatch != null)

		{

			_resolvedDispatchName = _positionChangedDispatch.Name;

			failReason = null;

			return true;

		}



		if (HasChangedHexEventHandler(hubType))

		{

			_resolvedDispatchName = "EventHandler_21";

			failReason = null;

			return true;

		}



		_resolveFailure = "edb OnUnitChangedHex dispatch was not found on hub "

		                  + (hubType.FullName ?? hubType.Name)

		                  + " (tried Method_20/bcqt, Method_45/bcqv, EventHandler_21)";

		failReason = _resolveFailure;

		return false;

	}



	private static bool HasChangedHexEventHandler(Type hubType)

	{

		if (hubType == null)

			return false;

		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;

		for (var i = 0; i < GameSymbols.DirectStateLaws.MovementChangedHexEventHandlerMembers.Length; i++)

		{

			var name = GameSymbols.DirectStateLaws.MovementChangedHexEventHandlerMembers[i];

			if (hubType.GetProperty(name, flags) != null || hubType.GetField(name, flags) != null

			    || hubType.GetMethod(name, flags, null, Type.EmptyTypes, null) != null)

				return true;

		}

		return false;

	}



	private static bool TryInvokeChangedHexEventHandler(

		object eventHub,

		object eventContext,

		object eventArgs,

		out string failReason)

	{

		var handler = ReadFirstMember(eventHub, GameSymbols.DirectStateLaws.MovementChangedHexEventHandlerMembers);

		if (handler == null)

		{

			failReason = "OnUnitChangedHex EventHandler_21 is null (no subscribers)";

			return false;

		}



		MethodInfo invoke = null;

		for (var current = handler.GetType(); current != null && current != typeof(object); current = current.BaseType)

		{

			invoke = current.GetMethod(

				"Invoke",

				BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,

				null,

				new[] { typeof(object), eventArgs.GetType() },

				null);

			if (invoke != null)

				break;

			invoke = current.GetMethod(

				"Invoke",

				BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);

			if (invoke != null && invoke.GetParameters().Length == 2)

				break;

			invoke = null;

		}

		if (invoke == null)

		{

			failReason = "OnUnitChangedHex EventHandler_21 Invoke was not found";

			return false;

		}



		invoke.Invoke(handler, new[] { eventContext, eventArgs });

		failReason = null;

		return true;

	}



	private static ConstructorInfo ResolveUnitHexConstructor(Type eventArgsType)

	{

		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;

		foreach (var ctor in eventArgsType.GetConstructors(flags))

		{

			var parameters = ctor.GetParameters();

			if (parameters.Length != 2)

				continue;

			var p0 = parameters[0].ParameterType.Name ?? string.Empty;

			var p1 = parameters[1].ParameterType.Name ?? string.Empty;

			if (p0.IndexOf("Unit", StringComparison.OrdinalIgnoreCase) < 0)

				continue;

			if (p1.IndexOf("Hex", StringComparison.OrdinalIgnoreCase) < 0)

				continue;

			return ctor;

		}

		return null;

	}



	private static MethodInfo ResolveDispatchMethod(Type hubType, GameSymbols.MethodSymbol symbol)

	{

		if (hubType == null || symbol.NameHints == null)

			return null;

		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;

		for (var current = hubType; current != null && current != typeof(object); current = current.BaseType)

		{

			foreach (var method in current.GetMethods(flags | BindingFlags.DeclaredOnly))

			{

				if (method.ReturnType != typeof(void))

					continue;

				var parameters = method.GetParameters();

				if (parameters.Length != 2)

					continue;

				var second = parameters[1].ParameterType;

				var secondName = second.Name ?? string.Empty;

				if (secondName.IndexOf("BattleEventArgs", StringComparison.Ordinal) < 0

				    && secondName.IndexOf("UnitPosChanged", StringComparison.Ordinal) < 0)

					continue;

				foreach (var hint in symbol.NameHints)

				{

					if (string.IsNullOrWhiteSpace(hint))

						continue;

					if (string.Equals(method.Name, hint, StringComparison.Ordinal))

						return method;

				}

			}

		}

		return null;

	}



	private static object ReadFirstMember(object target, string[] names)

	{

		if (target == null || names == null)

			return null;

		for (var current = target.GetType(); current != null && current != typeof(object); current = current.BaseType)

		{

			const BindingFlags flags =

				BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;

			for (var i = 0; i < names.Length; i++)

			{

				var name = names[i];

				if (string.IsNullOrWhiteSpace(name))

					continue;

				try

				{

					var field = current.GetField(name, flags);

					if (field != null)

					{

						var value = field.GetValue(target);

						if (value != null)

							return value;

					}

					var property = current.GetProperty(name, flags);

					if (property != null && property.GetIndexParameters().Length == 0)

					{

						var value = property.GetValue(target, null);

						if (value != null)

							return value;

					}

					var method = current.GetMethod(name, flags, null, Type.EmptyTypes, null);

					if (method != null && method.ReturnType != typeof(void))

					{

						var value = method.Invoke(target, null);

						if (value != null)

							return value;

					}

				}

				catch

				{

				}

			}

		}

		return null;

	}

}


