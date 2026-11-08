using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using Hex.Configs;
using Hex.GameHub.UICommon;
using Hex.Map;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.InteropTypes;
using Il2CppInterop.Runtime.Runtime;

namespace OfflineUnlockMod;

/// <summary>
/// Golden Era interop renames semantic members such as <c>sid</c> to generated names like
/// <c>field_Public_String_0</c>. Helpers here resolve both shapes at runtime so one build works on
/// legacy playtest and Golden Era installs.
/// </summary>
internal static class DeobfInteropCompat
{
	public static T TryReadNativeObjectMember<T>(object owner, params string[] names)
		where T : Il2CppObjectBase
	{
		if (names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var value = TryReadNativeObjectMember(owner, names[i], typeof(T)) as T;
			if (value != null)
				return value;
		}
		return null;
	}

	public static Il2CppObjectBase TryReadNativeObjectMember(object owner, Type expectedType, params string[] names)
	{
		if (expectedType == null || !typeof(Il2CppObjectBase).IsAssignableFrom(expectedType) || names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var value = TryReadNativeObjectMember(owner, names[i], expectedType) as Il2CppObjectBase;
			if (value != null)
				return value;
		}
		return null;
	}

	internal static bool TryReadNativeObjectFieldDeclared(
		object owner,
		Type declaringType,
		Type expectedType,
		GameSymbols.FieldSymbol member,
		out Il2CppObjectBase value,
		out string failure)
	{
		// Read through one owner's native field metadata; do not recover through guessed member aliases.
		value = null;
		failure = null;
		if (owner == null || declaringType == null || expectedType == null)
		{
			failure = "invalid-arguments";
			return false;
		}
		if (!declaringType.IsInstanceOfType(owner))
		{
			failure = "owner-type-mismatch";
			return false;
		}
		if (owner is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero)
		{
			failure = "owner-native-pointer-missing";
			return false;
		}
		if (string.IsNullOrWhiteSpace(member.NativeFieldInfoName) || string.IsNullOrWhiteSpace(member.FieldName) ||
		    !string.Equals(member.NativeFieldInfoName, "NativeFieldInfoPtr_" + member.FieldName, StringComparison.Ordinal))
		{
			failure = "field-symbol-pointer-name-mismatch";
			return false;
		}
		if (!typeof(Il2CppObjectBase).IsAssignableFrom(expectedType))
		{
			failure = "expected-type-is-not-an-il2cpp-reference";
			return false;
		}

		const BindingFlags declaredInstance = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly;
		var properties = declaringType.GetProperties(declaredInstance)
			.Where(property => string.Equals(property.Name, member.FieldName, StringComparison.Ordinal))
			.ToArray();
		var instanceFields = declaringType.GetFields(declaredInstance)
			.Where(field => string.Equals(field.Name, member.FieldName, StringComparison.Ordinal))
			.ToArray();
		var metadataType = properties.Length == 1 && instanceFields.Length == 0
			? properties[0].PropertyType
			: instanceFields.Length == 1 && properties.Length == 0
				? instanceFields[0].FieldType
				: null;
		if (metadataType == null || metadataType != expectedType)
		{
			failure = "interop-reference-type-not-declared-on-owner";
			return false;
		}

		TryInitializeIl2CppType(declaringType);
		const BindingFlags declaredStatic = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.DeclaredOnly;
		var pointerField = declaringType.GetField(member.NativeFieldInfoName, declaredStatic);
		if (pointerField == null || pointerField.FieldType != typeof(IntPtr))
		{
			failure = "native-field-info-pointer-not-declared-on-owner";
			return false;
		}

		IntPtr fieldPointer;
		try
		{
			fieldPointer = (IntPtr)pointerField.GetValue(null);
		}
		catch (Exception ex)
		{
			failure = "native-field-info-pointer-read-failed:" + ex.GetType().Name;
			return false;
		}
		if (fieldPointer == IntPtr.Zero)
		{
			failure = "native-field-info-pointer-zero";
			return false;
		}
		if (!NativeFieldClassAssignableToExpectedType(fieldPointer, expectedType, out failure))
		{
			failure ??= "native-field-reference-type-mismatch";
			return false;
		}

		try
		{
			var objectPointer = IL2CPP.Il2CppObjectBaseToPtrNotNull(il2Cpp);
			var offset = IL2CPP.il2cpp_field_get_offset(fieldPointer);
			if (offset > int.MaxValue)
			{
				failure = "native-field-offset-invalid";
				return false;
			}
			var valuePointer = Marshal.ReadIntPtr(IntPtr.Add(objectPointer, (int)offset));
			if (valuePointer == IntPtr.Zero)
			{
				failure = "native-field-value-null";
				return false;
			}

			value = CreateIl2CppObjectWrapper(valuePointer, expectedType) as Il2CppObjectBase;
			if (value == null || !expectedType.IsInstanceOfType(value))
			{
				value = null;
				failure = "interop-wrapper-construction-failed";
				return false;
			}
			return true;
		}
		catch (Exception ex)
		{
			failure = "native-field-read-failed:" + ex.GetType().Name;
			return false;
		}
	}

	public static string TryReadNativeStringMember(object owner, params string[] names)
	{
		if (names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var value = TryReadNativeStringMember(owner, names[i]);
			if (!string.IsNullOrWhiteSpace(value))
				return value;
		}
		return null;
	}

	public static bool TryGetMapObjectInfoSid(MapObjectInfo info, out string sid)
	{
		if (!TryGetMemberValue(info, out var value, "sid", "field_Public_String_0"))
		{
			sid = null;
			return false;
		}
		sid = value as string;
		return !string.IsNullOrWhiteSpace(sid);
	}

	public static string GetMapObjectInfoSid(MapObjectInfo info)
	{
		return TryGetMapObjectInfoSid(info, out var sid) ? sid : null;
	}

	public static int GetMapObjectInfoId(MapObjectInfo info)
	{
		return GetIntMember(info, "id", "field_Public_Int32_0");
	}

