using System;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.InteropServices;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.InteropTypes;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Feeds target-side attack direction into HoMM3 flat battle billboards. Release battle drawer roots do not
/// receive the playtest action rotation, so stationary backwards-angle attacks need an explicit
/// target-position signal rather than root-motion detection.
/// </summary>
internal static class Homm3BattleAttackFacingHook
{
	private static bool _patched;
	private static int _loggedDecision;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		Register(harmony, log, required: false);
	}

	internal static void RegisterRequiredReleaseSafeSlice(Harmony harmony, ManualLogSource log)
	{
		Register(harmony, log, required: true);
	}

	private static void Register(Harmony harmony, ManualLogSource log, bool required)
	{
		if (_patched)
			return;
		if (harmony == null)
		{
			if (required)
				throw new InvalidOperationException("Harmony was not initialized before required battle attack-facing registration.");
			return;
		}
		try
		{
			var timelinePatched = PatchTimelineHelper(harmony, log);
			if (required && !timelinePatched)
				throw new InvalidOperationException("required battle attack-facing surface missing: BhBattleTimelineHelper void(Unit,Unit,drawer,drawer) bind not found.");

			var methods = new List<MethodInfo>();
			if (!timelinePatched)
			{
				var battleUnitViewType = ResolveAssemblyType(GameSymbols.BattleVisual.BattleDrawerTypeNames);
				if (battleUnitViewType == null)
				{
					HandleMissing(required, "battle drawer type not found.");
					return;
				}
				methods = FindAttackEventMethods(battleUnitViewType);
				if (methods.Count == 0)
				{
					HandleMissing(required, "no timeline helper or battle drawer void(object,BattleEventArgs) handler found.");
					return;
				}
			}

			foreach (var method in methods)
				harmony.Patch(method, postfix: new HarmonyMethod(typeof(Homm3BattleAttackFacingHook), nameof(PostfixAttackStart)));
			_patched = true;
			log?.LogInfo("Homm3 battle attack facing: patched " + methods.Count + " fallback battle drawer event handler(s); timeline helper patched=" + timelinePatched + ".");
		}
		catch (Exception ex)
		{
			if (required)
				throw;
			log?.LogWarning("Homm3 battle attack facing hook failed: " + ex.GetType().Name + ": " + ex.Message);
		}
	}

	private static bool PatchTimelineHelper(Harmony harmony, ManualLogSource log)
	{
		try
		{
			var helperType = FindBattleTimelineHelperType();
			if (helperType == null)
				return false;
			const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
			MethodInfo exactMatch = null;
			MethodInfo shapeMatch = null;
			foreach (var method in helperType.GetMethods(flags))
			{
				if (method.ReturnType != typeof(void))
					continue;
				var ps = method.GetParameters();
				if (ps.Length != 4)
					continue;
				if (ps[0].ParameterType != typeof(Unit)
				    || ps[1].ParameterType != typeof(Unit)
				    || !MatchesBattleDrawerParameterType(ps[2].ParameterType)
				    || !MatchesBattleDrawerParameterType(ps[3].ParameterType))
					continue;

				if (Array.IndexOf(GameSymbols.BattleVisual.TimelineAttackBind.NameHints, method.Name) >= 0)
					exactMatch ??= method;
				else
					shapeMatch ??= method;
			}

			var target = exactMatch ?? shapeMatch;
			if (target == null)
				return false;

			harmony.Patch(target, postfix: new HarmonyMethod(typeof(Homm3BattleAttackFacingHook), nameof(PostfixTimelineAttack)));
			log?.LogInfo("Homm3 battle attack facing: patched timeline helper " + helperType.FullName + "." + target.Name + ".");
			return true;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3 battle attack facing timeline helper hook failed: " + ex.GetType().Name + ": " + ex.Message);
		}
		return false;
	}

	private static Type FindBattleTimelineHelperType()
	{
		var asm = typeof(ObjCityConfig).Assembly;
		var type = asm.GetType("Hex.Session.Battle.BhBattleTimelineHelper", throwOnError: false)
		           ?? asm.GetType("BhBattleTimelineHelper", throwOnError: false);
		if (type != null)
			return type;
		return GameMember.FindType("battle.visual.timelineHelper", "BhBattleTimelineHelper");
	}

	private static bool MatchesBattleDrawerParameterType(Type parameterType)
	{
		if (parameterType == null)
			return false;
		foreach (var typeName in GameSymbols.BattleVisual.BattleDrawerTypeNames)
		{
			if (string.Equals(parameterType.Name, typeName, StringComparison.Ordinal))
				return true;
			var resolved = ResolveAssemblyType(new[] { typeName });
			if (resolved != null
			    && (GameInteropTypes.TypesMatch(parameterType, resolved)
			        || resolved.IsAssignableFrom(parameterType)
			        || parameterType.IsAssignableFrom(resolved)))
				return true;
		}
		return false;
	}

	private static bool IsBattleDrawerTypeName(string name)
	{
		if (string.IsNullOrWhiteSpace(name))
			return false;
		foreach (var typeName in GameSymbols.BattleVisual.BattleDrawerTypeNames)
		{
			if (string.Equals(name, typeName, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static void HandleMissing(bool required, string message)
	{
		if (required)
			throw new InvalidOperationException("required battle attack-facing surface missing: " + message);
		Plugin.LogSource?.LogWarning("Homm3 battle attack facing: " + message);
	}

	private static List<MethodInfo> FindAttackEventMethods(Type battleUnitViewType)
	{
		var result = new List<MethodInfo>();
		var candidateNames = new HashSet<string>(StringComparer.Ordinal)
		{
			"cvf",
			"mhg",
			"bbuv",
			"icf",
			"myh",
			"bbwc",
			"nay",
			"bbwm",
			"mez",
		};
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		foreach (var method in battleUnitViewType.GetMethods(flags))
		{
			if (!candidateNames.Contains(method.Name))
				continue;
			if (method.ReturnType != typeof(void))
				continue;
			var ps = method.GetParameters();
			if (ps.Length == 2 && string.Equals(ps[1].ParameterType.Name, "BattleEventArgs", StringComparison.Ordinal))
				result.Add(method);
		}
		return result;
	}

	private static void PostfixAttackStart(object __instance, [HarmonyArgument(1)] object eventArgs)
	{
		try
		{
			if (__instance == null || eventArgs == null)
				return;

			var viewUnit = ResolveViewUnit(__instance);
			if (viewUnit == null)
				return;
			var round = GetMemberValue(eventArgs, "roundNumber");
			var timelineHelper = ResolveTimelineHelper(__instance);

			var attackerDrawer = GetMemberValue(timelineHelper, "attackerDrawer");
			if (attackerDrawer != null && !SameObject(attackerDrawer, __instance))
			{
				LogDecision("event skip:not attacker drawer", null, DescribeUnit(viewUnit), DescribeUnit(GetMemberValue(timelineHelper, "attacker")), DescribeUnit(GetMemberValue(timelineHelper, "target") ?? GetMemberValue(eventArgs, "target")), round);
				return;
			}

			var attackerUnit = GetMemberValue(timelineHelper, "attacker");
			if (attackerUnit == null)
			{
				LogDecision("event skip:missing attacker unit", null, DescribeUnit(viewUnit), "null", DescribeUnit(GetMemberValue(timelineHelper, "target") ?? GetMemberValue(eventArgs, "target")), round);
				return;
			}

			if (!SameObject(attackerUnit, viewUnit))
			{
				LogDecision("event skip:not attacker unit", null, DescribeUnit(viewUnit), DescribeUnit(attackerUnit), DescribeUnit(GetMemberValue(timelineHelper, "target") ?? GetMemberValue(eventArgs, "target")), round);
				return;
			}

			var targetUnit = GetMemberValue(timelineHelper, "target") ?? GetMemberValue(eventArgs, "target");
			var targetDrawer = GetMemberValue(timelineHelper, "targetDrawer");
			TryApplyAttackFacing(__instance, targetDrawer, attackerUnit, targetUnit, round, "event");
		}
		catch (Exception ex)
		{
			LogDecision("event skip:" + ex.GetType().Name + ": " + ex.Message, null, "?", "?", "?", null);
		}
	}

	private static void PostfixTimelineAttack(object __0, object __1, object __2, object __3)
	{
		try
		{
			// BhBattleTimelineHelper.bbsg/bbtg(Unit attacker, Unit target, ecd attackerDrawer, ecd targetDrawer)
			TryApplyAttackFacing(__2, __3, __0, __1, null, "timeline");
		}
		catch (Exception ex)
		{
			LogDecision("timeline skip:" + ex.GetType().Name + ": " + ex.Message, null, "?", "?", "?", null);
		}
	}

	private static void TryApplyAttackFacing(object attackerDrawer, object targetDrawer, object attackerUnit, object targetUnit, object round, string source)
	{
		if (attackerDrawer == null || attackerUnit == null || targetUnit == null)
		{
			LogDecision(source + " skip:missing attacker/target", null, DescribeUnit(attackerUnit), DescribeUnit(attackerUnit), DescribeUnit(targetUnit), round);
			return;
		}
		if (!TryResolveViewRoot(attackerDrawer, out var attackerRoot) || !attackerRoot)
		{
			LogDecision(source + " skip:attacker root", null, DescribeUnit(attackerUnit), DescribeUnit(attackerUnit), DescribeUnit(targetUnit), round);
			return;
		}
		if (!TryResolveHomm3BattleRoot(attackerRoot, out var homm3Root))
		{
			LogDecision(source + " skip:no HoMM3 battle root", attackerRoot, DescribeUnit(attackerUnit), DescribeUnit(attackerUnit), DescribeUnit(targetUnit), round);
			return;
		}
		var viewUnit = ResolveViewUnit(attackerDrawer);
		var viewSid = DescribeUnit(viewUnit);
		var attackerSid = DescribeUnit(attackerUnit);
		var targetSid = DescribeUnit(targetUnit);
		if (viewUnit != null && !SameObject(attackerUnit, viewUnit))
		{
			LogDecision(source + " skip:not attacker unit", attackerRoot, viewSid, attackerSid, targetSid, round);
			return;
		}
		if (SameObject(targetUnit, attackerUnit))
		{
			LogDecision(source + " skip:self target unit", attackerRoot, viewSid, attackerSid, targetSid, round);
			return;
		}
		if (!TryResolveUnitVisualPosition(targetUnit, targetDrawer, out var targetPosition))
		{
			LogDecision(source + " skip:target visual position", attackerRoot, viewSid, attackerSid, targetSid, round);
			return;
		}

		const float attackDirectionWindowSeconds = 4.0f;
		var appliedSkinnedFacing = false;
		var skinnedFacingDeltaDeg = 0f;
		if (Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(homm3Root))
		{
			skinnedFacingDeltaDeg = Homm3ImportVisuals.MeasureSkinnedTargetFacingDelta(homm3Root, targetPosition);
			appliedSkinnedFacing = Homm3ImportVisuals.TryApplySkinnedBattleTargetFacing(homm3Root, targetPosition);
		}
		var appliedFrames = appliedSkinnedFacing
		                  || Homm3BattleDiskTextureRemap.TryApplyAttackDirection(homm3Root, targetPosition, attackDirectionWindowSeconds)
		                  || Homm3BattleArrayBillboard.TryApplyAttackDirection(homm3Root, targetPosition, attackDirectionWindowSeconds);
		var appliedCannonShot = IsCoveCannonAttack(homm3Root, attackerSid) && Homm3CoveCannonVisuals.TryPlayShootAnimation(homm3Root, Plugin.LogSource);
		var appliedPirateShot = IsCovePirateGunSid(attackerSid) && Homm3CovePirateShotAudio.TryPlayShot();
		var facingMode = appliedSkinnedFacing ? "skinned_target" : "billboard";
		LogDecision(
			source
			+ " apply:frames=" + appliedFrames
			+ " skinnedFacing=" + appliedSkinnedFacing
			+ " skinnedDelta=" + skinnedFacingDeltaDeg.ToString("0.#")
			+ " attackerYaw=" + (attackerRoot && attackerRoot.transform ? attackerRoot.transform.eulerAngles.y.ToString("0.#") : "?")
			+ " targetPos=" + targetPosition.ToString("0.##")
			+ " cannonShot=" + appliedCannonShot
			+ " pirateShot=" + appliedPirateShot
			+ " facing=" + facingMode
			+ " drawerRoot='" + attackerRoot.name + "'", homm3Root, viewSid, attackerSid, targetSid, round);
	}

	private static bool IsCoveCannonAttack(GameObject homm3Root, string describedSid)
	{
		if (Homm3CoveCannonVisuals.IsCannonVisualRoot(homm3Root))
			return true;
		return !string.IsNullOrWhiteSpace(describedSid)
		       && (string.Equals(describedSid, Homm3CoveCannonVisuals.UnitSid, StringComparison.Ordinal)
		           || describedSid.StartsWith(Homm3CoveCannonVisuals.UnitSid + "@", StringComparison.Ordinal));
	}

	private static bool IsCovePirateGunSid(string describedSid)
	{
		if (string.IsNullOrWhiteSpace(describedSid))
			return false;
		return IsExactOrStackSid(describedSid, "h3_pirate")
		       || IsExactOrStackSid(describedSid, "h3_corsair")
		       || IsExactOrStackSid(describedSid, "h3_sea_dog");
	}

	private static bool IsExactOrStackSid(string describedSid, string sid)
	{
		return string.Equals(describedSid, sid, StringComparison.Ordinal)
		       || describedSid.StartsWith(sid + "@", StringComparison.Ordinal);
	}

	private static object ResolveViewUnit(object view)
	{
		return GetFirstMemberOrNoArg(view, GameSymbols.BattleVisual.AttackFacingViewUnitMembers);
	}

	private static object ResolveTimelineHelper(object view)
	{
		return GetFirstMemberOrNoArg(view, GameSymbols.BattleVisual.AttackFacingTimelineHelperMembers);
	}

	private static bool TryResolveUnitVisualPosition(object unit, object drawer, out Vector3 position)
	{
		position = default;
		// The timeline helper exposes the target's drawer (bbsg/bbtg targetDrawer), which
		// resolves the same way the attacker drawer does. The bare Unit (and its bases) has no
		// view, drawer or GameObject member on 25672315, so there is no Unit-side fallback.
		if (drawer != null && TryResolveViewRoot(drawer, out var drawerRoot) && drawerRoot && drawerRoot.transform)
		{
			position = TryResolveHomm3BattleRoot(drawerRoot, out var homm3Root) && homm3Root && homm3Root.transform
				? homm3Root.transform.position
				: drawerRoot.transform.position;
			return true;
		}

		return false;
	}

	private static bool TryResolveViewRoot(object view, out GameObject root)
	{
		root = GetFirstGameObjectMember(view, GameSymbols.BattleVisual.EcdVisualGameObjectFields)
		       ?? GetFirstGameObjectMember(view, GameSymbols.BattleVisual.EczRootGameObjectFields)
		       ?? GetFirstMemberOrNoArg(view, GameSymbols.BattleVisual.AttackFacingViewRootGameObjectMembers) as GameObject;
		if (root != null && root)
			return true;

		if (TryResolveEczViewRoot(view, out root))
			return true;

		var component = view as Component;
		root = component != null && component ? component.gameObject : null;
		return root != null && root;
	}

	private static bool TryResolveHomm3BattleRoot(GameObject root, out GameObject homm3Root)
	{
		homm3Root = null;
		if (!root)
			return false;
		if (Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(root))
		{
			homm3Root = root;
			return true;
		}
		if (HasHomm3BattleHelper(root))
		{
			homm3Root = root;
			return true;
		}

		var directBattle = root.transform ? root.transform.Find("battle") : null;
		if (directBattle && (Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(directBattle.gameObject)
		                     || HasHomm3BattleHelper(directBattle.gameObject)))
		{
			homm3Root = directBattle.gameObject;
			return true;
		}

		var facing = GetComponentInChildrenSafe<Homm3BattleBillboardCameraFacing>(root);
		if (facing != null && facing && facing.gameObject)
		{
			homm3Root = facing.gameObject;
			return true;
		}

		var remap = GetComponentInChildrenSafe<Homm3BattleDiskTextureRemap>(root);
		if (remap != null && remap && remap.gameObject)
		{
			homm3Root = remap.gameObject;
			return true;
		}

		var arrayBillboard = GetComponentInChildrenSafe<Homm3BattleArrayBillboard>(root);
		if (arrayBillboard != null && arrayBillboard && arrayBillboard.gameObject)
		{
			homm3Root = arrayBillboard.gameObject;
			return true;
		}

		var cannonAnimator = GetComponentInChildrenSafe<Homm3CoveCannonBattleAnimator>(root);
		if (cannonAnimator != null && cannonAnimator && cannonAnimator.gameObject)
		{
			homm3Root = cannonAnimator.gameObject;
			return true;
		}

		return false;
	}

	private static Type ResolveAssemblyType(IEnumerable<string> names)
	{
		var asm = typeof(ObjCityConfig).Assembly;
		if (names == null)
			return null;
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var type = asm.GetType(name, throwOnError: false);
			if (type != null)
				return type;
			type = GameMember.FindType("battle.visual.drawer." + name, name);
			if (type != null)
				return type;
		}
		return null;
	}

	private static bool HasHomm3BattleHelper(GameObject root)
	{
		return root
		       && (GetComponentSafe<Homm3BattleBillboardCameraFacing>(root) != null
		           || GetComponentSafe<Homm3BattleDiskTextureRemap>(root) != null
		           || GetComponentSafe<Homm3BattleArrayBillboard>(root) != null
		           || Homm3CoveCannonVisuals.IsCannonVisualRoot(root));
	}

	private static T GetComponentSafe<T>(GameObject root) where T : Component
	{
		if (!root)
			return null;
		try
		{
			return root.GetComponent(Il2CppType.Of<T>())?.TryCast<T>();
		}
		catch
		{
			return null;
		}
	}

	private static T GetComponentInChildrenSafe<T>(GameObject root) where T : Component
	{
		if (!root)
			return null;
		try
		{
			var components = root.GetComponentsInChildren(Il2CppType.Of<T>(), true);
			if (components == null)
				return null;
			for (var i = 0; i < components.Length; i++)
			{
				var component = components[i]?.TryCast<T>();
				if (component != null && component)
					return component;
			}
		}
		catch
		{
			// Generic GetComponent<T> can throw after IL2CPP wrapper drift; fail closed.
		}
		return null;
	}

	private static GameObject GetFirstGameObjectMember(object owner, IEnumerable<string> names)
	{
		if (owner == null || names == null)
			return null;
		foreach (var name in names)
		{
			var value = GetMemberValue(owner, name) as GameObject;
			if (value)
				return value;
		}
		return null;
	}

	private static object GetFirstMemberOrNoArg(object owner, IEnumerable<string> names)
	{
		if (owner == null || names == null)
			return null;
		foreach (var name in names)
		{
			var value = GetMemberValue(owner, name) ?? InvokeNoArg(owner, name);
			if (value != null)
				return value;
		}
		return null;
	}

	private static bool TryResolveEczViewRoot(object view, out GameObject root)
	{
		root = null;
		if (view is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero)
			return false;

		try
		{
			root = ReadGameObjectField(il2Cpp.Pointer, 0x20) ?? ReadGameObjectField(il2Cpp.Pointer, 0x10);
			if (root != null && root)
				return true;

			var transform = ReadTransformField(il2Cpp.Pointer, 0x18);
			root = transform != null && transform ? transform.gameObject : null;
			return root != null && root;
		}
		catch
		{
			root = null;
			return false;
		}
	}

	private static GameObject ReadGameObjectField(IntPtr objectPointer, int offset)
	{
		var pointer = Marshal.ReadIntPtr(objectPointer, offset);
		return pointer == IntPtr.Zero ? null : new GameObject(pointer);
	}

	private static Transform ReadTransformField(IntPtr objectPointer, int offset)
	{
		var pointer = Marshal.ReadIntPtr(objectPointer, offset);
		return pointer == IntPtr.Zero ? null : new Transform(pointer);
	}

	private static bool SameObject(object left, object right)
	{
		if (ReferenceEquals(left, right))
			return true;
		if (left is Il2CppObjectBase leftIl2Cpp && right is Il2CppObjectBase rightIl2Cpp)
			return leftIl2Cpp.Pointer != IntPtr.Zero && leftIl2Cpp.Pointer == rightIl2Cpp.Pointer;
		return false;
	}

	private static string DescribeUnit(object unit)
	{
		if (unit == null)
			return "null";
		var sid = TryGetStringMember(unit, "configSid")
		          ?? TryGetStringMember(unit, "sid")
		          ?? TryGetStringMember(unit, "id")
		          ?? TryGetStringMember(unit, "unitSid");
		if (string.IsNullOrWhiteSpace(sid))
		{
			foreach (var name in new[] { "chey", "_chdi_k__BackingField", "<chey>k__BackingField", "chbu", "_chbu_k__BackingField", "<chbu>k__BackingField", "cggz" })
			{
				var nested = GetMemberValue(unit, name);
				sid = TryGetStringMember(nested, "configSid")
				      ?? TryGetStringMember(nested, "sid")
				      ?? TryGetStringMember(nested, "id")
				      ?? TryGetStringMember(nested, "unitSid");
				if (!string.IsNullOrWhiteSpace(sid))
					break;
			}
		}
		if (string.IsNullOrWhiteSpace(sid))
		{
			var transfer = GetFirstMemberOrNoArg(unit, GameSymbols.BattleUi.UnitTransferFields);
			if (Homm3CoveCannonVisuals.TryResolveRememberedUnitSid(transfer, out var cannonSid))
				sid = cannonSid;
		}
		var pointer = unit is Il2CppObjectBase il2Cpp && il2Cpp.Pointer != IntPtr.Zero
			? "@" + il2Cpp.Pointer.ToString("x")
			: string.Empty;
		return (string.IsNullOrWhiteSpace(sid) ? unit.GetType().Name : sid.Trim()) + pointer;
	}

	private static string TryGetStringMember(object owner, string name)
	{
		var value = GetMemberValue(owner, name);
		return value as string;
	}

	private static object GetMemberValue(object owner, string name)
	{
		if (owner == null || string.IsNullOrEmpty(name))
			return null;
		var type = owner.GetType();
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		var prop = type.GetProperty(name, flags);
		if (prop != null && prop.GetIndexParameters().Length == 0)
		{
			try { return prop.GetValue(owner); } catch { }
		}
		var field = type.GetField(name, flags);
		if (field != null)
		{
			try { return field.GetValue(owner); } catch { }
		}
		return null;
	}

	private static object InvokeNoArg(object owner, string name)
	{
		if (owner == null || string.IsNullOrEmpty(name))
			return null;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		var method = owner.GetType().GetMethod(name, flags, null, Type.EmptyTypes, null);
		if (method == null)
			return null;
		try { return method.Invoke(owner, null); } catch { return null; }
	}

	private static void LogDecision(string decision, GameObject root, string viewSid, string attackerSid, string targetSid, object round)
	{
		if (!Homm3DiagnosticFlags.IsEnabled("homm3_battle_attack_facing_diag.flag"))
			return;
		if (_loggedDecision >= 80)
			return;
		_loggedDecision++;
		Plugin.LogSource?.LogInfo(
			"Homm3 battle attack facing: "
			+ decision
			+ " root='"
			+ (root ? root.name : "?")
			+ "' view="
			+ (viewSid ?? "?")
			+ " attacker="
			+ (attackerSid ?? "?")
			+ " target="
			+ (targetSid ?? "?")
			+ " round="
			+ (round ?? "?")
			+ ".");
	}
}