	public static void SetMapObjectInfoSid(ref MapObjectInfo info, string sid)
	{
		if (TrySetStringMember(ref info, sid, "sid", "field_Public_String_0"))
			return;
		throw new MissingMemberException(typeof(MapObjectInfo).FullName, "sid/field_Public_String_0");
	}

	public static string GetFractionLobbyAssetSid(FractionLobbyAsset asset)
	{
		if (!TryGetMemberValue(asset, out var value, "sid", "field_Public_String_0"))
			throw new MissingMemberException(typeof(FractionLobbyAsset).FullName, "sid/field_Public_String_0");
		return value as string;
	}

	public static void SetFractionLobbyAssetSid(FractionLobbyAsset asset, string sid)
	{
		if (TrySetStringMember(asset, sid, "sid", "field_Public_String_0"))
			return;
		throw new MissingMemberException(typeof(FractionLobbyAsset).FullName, "sid/field_Public_String_0");
	}

	public static void SetFractionLobbyAssetCard(FractionLobbyAsset asset, UnityEngine.Sprite card)
	{
		if (TrySetSpriteMember(asset, card, "card", "field_Public_Sprite_0"))
			return;
		throw new MissingMemberException(typeof(FractionLobbyAsset).FullName, "card/field_Public_Sprite_0");
	}

	public static UnityEngine.Sprite GetFractionLobbyAssetCard(FractionLobbyAsset asset)
	{
		return GetSpriteMember(asset, "card", "field_Public_Sprite_0");
	}

	/// <summary>
	/// Read <see cref="ConfigElementBase{T}.id"/> without calling the interop <c>id</c> property
	/// (that getter has AV'd on Golden Era during mid-init). Prefer the native IL2CPP field named
	/// <c>id</c>. Do not treat derived <c>field_Public_String_0</c> as the id — on
	/// <c>ObjectConfig</c> that slot is often <c>tag</c> (e.g. <c>Artifact</c>), which is a
	/// category token, not the catalog SID.
	/// </summary>
	public static string GetConfigElementId(object config)
	{
		if (config == null)
			return null;
		return TryReadConfigElementId(config, out var id) ? id : null;
	}

	public static bool TryGetConfigElementId(object config, out string id)
	{
		return TryReadNativeConfigElementBaseId(config, out id, out _);
	}

	public static bool TrySetConfigElementId(object config, string id)
	{
		if (config == null)
			return false;
		for (var cur = config.GetType(); cur != null && cur != typeof(object); cur = cur.BaseType)
		{
			if (!LooksLikeConfigElementBaseType(cur))
				continue;
			for (var i = 0; i < ConfigElementIdFieldNames.Length; i++)
			{
				if (TryWriteDeclaredStringField(cur, config, ConfigElementIdFieldNames[i], id))
					return true;
			}
		}
		return TryWriteDeclaredStringField(config.GetType(), config, "id", id)
		       || TrySetStringMember(config, id, "field_Public_String_0", "field_Private_String_0", "id");
	}

	private static bool TryWriteDeclaredStringField(Type declaringType, object target, string fieldName, string value)
	{
		if (declaringType == null || target == null || string.IsNullOrWhiteSpace(fieldName))
			return false;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		FieldInfo field = null;
		try { field = declaringType.GetField(fieldName, flags); }
		catch { return false; }
		if (field == null || field.FieldType != typeof(string))
			return false;
		try
		{
			field.SetValue(target, value);
			return true;
		}
		catch
		{
			return false;
		}
	}

	public static string GetUnitViewConfigMapMesh(UnitViewConfig config)
	{
		if (config == null)
			return null;
		var viaReflection = GetStringMember(config, "mapMesh");
		if (!string.IsNullOrEmpty(viaReflection))
			return viaReflection;
		try
		{
			return config.mapMesh;
		}
		catch (MissingMethodException)
		{
			return null;
		}
	}

	public static void SetUnitViewConfigMapMesh(UnitViewConfig config, string mapMesh)
	{
		if (config == null)
			return;
		if (TrySetStringMember(config, mapMesh, "mapMesh"))
			return;
		try
		{
			config.mapMesh = mapMesh;
		}
		catch (MissingMethodException)
		{
			throw new MissingMemberException(typeof(UnitViewConfig).FullName, "mapMesh");
		}
	}

	public static bool TryGetUnitViewConfigMoveSpeed(UnitViewConfig config, out float moveSpeed)
	{
		moveSpeed = 0f;
		if (config == null)
			return false;
		try
		{
			moveSpeed = config.moveSpeed;
			return true;
		}
		catch (MissingMethodException)
		{
		}
		if (TryGetMemberValue(config, out var boxed, "moveSpeed") && TryCoerceSingle(boxed, out moveSpeed))
			return true;
		return TryReadNativeFloat(config, "moveSpeed", out moveSpeed);
	}

	public static bool TrySetUnitViewConfigMoveSpeed(UnitViewConfig config, float moveSpeed)
	{
		if (config == null)
			return false;
		try
		{
			config.moveSpeed = moveSpeed;
			return true;
		}
		catch (MissingMethodException)
		{
		}
		if (TrySetMemberValue(config, moveSpeed, "moveSpeed"))
			return true;
		return TryWriteNativeFloat(config, "moveSpeed", moveSpeed);
	}

	private static bool TryCoerceSingle(object boxed, out float value)
	{
		value = 0f;
		if (boxed == null)
			return false;
		if (boxed is float f)
		{
			value = f;
			return true;
		}
		if (boxed is double d)
		{
			value = (float)d;
			return true;
		}
		try
		{
			value = Convert.ToSingle(boxed, CultureInfo.InvariantCulture);
			return !float.IsNaN(value) && !float.IsInfinity(value);
		}
		catch
		{
			return false;
		}
	}

	private static bool TryReadNativeFloat(Il2CppObjectBase owner, string fieldName, out float value)
	{
		value = 0f;
		if (!TryResolveNativeFloatAddress(owner, fieldName, out var address))
			return false;
		var bytes = new byte[4];
		Marshal.Copy(address, bytes, 0, 4);
		value = BitConverter.ToSingle(bytes, 0);
		return true;
	}

	private static bool TryWriteNativeFloat(Il2CppObjectBase owner, string fieldName, float value)
	{
		if (!TryResolveNativeFloatAddress(owner, fieldName, out var address))
			return false;
		Marshal.Copy(BitConverter.GetBytes(value), 0, address, 4);
		return true;
	}

	private static bool TryResolveNativeFloatAddress(Il2CppObjectBase owner, string fieldName, out IntPtr address)
	{
		address = IntPtr.Zero;
		if (owner == null || owner.Pointer == IntPtr.Zero || string.IsNullOrWhiteSpace(fieldName))
			return false;
		var fieldPtr = ResolveNativeFieldPointer(owner.GetType(), fieldName);
		if (fieldPtr == IntPtr.Zero)
		{
			try
			{
				fieldPtr = IL2CPP.GetIl2CppField(Il2CppClassPointerStore<UnitViewConfig>.NativeClassPtr, fieldName);
			}
			catch
			{
				fieldPtr = IntPtr.Zero;
			}
		}
		if (fieldPtr == IntPtr.Zero)
			return false;
		var objectPtr = IL2CPP.Il2CppObjectBaseToPtrNotNull(owner);
		address = IntPtr.Add(objectPtr, (int)IL2CPP.il2cpp_field_get_offset(fieldPtr));
		return address != IntPtr.Zero;
	}

	public static string GetHeroConfigId(object heroConfig) => GetConfigElementId(heroConfig);

	public static string GetHeroConfigIcon(object heroConfig)
	{
		return GetStringMember(heroConfig, "icon", "field_Public_String_1", "field_Public_String_2", "field_Public_String_3");
	}

	public static string GetObjCityConfigFraction(object cityConfig)
	{
		return GetStringMember(cityConfig, "fraction", "field_Public_String_1", "field_Public_String_2", "field_Public_String_3");
	}

	public static bool TryGetPlacedMapObjectSid(object placed, out string sid)
	{
		sid = null;
		if (placed == null)
			return false;
		if (TryGetMemberValue(placed, out var value,
			    "bvno", "bvoy", "sid", "objectSid", "id", "configSid",
			    "field_Private_String_0", "field_Public_String_0", "field_Private_String_1",
			    "<bvno>k__BackingField", "_bvno_k__BackingField"))
		{
			sid = value as string;
			if (!string.IsNullOrWhiteSpace(sid))
				return true;
		}
		if (TryGetAnyStringMember(placed, out sid)
		    && (sid.IndexOf("homm3_", StringComparison.OrdinalIgnoreCase) >= 0
		        || sid.IndexOf("_city", StringComparison.OrdinalIgnoreCase) >= 0
		        || sid.IndexOf("city-spawner", StringComparison.OrdinalIgnoreCase) >= 0
		        || sid.IndexOf("random-city", StringComparison.OrdinalIgnoreCase) >= 0))
			return true;
		sid = null;
		return false;
	}

	public static bool TryGetMapObjectMetaConfig(object meta, out object config)
	{
		config = null;
		if (meta == null)
			return false;
		if (meta is MapObjectInfo info && TryGetMapObjectInfoSid(info, out var infoSid) && !string.IsNullOrWhiteSpace(infoSid))
		{
			// MapObjectInfo carries sid directly; caller resolves city billboard from sid.
			return false;
		}
		if (TryGetMemberValue(meta, out config,
			"bvnz", "bvpj", "config",
			"field_Public_ObjectConfig_0", "field_Private_ObjectConfig_0",
			"<bvnz>k__BackingField", "_bvnz_k__BackingField"))
			return config != null;
		config = TryFindNestedMemberByTypeName(meta, "ObjectConfig");
		return config != null;
	}

	public static string GetUnitPortraitSid(object unitOrConfig)
	{
		if (unitOrConfig == null)
			return null;
		var direct = GetStringMember(unitOrConfig, "sid", "configSid", "unitSid", "field_Public_String_0", "field_Private_String_0");
		if (!string.IsNullOrWhiteSpace(direct))
			return direct.Trim();
		return GetConfigElementId(unitOrConfig);
	}

	public static string GetStringMember(object target, params string[] names)
	{
		return TryGetMemberValue(target, out var value, names) ? value as string : null;
	}

	public static UnityEngine.UI.Image GetImageMember(object target, params string[] names)
	{
		return TryGetMemberValue(target, out var value, names) ? value as UnityEngine.UI.Image : null;
	}

	public static object TryFindNestedMemberByTypeName(object owner, string typeNameFragment, int maxDepth = 2)
	{
		if (owner == null || string.IsNullOrWhiteSpace(typeNameFragment))
			return null;
		return TryFindNestedMemberByTypeName(owner, typeNameFragment, new HashSet<int>(), 0, maxDepth);
	}

	public static string GetSessionHeroPortraitKey(object heroOrWrapper)
	{
		return ResolveSessionHeroPortraitKey(heroOrWrapper, new HashSet<int>(), 0, fieldOnly: false);
	}

	public static string GetSessionHeroPortraitKeyFieldOnly(object heroOrWrapper)
	{
		return ResolveSessionHeroPortraitKey(heroOrWrapper, new HashSet<int>(), 0, fieldOnly: true);
	}

	private static string ResolveSessionHeroPortraitKey(object current, HashSet<int> seen, int depth, bool fieldOnly)
	{
		if (current == null || depth > 5)
			return null;
		if ((fieldOnly ? TryNormalizeHeroPortraitKeyFieldOnly(current, out var directKey) : TryNormalizeHeroPortraitKey(current, out directKey)))
			return directKey;
		if (!seen.Add(System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(current)))
			return null;

		var groups = new[]
		{
			GameSymbols.ImportVisuals.SessionHeroConfigFields,
			GameSymbols.ImportVisuals.SessionHeroWrapperHeroFields,
			GameSymbols.ImportVisuals.SessionLogicHeroDataFields
		};
		for (var i = 0; i < groups.Length; i++)
		{
			var names = groups[i];
			if (names == null)
				continue;
			for (var j = 0; j < names.Length; j++)
			{
				if (!TryGetFieldValue(current, out var nested, names[j]) || nested == null)
					continue;
				var nestedKey = ResolveSessionHeroPortraitKey(nested, seen, depth + 1, fieldOnly);
				if (!string.IsNullOrWhiteSpace(nestedKey))
					return nestedKey;
			}
		}

		return null;
	}

	private static bool TryGetFieldValue(object target, out object value, params string[] names)
	{
		value = null;
		if (target == null || names == null || names.Length == 0)
			return false;
		var type = target.GetType();
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			for (var cur = type; cur != null && cur != typeof(object); cur = cur.BaseType)
			{
				const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
				FieldInfo field = null;
				try { field = cur.GetField(name, flags); }
				catch { field = null; }
				if (field == null)
					continue;
				try
				{
					value = field.GetValue(target);
					if (value != null)
						return true;
				}
				catch { }
			}
		}
		return false;
	}

	private static bool TryNormalizeHeroPortraitKeyFieldOnly(object heroOrConfig, out string portraitKey)
	{
		portraitKey = null;
		if (heroOrConfig == null)
			return false;
		if (heroOrConfig is string direct && Homm3CustomFactionRegistry.IsCustomHeroSid(direct))
			return Homm3CustomFactionRegistry.TryNormalizeHeroPortraitKey(direct.Trim(), out portraitKey);
		var icon = GetStringField(heroOrConfig, "icon", "field_Public_String_1", "field_Public_String_2", "field_Public_String_3");
		var id = GetConfigElementId(heroOrConfig)
		         ?? GetStringField(heroOrConfig, "configSid", "sid", "field_Public_String_0", "field_Private_String_0", "field_Public_String_1");
		return Homm3CustomFactionRegistry.TryNormalizeHeroPortraitKey(icon ?? id, out portraitKey);
	}

	private static string GetStringField(object target, params string[] names)
	{
		return TryGetFieldValue(target, out var value, names) ? value as string : null;
	}

	public static bool TryGetAnyStringMember(object target, out string value, params string[] names)
	{
		value = GetStringMember(target, names);
		if (!string.IsNullOrWhiteSpace(value))
		{
			value = value.Trim();
			return true;
		}
		if (target == null)
			return false;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		for (var type = target.GetType(); type != null; type = type.BaseType)
		{
			foreach (var field in type.GetFields(flags))
			{
				if (field.FieldType != typeof(string))
					continue;
				try
				{
					var candidate = field.GetValue(target) as string;
					if (!string.IsNullOrWhiteSpace(candidate))
					{
						value = candidate.Trim();
						return true;
					}
				}
				catch { }
			}
		}
		return false;
	}

	private static bool TryNormalizeHeroPortraitKey(object heroOrConfig, out string portraitKey)
	{
		portraitKey = null;
		if (heroOrConfig == null)
			return false;
		if (heroOrConfig is string direct && Homm3CustomFactionRegistry.IsCustomHeroSid(direct))
		{
			return Homm3CustomFactionRegistry.TryNormalizeHeroPortraitKey(direct.Trim(), out portraitKey);
		}
		var icon = GetHeroConfigIcon(heroOrConfig);
		var id = GetHeroConfigId(heroOrConfig)
		         ?? GetStringMember(heroOrConfig, "configSid", "sid", "field_Public_String_0", "field_Private_String_0", "field_Public_String_1");
		return Homm3CustomFactionRegistry.TryNormalizeHeroPortraitKey(icon ?? id, out portraitKey);
	}

	private static object TryFindNestedMemberByTypeName(object owner, string typeNameFragment, HashSet<int> seen, int depth, int maxDepth)
	{
		if (owner == null || depth > maxDepth || !seen.Add(System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(owner)))
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		for (var type = owner.GetType(); type != null; type = type.BaseType)
		{
			foreach (var field in type.GetFields(flags))
			{
				var fieldType = field.FieldType;
				if (fieldType == null)
					continue;
				object value = null;
				try { value = field.GetValue(owner); } catch { }
				if (value == null)
					continue;
				if (fieldType.Name.IndexOf(typeNameFragment, StringComparison.Ordinal) >= 0
				    || (fieldType.FullName?.IndexOf(typeNameFragment, StringComparison.Ordinal) ?? -1) >= 0)
					return value;
				var nested = TryFindNestedMemberByTypeName(value, typeNameFragment, seen, depth + 1, maxDepth);
				if (nested != null)
					return nested;
			}
		}
		return null;
	}

	public static int GetIntMember(object target, params string[] names)
	{
		if (!TryGetMemberValue(target, out var value, names) || value == null)
			return 0;
		try
		{
			return Convert.ToInt32(value);
		}
		catch
		{
			return 0;
		}
	}

	public static bool TryGetObjectMember(object target, out object value, params string[] names)
	{
		return TryGetMemberValue(target, out value, names);
	}

	public static bool TryGetSingleMember(object target, out float value, params string[] names)
	{
		value = 0f;
		return TryGetMemberValue(target, out var boxed, names) && TryCoerceSingle(boxed, out value);
	}

	public static bool TryGetInt32Member(object target, out int value, params string[] names)
	{
		value = 0;
		if (!TryGetMemberValue(target, out var boxed, names) || boxed == null)
			return false;
		try
		{
			value = Convert.ToInt32(boxed, CultureInfo.InvariantCulture);
			return true;
		}
		catch
		{
			return false;
		}
	}

	/// <summary>Reads the first present static field/property among <paramref name="names"/>.</summary>
	public static bool TryGetStaticMember(Type type, out object value, params string[] names)
	{
		value = null;
		if (type == null || names == null)
			return false;
		const BindingFlags flags = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			try
			{
				var property = type.GetProperty(name, flags);
				if (property != null && property.GetIndexParameters().Length == 0)
				{
					value = property.GetValue(null);
					return true;
				}
				var field = type.GetField(name, flags);
				if (field != null)
				{
					value = field.GetValue(null);
					return true;
				}
			}
			catch
			{
				value = null;
			}
		}
		return false;
	}

	public static UnityEngine.Sprite GetSpriteMember(object target, params string[] names)
	{
		return TryGetMemberValue(target, out var value, names) ? value as UnityEngine.Sprite : null;
	}

	public static bool TrySetStringMember(object target, string value, params string[] names)
	{
		if (TryWriteNativeStringMember(target, value, names))
			return true;
		return TrySetMemberValue(target, value, names);
	}

	/// <summary>
	/// Write a string field through IL2CPP native field pointers. Prefer this over managed
	/// property setters on Golden Era — semantic getters/setters like FractionConfig.city can
	/// throw MissingMethodException even when NativeFieldInfoPtr_city is present.
	/// </summary>
	public static bool TryWriteNativeStringMember(object owner, string value, params string[] names)
	{
		if (owner == null || names == null || owner is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero)
			return false;
		for (var i = 0; i < names.Length; i++)
		{
			if (TryWriteNativeStringMember(il2Cpp, names[i], value))
				return true;
		}
		return false;
	}

	private static bool TryWriteNativeStringMember(Il2CppObjectBase il2Cpp, string name, string value)
	{
		if (il2Cpp == null || string.IsNullOrWhiteSpace(name))
			return false;
		for (var current = il2Cpp.GetType(); current != null; current = current.BaseType)
		{
			var fieldPtr = ResolveNativeFieldPointer(current, name);
			if (fieldPtr == IntPtr.Zero || !NativeFieldTypeIsString(fieldPtr))
				continue;
			try
			{
				var objectPtr = IL2CPP.Il2CppObjectBaseToPtrNotNull(il2Cpp);
				var targetAddress = IntPtr.Add(objectPtr, (int)IL2CPP.il2cpp_field_get_offset(fieldPtr));
				IL2CPP.il2cpp_gc_wbarrier_set_field(
					objectPtr,
					targetAddress,
					IL2CPP.ManagedStringToIl2Cpp(value));
				return true;
			}
			catch
			{
			}
		}
		return false;
	}

	public static bool TrySetSpriteMember(object target, UnityEngine.Sprite value, params string[] names)
	{
		return TrySetMemberValue(target, value, names);
	}

	public static bool TrySetStringMember(ref MapObjectInfo target, string value, params string[] names)
	{
		object boxed = target;
		if (!TrySetMemberValue(boxed, value, names))
			return false;
		target = (MapObjectInfo)boxed;
		return true;
	}

	private static bool TryGetMemberValue(object target, out object value, params string[] names)
	{
		value = null;
		if (target == null || names == null || names.Length == 0)
			return false;

		var type = target.GetType();
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			if (TryReadMember(type, target, name, out value))
				return true;
		}

		return false;
	}

	private static bool TrySetMemberValue(object target, object value, params string[] names)
	{
		if (target == null || names == null || names.Length == 0)
			return false;

		var type = target.GetType();
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			if (TryWriteMember(type, target, name, value))
				return true;
		}

		return false;
	}

	private static readonly string[] ConfigElementIdFieldNames =
	{
		"field_Public_String_0",
		"field_Private_String_0",
		"prop_String_0",
		"_id",
		"<id>k__BackingField"
	};

	private static object TryReadNativeObjectMember(object owner, string name, Type expectedType)
	{
		if (owner == null || string.IsNullOrWhiteSpace(name) || expectedType == null)
			return null;
		if (owner is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero)
			return null;
		for (var current = owner.GetType(); current != null; current = current.BaseType)
		{
			var fieldPtr = ResolveNativeFieldPointer(current, name);
			if (fieldPtr == IntPtr.Zero || !NativeFieldTypeAssignableTo(fieldPtr, expectedType))
				continue;
			try
			{
				var objectPtr = IL2CPP.Il2CppObjectBaseToPtrNotNull(il2Cpp);
				var valuePtr = Marshal.ReadIntPtr(IntPtr.Add(objectPtr, (int)IL2CPP.il2cpp_field_get_offset(fieldPtr)));
				return valuePtr == IntPtr.Zero ? null : CreateIl2CppObjectWrapper(valuePtr, expectedType);
			}
			catch
			{
			}
		}
		return null;
	}

	private static string TryReadNativeStringMember(object owner, string name)
	{
		if (owner == null || string.IsNullOrWhiteSpace(name))
			return null;
		if (owner is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero)
			return null;
		for (var current = owner.GetType(); current != null; current = current.BaseType)
		{
			var fieldPtr = ResolveNativeFieldPointer(current, name);
			if (fieldPtr == IntPtr.Zero || !NativeFieldTypeIsString(fieldPtr))
				continue;
			try
			{
				var objectPtr = IL2CPP.Il2CppObjectBaseToPtrNotNull(il2Cpp);
				var valuePtr = Marshal.ReadIntPtr(IntPtr.Add(objectPtr, (int)IL2CPP.il2cpp_field_get_offset(fieldPtr)));
				if (valuePtr == IntPtr.Zero)
					continue;
				var text = IL2CPP.Il2CppStringToManaged(valuePtr);
				if (!string.IsNullOrWhiteSpace(text))
					return text.Trim();
			}
			catch
			{
			}
		}
		return null;
	}

	private static string TryReadNativeStringMember(object owner, Type declaringType, string name)
	{
		if (owner == null || declaringType == null || string.IsNullOrWhiteSpace(name)
		    || !declaringType.IsAssignableFrom(owner.GetType()))
			return null;
		if (owner is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero)
			return null;

		var fieldPtr = ResolveNativeFieldPointerDeclared(declaringType, name);
		if (fieldPtr == IntPtr.Zero || !NativeFieldTypeIsString(fieldPtr))
			return null;
		try
		{
			var objectPtr = IL2CPP.Il2CppObjectBaseToPtrNotNull(il2Cpp);
			var valuePtr = Marshal.ReadIntPtr(IntPtr.Add(objectPtr, (int)IL2CPP.il2cpp_field_get_offset(fieldPtr)));
			if (valuePtr == IntPtr.Zero)
				return null;
			var text = IL2CPP.Il2CppStringToManaged(valuePtr);
			return string.IsNullOrWhiteSpace(text) ? null : text.Trim();
		}
		catch
		{
			return null;
		}
	}

	private static IntPtr ResolveNativeFieldPointer(Type ownerType, string logicalName)
	{
		if (ownerType == null || string.IsNullOrWhiteSpace(logicalName))
			return IntPtr.Zero;
		TryInitializeIl2CppType(ownerType);
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static;
		for (var current = ownerType; current != null; current = current.BaseType)
		{
			foreach (var candidate in ExpandNativeFieldCandidates(logicalName))
			{
				try
				{
					var managedField = current.GetField(candidate, flags);
					if (managedField != null && managedField.FieldType == typeof(IntPtr))
					{
						var ptr = (IntPtr)managedField.GetValue(null);
						if (ptr != IntPtr.Zero)
							return ptr;
					}
				}
				catch
				{
				}
			}
		}
		return IntPtr.Zero;
	}

	private static IntPtr ResolveNativeFieldPointerDeclared(Type ownerType, string logicalName)
	{
		if (ownerType == null || string.IsNullOrWhiteSpace(logicalName))
			return IntPtr.Zero;
		TryInitializeIl2CppType(ownerType);
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.DeclaredOnly;
		foreach (var candidate in ExpandNativeFieldCandidates(logicalName))
		{
			try
			{
				var managedField = ownerType.GetField(candidate, flags);
				if (managedField != null && managedField.FieldType == typeof(IntPtr))
				{
					var ptr = (IntPtr)managedField.GetValue(null);
					if (ptr != IntPtr.Zero)
						return ptr;
				}
			}
			catch
			{
			}
		}
		return IntPtr.Zero;
	}

	private static IEnumerable<string> ExpandNativeFieldCandidates(string logicalName)
	{
		yield return "NativeFieldInfoPtr_" + logicalName;
		if (logicalName.StartsWith("<", StringComparison.Ordinal) && logicalName.EndsWith(">k__BackingField", StringComparison.Ordinal))
		{
			var end = logicalName.IndexOf('>', StringComparison.Ordinal);
			if (end > 1)
			{
				var inner = logicalName.Substring(1, end - 1);
				yield return "NativeFieldInfoPtr__" + inner + "_k__BackingField";
				yield return "NativeFieldInfoPtr_" + inner;
			}
		}
		if (logicalName.StartsWith("_", StringComparison.Ordinal) && logicalName.EndsWith("_k__BackingField", StringComparison.Ordinal))
		{
			var inner = logicalName.Substring(1, logicalName.Length - "_k__BackingField".Length - 1);
			if (!string.IsNullOrWhiteSpace(inner))
			{
				yield return "NativeFieldInfoPtr__" + inner + "_k__BackingField";
				yield return "NativeFieldInfoPtr_" + inner;
			}
		}
	}

	private static bool NativeFieldTypeIsString(IntPtr fieldPtr)
	{
		var fieldTypeName = ResolveNativeFieldTypeName(fieldPtr);
		var clean = CleanIl2CppTypeName(fieldTypeName);
		return string.Equals(clean, "System.String", StringComparison.Ordinal)
		       || string.Equals(clean, "String", StringComparison.Ordinal)
		       || string.Equals(clean, "Il2CppSystem.String", StringComparison.Ordinal);
	}

	private static bool NativeFieldClassAssignableToExpectedType(IntPtr fieldPtr, Type expectedType, out string failure)
	{
		// Generated interop type names can differ from the live IL2CPP alias; runtime preview behavior still needs testing.
		failure = null;
		if (fieldPtr == IntPtr.Zero || expectedType == null)
		{
			failure = "native-field-class-check-invalid-arguments";
			return false;
		}

		try
		{
			var nativeFieldType = IL2CPP.il2cpp_field_get_type(fieldPtr);
			if (nativeFieldType == IntPtr.Zero)
			{
				failure = "native-field-type-pointer-zero";
				return false;
			}

			var nativeFieldClass = IL2CPP.il2cpp_class_from_il2cpp_type(nativeFieldType);
			if (nativeFieldClass == IntPtr.Zero)
			{
				failure = "native-field-class-pointer-zero";
				return false;
			}

			if (!TryGetNativeClassPointer(expectedType, out var expectedClass, out failure))
				return false;
			if (!IL2CPP.il2cpp_class_is_assignable_from(expectedClass, nativeFieldClass))
			{
				failure = "native-field-reference-type-mismatch";
				return false;
			}

			return true;
		}
		catch (Exception ex)
		{
			failure = "native-field-class-check-failed:" + ex.GetType().Name;
			return false;
		}
	}

	private static bool TryGetNativeClassPointer(Type managedType, out IntPtr nativeClass, out string failure)
	{
		nativeClass = IntPtr.Zero;
		failure = null;
		if (managedType == null || !typeof(Il2CppObjectBase).IsAssignableFrom(managedType))
		{
			failure = "expected-type-is-not-an-il2cpp-reference";
			return false;
		}

		try
		{
			var classPointerStore = typeof(Il2CppClassPointerStore<>).MakeGenericType(managedType);
			RuntimeHelpers.RunClassConstructor(classPointerStore.TypeHandle);
			var classPointerField = classPointerStore.GetField(
				"NativeClassPtr",
				BindingFlags.Public | BindingFlags.Static);
			if (classPointerField == null || classPointerField.FieldType != typeof(IntPtr))
			{
				failure = "expected-native-class-pointer-not-declared";
				return false;
			}

			nativeClass = (IntPtr)classPointerField.GetValue(null);
			if (nativeClass == IntPtr.Zero)
			{
				failure = "expected-native-class-pointer-zero";
				return false;
			}

			return true;
		}
		catch (Exception ex)
		{
			nativeClass = IntPtr.Zero;
			failure = "expected-native-class-pointer-read-failed:" + ex.GetType().Name;
			return false;
		}
	}

	private static bool NativeFieldTypeAssignableTo(IntPtr fieldPtr, Type expectedType)
	{
		var clean = CleanIl2CppTypeName(ResolveNativeFieldTypeName(fieldPtr));
		return !string.IsNullOrWhiteSpace(clean)
		       && expectedType != null
		       && (string.Equals(clean, expectedType.FullName, StringComparison.Ordinal)
		           || string.Equals(clean, expectedType.Name, StringComparison.Ordinal)
		           || NativeTypeNameMatchesExpectedAlias(clean, expectedType));
	}

	private static bool NativeTypeNameMatchesExpectedAlias(string nativeTypeName, Type expectedType)
	{
		if (string.IsNullOrWhiteSpace(nativeTypeName) || expectedType == null)
			return false;
		var aliases = GetNativeTypeAliases(expectedType);
		for (var i = 0; i < aliases.Length; i++)
		{
			var alias = aliases[i];
			if (string.IsNullOrWhiteSpace(alias))
				continue;
			if (string.Equals(nativeTypeName, alias, StringComparison.Ordinal)
			    || nativeTypeName.EndsWith("." + alias, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static string[] GetNativeTypeAliases(Type expectedType)
	{
		return GameInteropTypes.GetNativeTypeAliases(expectedType);
	}

	private static string ResolveNativeFieldTypeName(IntPtr fieldPtr)
	{
		if (fieldPtr == IntPtr.Zero)
			return null;
		try
		{
			var getType = typeof(IL2CPP).GetMethod("il2cpp_field_get_type", BindingFlags.Public | BindingFlags.Static);
			var getName = typeof(IL2CPP).GetMethod("il2cpp_type_get_name", BindingFlags.Public | BindingFlags.Static);
			if (getType == null || getName == null)
				return null;
			var typePtr = getType.Invoke(null, new object[] { fieldPtr });
			if (typePtr is not IntPtr nativeType || nativeType == IntPtr.Zero)
				return null;
			var nameResult = getName.Invoke(null, new object[] { nativeType });
			return nameResult switch
			{
				string text => text,
				IntPtr ptr when ptr != IntPtr.Zero => Marshal.PtrToStringAnsi(ptr),
				_ => null
			};
		}
		catch
		{
			return null;
		}
	}

	private static string CleanIl2CppTypeName(string name)
	{
		if (string.IsNullOrWhiteSpace(name))
			return "";
		var value = name.Trim();
		if (value.StartsWith("class ", StringComparison.Ordinal))
			value = value.Substring("class ".Length);
		else if (value.StartsWith("struct ", StringComparison.Ordinal))
			value = value.Substring("struct ".Length);
		return value.TrimEnd('*', '&').Trim();
	}

	private static object CreateIl2CppObjectWrapper(IntPtr valuePtr, Type expectedType)
	{
		if (valuePtr == IntPtr.Zero || expectedType == null || !typeof(Il2CppObjectBase).IsAssignableFrom(expectedType))
			return null;
		try
		{
			foreach (var method in typeof(Il2CppObjectPool).GetMethods(BindingFlags.Public | BindingFlags.Static))
			{
				if (!string.Equals(method.Name, "Get", StringComparison.Ordinal) || !method.IsGenericMethodDefinition)
					continue;
				var parameters = method.GetParameters();
				if (parameters.Length == 1 && parameters[0].ParameterType == typeof(IntPtr))
					return method.MakeGenericMethod(expectedType).Invoke(null, new object[] { valuePtr });
			}
		}
		catch
		{
		}
		return null;
	}

	private static void TryInitializeIl2CppType(Type managedType)
	{
		if (managedType == null)
			return;
		try
		{
			RuntimeHelpers.RunClassConstructor(managedType.TypeHandle);
		}
		catch
		{
		}
	}

	private static bool TryReadNativeConfigElementBaseId(object target, out string id, out string tag)
	{
		id = null;
		tag = null;
		if (target is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero)
			return false;

		// ObjectConfig.tag is a native-only rejection guard; ID candidates use the exact base owner.
		tag = TryReadNativeStringMember(target, "tag");

		// Scope native reads to ConfigElementBase<string>; current interop names its id field through IDType_0.
		for (var cur = target.GetType(); cur != null && cur != typeof(object); cur = cur.BaseType)
		{
			if (!IsStringConfigElementBaseType(cur))
				continue;
			var aliases = GameSymbols.UnitViewConfig.ConfigElementBaseStringIdNativeFieldAliases;
			for (var i = 0; i < aliases.Length; i++)
			{
				var candidate = TryReadNativeStringMember(target, cur, aliases[i]);
				if (TryAcceptConfigElementId(candidate, tag, out id))
					return true;
			}
		}
		return false;
	}

	private static bool TryReadConfigElementId(object target, out string id)
	{
		id = null;
		if (target == null)
			return false;

		if (TryReadNativeConfigElementBaseId(target, out id, out var tag))
			return true;
		tag ??= TryReadObjectConfigTag(target);

		// Keep legacy reads for mixed callers of GetConfigElementId; map-view routing uses the strict API.
		if (TryAcceptConfigElementId(TryReadNativeStringMember(target, "id"), tag, out id))
			return true;

		for (var cur = target.GetType(); cur != null && cur != typeof(object); cur = cur.BaseType)
		{
			if (!LooksLikeConfigElementBaseType(cur))
				continue;
			for (var i = 0; i < ConfigElementIdFieldNames.Length; i++)
			{
				if (!TryReadDeclaredStringField(cur, target, ConfigElementIdFieldNames[i], out var candidate))
					continue;
				if (TryAcceptConfigElementId(candidate, tag, out id))
					return true;
			}
		}

		for (var cur = target.GetType(); cur != null && cur != typeof(object); cur = cur.BaseType)
		{
			if (!TryReadDeclaredStringField(cur, target, "id", out var candidate))
				continue;
			if (TryAcceptConfigElementId(candidate, tag, out id))
				return true;
		}

		return false;
	}

	private static string TryReadObjectConfigTag(object target)
	{
		if (target == null)
			return null;
		var native = TryReadNativeStringMember(target, "tag");
		if (!string.IsNullOrWhiteSpace(native))
			return native.Trim();
		for (var cur = target.GetType(); cur != null && cur != typeof(object); cur = cur.BaseType)
		{
			if (TryReadDeclaredStringField(cur, target, "tag", out var tag) && !string.IsNullOrWhiteSpace(tag))
				return tag.Trim();
		}
		return null;
	}

	private static bool TryAcceptConfigElementId(string candidate, string tag, out string id)
	{
		id = null;
		if (string.IsNullOrWhiteSpace(candidate))
			return false;
		var trimmed = candidate.Trim();
		if (!string.IsNullOrWhiteSpace(tag) && string.Equals(trimmed, tag, StringComparison.Ordinal))
			return false;
		if (IsKnownObjectConfigCategoryTag(trimmed))
			return false;
		id = trimmed;
		return true;
	}

	/// <summary>
	/// Core.zip <c>DB/map/objects/*.json</c> <c>tag</c> vocabulary (never equals row <c>id</c>).
	/// </summary>
	private static bool IsKnownObjectConfigCategoryTag(string value)
	{
		return string.Equals(value, "Artifact", StringComparison.Ordinal)
		       || string.Equals(value, "Interact", StringComparison.Ordinal)
		       || string.Equals(value, "Environment", StringComparison.Ordinal)
		       || string.Equals(value, "Animals", StringComparison.Ordinal)
		       || string.Equals(value, "FX", StringComparison.Ordinal)
		       || string.Equals(value, "TEST", StringComparison.Ordinal)
		       || string.Equals(value, "Resource", StringComparison.Ordinal)
		       || string.Equals(value, "meta", StringComparison.Ordinal)
		       || string.Equals(value, "Block", StringComparison.Ordinal);
	}

	private static bool LooksLikeConfigElementBaseType(Type type)
	{
		if (type == null)
			return false;
		if (type.Name.StartsWith("ConfigElementBase", StringComparison.Ordinal))
			return true;
		return (type.FullName?.IndexOf("ConfigElementBase", StringComparison.Ordinal) ?? -1) >= 0;
	}

	private static bool IsStringConfigElementBaseType(Type type)
	{
		if (type == null || !type.IsGenericType || type.ContainsGenericParameters)
			return false;
		var arguments = type.GetGenericArguments();
		var definition = type.GetGenericTypeDefinition();
		return arguments.Length == 1
		       && arguments[0] == typeof(string)
		       && string.Equals(definition.FullName, GameSymbols.UnitViewConfig.ConfigElementBaseGenericTypeFullName, StringComparison.Ordinal);
	}

	private static bool TryReadDeclaredStringField(Type declaringType, object target, string fieldName, out string value)
	{
		value = null;
		if (declaringType == null || target == null || string.IsNullOrWhiteSpace(fieldName))
			return false;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		FieldInfo field = null;
		try { field = declaringType.GetField(fieldName, flags); }
		catch { return false; }
		if (field == null || field.FieldType != typeof(string))
			return false;
		try
		{
			var raw = field.GetValue(target) as string;
			if (string.IsNullOrWhiteSpace(raw))
				return false;
			value = raw.Trim();
			return true;
		}
		catch
		{
			return false;
		}
	}

	private static bool TryReadMember(Type type, object target, string name, out object value)
	{
		value = null;
		for (var cur = type; cur != null && cur != typeof(object); cur = cur.BaseType)
		{
			const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
			FieldInfo field = null;
			try { field = cur.GetField(name, flags); }
			catch { field = null; }
			if (field != null)
			{
				try
				{
					value = field.GetValue(target);
					return true;
				}
				catch { }
			}

			PropertyInfo property = null;
			try { property = cur.GetProperty(name, flags); }
			catch { property = null; }
			if (property != null && property.GetIndexParameters().Length == 0 && !IsGeneratedInteropPropertyName(name))
			{
				try
				{
					value = property.GetValue(target);
					return true;
				}
				catch (Exception ex) when (IsBrokenConfigElementInteropPropertyFailure(ex, name)) { }
				catch { }
			}
		}

		return false;
	}

	private static bool IsGeneratedInteropPropertyName(string name)
	{
		return !string.IsNullOrWhiteSpace(name)
		       && name.StartsWith("prop_", StringComparison.Ordinal);
	}

	private static bool IsBrokenConfigElementInteropPropertyFailure(Exception ex, string memberName)
	{
		if (!string.Equals(memberName, "id", StringComparison.Ordinal))
			return false;
		for (var cur = ex; cur != null; cur = cur.InnerException)
		{
			var message = cur.Message;
			if (string.IsNullOrEmpty(message))
				continue;
			if (message.IndexOf("ConfigElementBase", StringComparison.Ordinal) >= 0
			    && message.IndexOf("get_id", StringComparison.Ordinal) >= 0)
				return true;
		}
		return false;
	}

	private static bool TryWriteMember(Type type, object target, string name, object value)
	{
		for (var cur = type; cur != null && cur != typeof(object); cur = cur.BaseType)
		{
			const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
			PropertyInfo property = null;
			try { property = cur.GetProperty(name, flags); }
			catch { property = null; }
			if (property != null && property.CanWrite && property.GetIndexParameters().Length == 0)
			{
				try
				{
					property.SetValue(target, value);
					return true;
				}
				catch { }
			}

			FieldInfo field = null;
			try { field = cur.GetField(name, flags); }
			catch { field = null; }
			if (field != null)
			{
				try
				{
					field.SetValue(target, value);
					return true;
				}
				catch { }
			}
		}

		return false;
	}
}
