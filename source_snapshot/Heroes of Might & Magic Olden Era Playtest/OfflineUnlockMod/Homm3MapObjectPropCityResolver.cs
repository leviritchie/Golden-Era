using System;
using System.Collections.Generic;
using System.Reflection;
using System.Text;

namespace OfflineUnlockMod;

internal static class Homm3MapObjectPropCityResolver
{
	private const string PropFractionResolverProbeFlagName = "homm3_dwelling_fraction_resolver_probe.flag";

	private sealed class AreaContext
	{
		internal int Index;
		internal int? Id;
		internal int? RootNode;
		internal int? KeyObjectId;
		internal string Biome;
	}

	internal enum MissReason
	{
		None,
		NoMap,
		NoObjectsProperties,
		NoCustomMapObjectPropCity
	}

	internal static object ResolveObjectsProperties(object map)
	{
		if (map == null)
			return null;
		foreach (var candidate in EnumerateNoArgMemberValues(map, GameSymbols.CustomTownMapBillboard.MapObjectsPropertiesGetters))
			if (IsObjectsPropertiesCandidate(candidate))
				return candidate;
		foreach (var candidate in EnumerateMemberValues(map, GameSymbols.CustomTownMapBillboard.MapObjectsPropertiesFields))
			if (IsObjectsPropertiesCandidate(candidate))
				return candidate;
		return null;
	}

	internal static bool TryGetMapObjectPropCityFaction(object objectsProperties, int objectId, out string factionSid)
	{
		factionSid = null;
		if (objectId <= 0)
			return false;

		var sawScopedPropCity = false;
		foreach (var objectProps in EnumerateMapObjectPropertiesById(objectsProperties, objectId))
		{
			if (TryReadObjectIdScopedPropCityFactionAny(objectsProperties, objectProps, out var scopedFaction, out var scopedIsCustom))
			{
				sawScopedPropCity = true;
				if (scopedIsCustom)
				{
					factionSid = scopedFaction;
					return true;
				}
			}
			if (TryReadExactObjectPropCityFaction(objectProps, objectId, out factionSid))
				return true;
			foreach (var objectProp in EnumerateIl2CppList(objectProps))
			{
				if (TryReadObjectIdScopedPropCityFactionAny(objectsProperties, objectProp, out scopedFaction, out scopedIsCustom))
				{
					sawScopedPropCity = true;
					if (scopedIsCustom)
					{
						factionSid = scopedFaction;
						return true;
					}
				}
				if (TryReadExactObjectPropCityFaction(objectProp, objectId, out factionSid))
					return true;
			}
		}

		if (sawScopedPropCity)
			return false;

		return false;
	}

	internal static bool TryGetPlacedObjectPropCityFaction(object placedInstance, object mapInstance, int objectId, out string factionSid, out MissReason reason)
	{
		factionSid = null;
		reason = MissReason.None;
		var map = mapInstance ?? GetFirstMemberValue(placedInstance, GameSymbols.CustomTownMapBillboard.PlacedObjectMapFields);
		if (map == null)
		{
			reason = MissReason.NoMap;
			return false;
		}

		var objectsProperties = ResolveObjectsProperties(map);
		if (objectsProperties == null)
		{
			reason = MissReason.NoObjectsProperties;
			return false;
		}

		if (!TryGetMapObjectPropCityFaction(objectsProperties, objectId, out factionSid))
		{
			reason = MissReason.NoCustomMapObjectPropCity;
			return false;
		}

		return true;
	}

	internal static bool TryGetPlacedObjectPropRandomHire(object placedInstance, object mapInstance, int objectId, out int tier, out string fractionText, out MissReason reason)
	{
		tier = -1;
		fractionText = null;
		reason = MissReason.None;
		var map = mapInstance ?? GetFirstMemberValue(placedInstance, GameSymbols.CustomTownMapBillboard.PlacedObjectMapFields);
		if (map == null)
		{
			reason = MissReason.NoMap;
			return false;
		}

		var objectsProperties = ResolveObjectsProperties(map);
		if (objectsProperties == null)
		{
			reason = MissReason.NoObjectsProperties;
			return false;
		}

		if (!TryGetMapObjectPropRandomHire(objectsProperties, objectId, out tier, out fractionText))
		{
			reason = MissReason.NoCustomMapObjectPropCity;
			return false;
		}

		return true;
	}

	internal static bool TryGetPlacedObjectPropRandomHireNativeBiomeFaction(object placedInstance, object mapInstance, int objectId, int? nodeId, out int tier, out string fractionText, out string areaBiome, out string factionSid, out MissReason reason)
	{
		tier = -1;
		fractionText = null;
		areaBiome = null;
		factionSid = null;
		reason = MissReason.None;
		var map = mapInstance ?? GetFirstMemberValue(placedInstance, GameSymbols.CustomTownMapBillboard.PlacedObjectMapFields);
		if (map == null)
		{
			reason = MissReason.NoMap;
			return false;
		}
		if (!TryGetPlacedObjectPropRandomHire(placedInstance, map, objectId, out tier, out fractionText, out reason))
			return false;
		if (string.IsNullOrWhiteSpace(fractionText) || !fractionText.StartsWith("Node(", StringComparison.Ordinal))
			return false;
		var area = TryFindAreaContainingNode(map, nodeId, out _);
		if (area == null || string.IsNullOrWhiteSpace(area.Biome))
			return false;
		areaBiome = area.Biome.Trim();
		return Homm3CustomFactionRegistry.TryGetFactionSidForNativeBiome(areaBiome, out factionSid);
	}

	internal static bool TryGetMapObjectPropRandomHire(object objectsProperties, int objectId, out int tier, out string fractionText)
	{
		tier = -1;
		fractionText = null;
		if (objectId <= 0)
			return false;

		foreach (var objectProps in EnumerateMapObjectPropertiesById(objectsProperties, objectId))
		{
			if (TryReadObjectIdScopedPropRandomHire(objectsProperties, objectProps, objectId, out tier, out fractionText))
				return true;
			foreach (var objectProp in EnumerateIl2CppList(objectProps))
				if (TryReadObjectIdScopedPropRandomHire(objectsProperties, objectProp, objectId, out tier, out fractionText))
					return true;
		}

		return TryGetMapObjectPropRandomHireFromList(objectsProperties, objectId, out tier, out fractionText);
	}

	internal static int? TryGetIntMember(object obj, string[] names)
	{
		if (obj == null || names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var value = GetMemberValue(obj, names[i]);
			if (value == null)
				continue;
			try { return Convert.ToInt32(value); }
			catch { }
		}
		return null;
	}

	internal static string DescribePlacedObjectPropCityProbe(object placedInstance, object mapInstance, int objectId, string rawSid, int? nodeId)
	{
		var sb = new StringBuilder();
		sb.Append("rawSid='").Append(rawSid ?? "?").Append('\'');
		sb.Append(" objectId=").Append(objectId);
		sb.Append(" node=").Append(nodeId.HasValue ? nodeId.Value.ToString() : "?");
		sb.Append(" placedType=").Append(placedInstance?.GetType().FullName ?? "?");
		var map = mapInstance ?? GetFirstMemberValue(placedInstance, GameSymbols.CustomTownMapBillboard.PlacedObjectMapFields);
		sb.Append(" mapType=").Append(map?.GetType().FullName ?? "?");
		if (map == null)
			return sb.Append(" result=no-map").ToString();

		var objectsProperties = ResolveObjectsPropertiesForProbe(map, sb);
		if (objectsProperties == null)
			return sb.Append(" result=no-objects-properties").ToString();

		sb.Append(" objectsPropertiesType=").Append(objectsProperties.GetType().FullName ?? objectsProperties.GetType().Name);
		DescribePropCitiesProbe(objectsProperties, objectId, sb);
		DescribeMapObjectAccessorProbe(objectsProperties, objectId, sb);
		if (TryGetMapObjectPropCityFaction(objectsProperties, objectId, out var factionSid))
			sb.Append(" result=faction:").Append(factionSid);
		else
			sb.Append(" result=no-custom-map-object-prop-city");
		return sb.ToString();
	}

	internal static string DescribePlacedObjectPropRandomHireProbe(object placedInstance, object mapInstance, int objectId, string rawSid, int? nodeId)
	{
		var sb = new StringBuilder();
		sb.Append("rawSid='").Append(rawSid ?? "?").Append('\'');
		sb.Append(" objectId=").Append(objectId);
		sb.Append(" node=").Append(nodeId.HasValue ? nodeId.Value.ToString() : "?");
		sb.Append(" placedType=").Append(placedInstance?.GetType().FullName ?? "?");
		var map = mapInstance ?? GetFirstMemberValue(placedInstance, GameSymbols.CustomTownMapBillboard.PlacedObjectMapFields);
		sb.Append(" mapType=").Append(map?.GetType().FullName ?? "?");
		if (map == null)
			return sb.Append(" result=no-map").ToString();

		var objectsProperties = ResolveObjectsPropertiesForProbe(map, sb);
		if (objectsProperties == null)
			return sb.Append(" result=no-objects-properties").ToString();

		sb.Append(" objectsPropertiesType=").Append(objectsProperties.GetType().FullName ?? objectsProperties.GetType().Name);
		DescribePropRandomHiresProbe(objectsProperties, objectId, sb);
		if (TryGetMapObjectPropRandomHire(objectsProperties, objectId, out var tier, out var fractionText))
		{
			sb.Append(" result=random-hire:tier=").Append(tier).Append(",fraction=").Append(fractionText ?? "?");
			if (Homm3DiagnosticFlags.IsEnabled(PropFractionResolverProbeFlagName))
				DescribePropFractionResolverCandidates(map, nodeId, fractionText, sb);
		}
		else
			sb.Append(" result=no-prop-random-hire");
		return sb.ToString();
	}

	private static bool IsObjectsPropertiesCandidate(object candidate)
	{
		if (candidate == null)
			return false;
		var typeName = candidate.GetType().FullName ?? candidate.GetType().Name ?? string.Empty;
		foreach (var rejected in GameSymbols.CustomTownMapBillboard.RejectedMapObjectsPropertiesTypeNames)
			if (!string.IsNullOrWhiteSpace(rejected) && typeName.IndexOf(rejected, StringComparison.Ordinal) >= 0)
				return false;
		if (GetFirstMemberValue(candidate, GameSymbols.CustomTownMapBillboard.PropCitiesFields) != null
		    || InvokeFirstNoArgByName(candidate, GameSymbols.CustomTownMapBillboard.PropCitiesGetters) != null)
			return true;
		return HasMapObjectPropertyAccessor(candidate);
	}

	private static bool HasMapObjectPropertyAccessor(object candidate)
	{
		if (candidate == null)
			return false;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var names = GameSymbols.CustomTownMapBillboard.MapObjectPropertiesGetters;
		for (var t = candidate.GetType(); t != null; t = t.BaseType)
		{
			MethodInfo[] methods;
			try { methods = t.GetMethods(flags); }
			catch { methods = Array.Empty<MethodInfo>(); }
			for (var i = 0; i < names.Length; i++)
			for (var j = 0; j < methods.Length; j++)
			{
				var method = methods[j];
				if (method == null || method.Name != names[i])
					continue;
				var ps = method.GetParameters();
				if (ps.Length == 2 && TryCreateIntegralArgument(ps[0].ParameterType, 0, out _) && TryCreateIntegralArgument(ps[1].ParameterType, 0, out _))
					return true;
			}
		}
		return false;
	}

	private static bool TryGetMapObjectPropCityFactionFromPropCities(object objectsProperties, int objectId, out string factionSid)
	{
		factionSid = null;
		if (objectsProperties == null)
			return false;
		var propCities = GetFirstMemberValue(objectsProperties, GameSymbols.CustomTownMapBillboard.PropCitiesFields)
		                 ?? InvokeFirstNoArgByName(objectsProperties, GameSymbols.CustomTownMapBillboard.PropCitiesGetters);
		if (propCities == null)
			return false;

		foreach (var objectProp in EnumerateIl2CppList(propCities))
			if (TryReadPropCityFaction(objectProp, objectId, requireExactId: true, out factionSid))
				return true;
		return false;
	}

	private static bool TryReadExactObjectPropCityFaction(object objectProp, int objectId, out string factionSid)
	{
		return TryReadPropCityFaction(objectProp, objectId, requireExactId: true, out factionSid);
	}

	private static bool TryReadObjectIdScopedPropCityFaction(object objectsProperties, object objectProp, int objectId, out string factionSid)
	{
		if (TryReadObjectIdScopedPropCityFactionAny(objectsProperties, objectProp, out factionSid, out var isCustom))
			return isCustom;
		return false;
	}

	private static bool TryReadObjectIdScopedPropCityFactionAny(object objectsProperties, object objectProp, out string factionSid, out bool isCustom)
	{
		factionSid = null;
		isCustom = false;
		var propCityIndex = TryGetIntMember(objectProp, GameSymbols.CustomTownMapBillboard.MapObjectPropValueFields)
		                    ?? TryInvokeIntGetter(objectProp, GameSymbols.CustomTownMapBillboard.MapObjectPropValueGetters);
		if (!propCityIndex.HasValue)
			return false;
		var propCity = TryGetPropCityByIndex(objectsProperties, propCityIndex.Value);
		if (propCity == null)
			return false;
		var thisFaction = GetFirstMemberValue(propCity, GameSymbols.CustomTownMapBillboard.PropCityFactionFields) as string;
		if (string.IsNullOrWhiteSpace(thisFaction))
			thisFaction = InvokeFirstNoArgByName(propCity, GameSymbols.CustomTownMapBillboard.PropCityFactionGetters) as string;
		if (string.IsNullOrWhiteSpace(thisFaction))
			return false;
		factionSid = thisFaction.Trim();
		isCustom = Homm3CustomFactionRegistry.GetCitySidForFaction(factionSid) != null;
		return true;
	}

	private static bool TryGetMapObjectPropRandomHireFromList(object objectsProperties, int objectId, out int tier, out string fractionText)
	{
		tier = -1;
		fractionText = null;
		if (objectsProperties == null)
			return false;
		var propRandomHires = GetFirstMemberValue(objectsProperties, GameSymbols.CustomDwellingRandomHire.PropRandomHireFields)
		                      ?? InvokeFirstNoArgByName(objectsProperties, GameSymbols.CustomDwellingRandomHire.PropRandomHireGetters);
		if (propRandomHires == null)
			return false;

		foreach (var objectProp in EnumerateIl2CppList(propRandomHires))
			if (TryReadPropRandomHire(objectProp, objectId, requireExactId: true, out tier, out fractionText))
				return true;
		return false;
	}

	private static bool TryReadObjectIdScopedPropRandomHire(object objectsProperties, object objectProp, int objectId, out int tier, out string fractionText)
	{
		tier = -1;
		fractionText = null;
		var propRandomHireIndex = TryGetIntMember(objectProp, GameSymbols.CustomTownMapBillboard.MapObjectPropValueFields)
		                          ?? TryInvokeIntGetter(objectProp, GameSymbols.CustomTownMapBillboard.MapObjectPropValueGetters);
		if (!propRandomHireIndex.HasValue)
			return false;
		var propRandomHire = TryGetPropRandomHireByIndex(objectsProperties, propRandomHireIndex.Value);
		return TryReadPropRandomHire(propRandomHire, objectId, requireExactId: false, out tier, out fractionText);
	}

	private static object TryGetPropCityByIndex(object objectsProperties, int index)
	{
		if (objectsProperties == null || index < 0)
			return null;
		var propCities = GetFirstMemberValue(objectsProperties, GameSymbols.CustomTownMapBillboard.PropCitiesFields)
		                 ?? InvokeFirstNoArgByName(objectsProperties, GameSymbols.CustomTownMapBillboard.PropCitiesGetters);
		if (propCities == null)
			return null;
		return TryGetListItem(propCities, index);
	}

	private static object TryGetPropRandomHireByIndex(object objectsProperties, int index)
	{
		if (objectsProperties == null || index < 0)
			return null;
		var propRandomHires = GetFirstMemberValue(objectsProperties, GameSymbols.CustomDwellingRandomHire.PropRandomHireFields)
		                      ?? InvokeFirstNoArgByName(objectsProperties, GameSymbols.CustomDwellingRandomHire.PropRandomHireGetters);
		if (propRandomHires == null)
			return null;
		return TryGetListItem(propRandomHires, index);
	}

	private static object TryGetListItem(object listObj, int index)
	{
		if (listObj == null || index < 0)
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		MethodInfo itemGetter = null;
		for (var t = listObj.GetType(); t != null && itemGetter == null; t = t.BaseType)
		{
			try { itemGetter = t.GetMethod("get_Item", flags, null, new[] { typeof(int) }, null); }
			catch { itemGetter = null; }
		}
		if (itemGetter == null)
			return null;
		try { return itemGetter.Invoke(listObj, new object[] { index }); }
		catch { return null; }
	}

	private static bool TryReadPropRandomHire(object objectProp, int objectId, bool requireExactId, out int tier, out string fractionText)
	{
		tier = -1;
		fractionText = null;
		if (objectProp == null)
			return false;
		var propId = TryGetIntMember(objectProp, GameSymbols.CustomDwellingRandomHire.PropRandomHireIdFields);
		if (requireExactId && (!propId.HasValue || propId.Value != objectId))
			return false;
		if (propId.HasValue && propId.Value != objectId)
			return false;
		var tierValue = TryGetIntMember(objectProp, GameSymbols.CustomDwellingRandomHire.PropRandomHireTierFields);
		if (!tierValue.HasValue)
			tierValue = TryInvokeIntGetter(objectProp, GameSymbols.CustomDwellingRandomHire.PropRandomHireTierGetters);
		if (!tierValue.HasValue || tierValue.Value <= 0)
			return false;
		var fraction = GetFirstMemberValue(objectProp, GameSymbols.CustomDwellingRandomHire.PropRandomHireFractionFields)
		               ?? InvokeFirstNoArgByName(objectProp, GameSymbols.CustomDwellingRandomHire.PropRandomHireFractionGetters);
		tier = tierValue.Value;
		fractionText = DescribeScalar(fraction);
		return true;
	}

	private static bool TryReadPropCityFaction(object objectProp, int objectId, bool requireExactId, out string factionSid)
	{
		factionSid = null;
		if (objectProp == null)
			return false;
		var propId = TryGetIntMember(objectProp, GameSymbols.CustomTownMapBillboard.PropCityIdFields);
		if (!propId.HasValue)
			propId = TryInvokeIntGetter(objectProp, GameSymbols.CustomTownMapBillboard.PropCityIdGetters);
		if (requireExactId && (!propId.HasValue || propId.Value != objectId))
			return false;
		if (propId.HasValue && propId.Value != objectId)
			return false;
		var thisFaction = GetFirstMemberValue(objectProp, GameSymbols.CustomTownMapBillboard.PropCityFactionFields) as string;
		if (string.IsNullOrWhiteSpace(thisFaction))
			thisFaction = InvokeFirstNoArgByName(objectProp, GameSymbols.CustomTownMapBillboard.PropCityFactionGetters) as string;
		if (string.IsNullOrWhiteSpace(thisFaction))
			return false;
		var normalized = thisFaction.Trim();
		if (Homm3CustomFactionRegistry.GetCitySidForFaction(normalized) == null)
			return false;
		factionSid = normalized;
		return true;
	}

	private static object ResolveObjectsPropertiesForProbe(object map, StringBuilder sb)
	{
		if (map == null)
			return null;
		foreach (var candidate in EnumerateNoArgMemberValuesWithName(map, GameSymbols.CustomTownMapBillboard.MapObjectsPropertiesGetters))
		{
			if (candidate.Value == null)
				continue;
			sb.Append(" objectsPropertiesGetter=").Append(candidate.Name).Append(':').Append(candidate.Value.GetType().FullName ?? candidate.Value.GetType().Name);
			if (IsObjectsPropertiesCandidate(candidate.Value))
				return candidate.Value;
			sb.Append("(rejected)");
		}
		foreach (var candidate in EnumerateMemberValuesWithName(map, GameSymbols.CustomTownMapBillboard.MapObjectsPropertiesFields))
		{
			if (candidate.Value == null)
				continue;
			sb.Append(" objectsPropertiesField=").Append(candidate.Name).Append(':').Append(candidate.Value.GetType().FullName ?? candidate.Value.GetType().Name);
			if (IsObjectsPropertiesCandidate(candidate.Value))
				return candidate.Value;
			sb.Append("(rejected)");
		}
		return null;
	}

	private static void DescribePropCitiesProbe(object objectsProperties, int objectId, StringBuilder sb)
	{
		var propCities = GetFirstMemberValue(objectsProperties, GameSymbols.CustomTownMapBillboard.PropCitiesFields)
		                 ?? InvokeFirstNoArgByName(objectsProperties, GameSymbols.CustomTownMapBillboard.PropCitiesGetters);
		if (propCities == null)
		{
			sb.Append(" propCities=null");
			return;
		}
		sb.Append(" propCitiesType=").Append(propCities.GetType().FullName ?? propCities.GetType().Name);
		var count = 0;
		var samples = new List<string>();
		foreach (var propCity in EnumerateIl2CppList(propCities))
		{
			count++;
			if (samples.Count >= 4)
				continue;
			var propId = TryGetIntMember(propCity, GameSymbols.CustomTownMapBillboard.PropCityIdFields);
			var faction = GetFirstMemberValue(propCity, GameSymbols.CustomTownMapBillboard.PropCityFactionFields) as string
			              ?? InvokeFirstNoArgByName(propCity, GameSymbols.CustomTownMapBillboard.PropCityFactionGetters) as string;
			samples.Add((propCity?.GetType().Name ?? "?") + "#" + (propId.HasValue ? propId.Value.ToString() : "?") + ":" + (faction ?? "?"));
		}
		sb.Append(" propCitiesCount=").Append(count);
		if (samples.Count > 0)
			sb.Append(" propCitiesSample=[").Append(string.Join(",", samples)).Append(']');
	}

	private static void DescribeMapObjectAccessorProbe(object objectsProperties, int objectId, StringBuilder sb)
	{
		if (objectsProperties == null)
			return;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var names = GameSymbols.CustomTownMapBillboard.MapObjectPropertiesGetters;
		var logged = 0;
		for (var t = objectsProperties.GetType(); t != null; t = t.BaseType)
		{
			MethodInfo[] methods;
			try { methods = t.GetMethods(flags); }
			catch { methods = Array.Empty<MethodInfo>(); }
			for (var i = 0; i < names.Length; i++)
			{
				for (var j = 0; j < methods.Length; j++)
				{
					var method = methods[j];
					if (method == null || method.Name != names[i])
						continue;
					if (!TryBuildMapObjectPropertiesArgs(method, objectId, out var args))
						continue;
					object value = null;
					string result;
					try
					{
						value = method.Invoke(objectsProperties, args);
						result = value == null ? "null" : value.GetType().FullName ?? value.GetType().Name;
					}
					catch (Exception ex)
					{
						result = "throw:" + (ex.InnerException?.GetType().Name ?? ex.GetType().Name);
					}
					if (logged == 0)
						sb.Append(" mapObjectAccessors=");
					else
						sb.Append('|');
					sb.Append(method.Name).Append('(').Append(method.GetParameters()[0].ParameterType.Name).Append(',').Append(method.GetParameters()[1].ParameterType.Name).Append(")->").Append(result);
					DescribeMapObjectAccessorResultProbe(objectsProperties, value, objectId, sb);
					logged++;
					if (logged >= 4)
						return;
				}
			}
		}
		if (logged == 0)
			sb.Append(" mapObjectAccessors=none");
	}

	private static void DescribeMapObjectAccessorResultProbe(object objectsProperties, object result, int objectId, StringBuilder sb)
	{
		if (result == null)
			return;
		var samples = new List<string>();
		if (TryDescribeObjectPropLink(objectsProperties, result, objectId, out var direct))
			samples.Add(direct);
		foreach (var objectProp in EnumerateIl2CppList(result))
		{
			if (samples.Count >= 4)
				break;
			if (TryDescribeObjectPropLink(objectsProperties, objectProp, objectId, out var sample))
				samples.Add(sample);
		}
		if (samples.Count > 0)
			sb.Append('{').Append(string.Join(",", samples)).Append('}');
	}

	private static bool TryDescribeObjectPropLink(object objectsProperties, object objectProp, int objectId, out string text)
	{
		text = null;
		if (objectProp == null)
			return false;
		var value = TryGetIntMember(objectProp, GameSymbols.CustomTownMapBillboard.MapObjectPropValueFields)
		            ?? TryInvokeIntGetter(objectProp, GameSymbols.CustomTownMapBillboard.MapObjectPropValueGetters);
		if (!value.HasValue)
			return false;
		var propCity = TryGetPropCityByIndex(objectsProperties, value.Value);
		var faction = "?";
		if (propCity != null)
		{
			faction = GetFirstMemberValue(propCity, GameSymbols.CustomTownMapBillboard.PropCityFactionFields) as string
			          ?? InvokeFirstNoArgByName(propCity, GameSymbols.CustomTownMapBillboard.PropCityFactionGetters) as string
			          ?? "?";
		}
		text = "value=" + value.Value + ":propCity=" + (propCity == null ? "null" : "ok") + ":faction=" + faction;
		if (TryReadObjectIdScopedPropCityFaction(objectsProperties, objectProp, objectId, out var resolved))
			text += ":resolved=" + resolved;
		var propRandomHire = TryGetPropRandomHireByIndex(objectsProperties, value.Value);
		if (TryReadPropRandomHire(propRandomHire, objectId, requireExactId: false, out var tier, out var fractionText))
			text += ":propRandomHire=ok:tier=" + tier + ":fraction=" + (fractionText ?? "?");
		else if (propRandomHire != null)
			text += ":propRandomHire=unreadable";
		return true;
	}

	private static void DescribePropRandomHiresProbe(object objectsProperties, int objectId, StringBuilder sb)
	{
		var propRandomHires = GetFirstMemberValue(objectsProperties, GameSymbols.CustomDwellingRandomHire.PropRandomHireFields)
		                      ?? InvokeFirstNoArgByName(objectsProperties, GameSymbols.CustomDwellingRandomHire.PropRandomHireGetters);
		if (propRandomHires == null)
		{
			sb.Append(" propRandomHires=null");
			return;
		}
		sb.Append(" propRandomHiresType=").Append(propRandomHires.GetType().FullName ?? propRandomHires.GetType().Name);
		var count = 0;
		var samples = new List<string>();
		foreach (var propRandomHire in EnumerateIl2CppList(propRandomHires))
		{
			count++;
			if (samples.Count >= 4)
				continue;
			var propId = TryGetIntMember(propRandomHire, GameSymbols.CustomDwellingRandomHire.PropRandomHireIdFields);
			TryReadPropRandomHire(propRandomHire, propId ?? objectId, requireExactId: propId.HasValue, out var tier, out var fraction);
			samples.Add((propRandomHire?.GetType().Name ?? "?") + "#" + (propId.HasValue ? propId.Value.ToString() : "?") + ":tier=" + (tier > 0 ? tier.ToString() : "?") + ":fraction=" + (fraction ?? "?"));
		}
		sb.Append(" propRandomHiresCount=").Append(count);
		if (samples.Count > 0)
			sb.Append(" propRandomHiresSample=[").Append(string.Join(",", samples)).Append(']');
	}

	private static void DescribePropFractionResolverCandidates(object map, int? nodeId, string fractionText, StringBuilder sb)
	{
		if (map == null || string.IsNullOrWhiteSpace(fractionText))
			return;
		var fractionValue = TryParseEnumValue(fractionText);
		if (!fractionValue.HasValue)
		{
			sb.Append(" fractionResolvers=unparsed");
			return;
		}
		var resolverType = FindType(GameSymbols.CustomDwellingRandomHire.PropFractionResolverTypeNames);
		if (resolverType == null)
		{
			sb.Append(" fractionResolvers=no-type");
			return;
		}
		var contexts = BuildPropFractionContextCandidates(map, nodeId, sb);
		if (contexts.Count == 0)
		{
			sb.Append(" fractionResolvers=no-context");
			return;
		}

		const BindingFlags flags = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
		var logged = 0;
		for (var c = 0; c < contexts.Count; c++)
		{
			var context = contexts[c];
			for (var i = 0; i < GameSymbols.CustomDwellingRandomHire.PropFractionMapResolverMethods.Length; i++)
			{
				var methodName = GameSymbols.CustomDwellingRandomHire.PropFractionMapResolverMethods[i];
				MethodInfo method;
				try { method = resolverType.GetMethod(methodName, flags); }
				catch { method = null; }
				if (method == null || !TryBuildPropFractionResolverArgs(method, map, fractionValue.Value, context.Value, out var args))
					continue;
				string result;
				try
				{
					result = method.Invoke(null, args) as string;
					if (string.IsNullOrWhiteSpace(result))
						result = "<empty>";
				}
				catch (Exception ex)
				{
					var inner = ex.InnerException;
					result = "throw:" + (inner?.GetType().Name ?? ex.GetType().Name);
					var message = inner?.Message ?? ex.Message;
					if (!string.IsNullOrWhiteSpace(message))
						result += ":" + SanitizeLogFragment(message);
				}
				if (logged == 0)
					sb.Append(" fractionResolvers=");
				else
					sb.Append('|');
				sb.Append(context.Label).Append(':').Append(ShortResolverName(methodName)).Append("->").Append(SanitizeLogFragment(result));
				logged++;
				if (logged >= 12)
					return;
			}
		}
		if (logged == 0)
			sb.Append(" fractionResolvers=no-method");
	}

	private static List<(string Label, int Value)> BuildPropFractionContextCandidates(object map, int? nodeId, StringBuilder sb)
	{
		var contexts = new List<(string Label, int Value)>();
		if (nodeId.HasValue && nodeId.Value > 0)
			contexts.Add(("node", nodeId.Value));
		var area = TryFindAreaContainingNode(map, nodeId, out var areaCount);
		if (area != null)
		{
			sb.Append(" area=index=").Append(area.Index)
				.Append(",id=").Append(area.Id.HasValue ? area.Id.Value.ToString() : "?")
				.Append(",root=").Append(area.RootNode.HasValue ? area.RootNode.Value.ToString() : "?")
				.Append(",key=").Append(area.KeyObjectId.HasValue ? area.KeyObjectId.Value.ToString() : "?")
				.Append(",biome=").Append(area.Biome ?? "?")
				.Append(",count=").Append(areaCount);
			AddUniqueContext(contexts, "areaIndex", area.Index);
			if (area.Id.HasValue)
				AddUniqueContext(contexts, "areaId", area.Id.Value);
			if (area.RootNode.HasValue)
				AddUniqueContext(contexts, "rootNode", area.RootNode.Value);
			if (area.KeyObjectId.HasValue)
				AddUniqueContext(contexts, "keyObject", area.KeyObjectId.Value);
		}
		else if (areaCount >= 0)
		{
			sb.Append(" area=not-found,count=").Append(areaCount);
		}
		else
		{
			sb.Append(" area=no-map-data");
		}
		return contexts;
	}

	private static void AddUniqueContext(List<(string Label, int Value)> contexts, string label, int value)
	{
		if (value < 0)
			return;
		for (var i = 0; i < contexts.Count; i++)
			if (contexts[i].Value == value)
				return;
		contexts.Add((label, value));
	}

	private static AreaContext TryFindAreaContainingNode(object map, int? nodeId, out int areaCount)
	{
		areaCount = -1;
		if (map == null)
			return null;
		var mapData = GetFirstMemberValue(map, GameSymbols.CustomDwellingRandomHire.MapDataFields)
		              ?? InvokeFirstNoArgByName(map, GameSymbols.CustomDwellingRandomHire.MapDataGetters);
		if (mapData == null)
			return null;
		var areas = GetFirstMemberValue(mapData, GameSymbols.CustomDwellingRandomHire.MapDataAreasFields)
		            ?? InvokeFirstNoArgByName(mapData, GameSymbols.CustomDwellingRandomHire.MapDataAreasGetters);
		if (areas == null)
			return null;
		areaCount = 0;
		AreaContext fallback = null;
		foreach (var areaObject in EnumerateIl2CppList(areas))
		{
			var context = DescribeArea(areaObject, areaCount);
			if (context != null && fallback == null)
				fallback = context;
			if (nodeId.HasValue && AreaContainsNode(areaObject, nodeId.Value))
				return context;
			areaCount++;
		}
		return nodeId.HasValue ? null : fallback;
	}

	private static AreaContext DescribeArea(object areaObject, int index)
	{
		if (areaObject == null)
			return null;
		return new AreaContext
		{
			Index = index,
			Id = TryInvokeIntGetter(areaObject, GameSymbols.CustomDwellingRandomHire.MapDataAreaIdGetters),
			RootNode = TryInvokeIntGetter(areaObject, GameSymbols.CustomDwellingRandomHire.MapDataAreaRootNodeGetters),
			KeyObjectId = TryInvokeIntGetter(areaObject, GameSymbols.CustomDwellingRandomHire.MapDataAreaKeyObjectIdGetters),
			Biome = InvokeFirstNoArgByName(areaObject, GameSymbols.CustomDwellingRandomHire.MapDataAreaBiomeGetters) as string
		};
	}

	private static bool AreaContainsNode(object areaObject, int nodeId)
	{
		var nodes = InvokeFirstNoArgByName(areaObject, GameSymbols.CustomDwellingRandomHire.MapDataAreaNodesGetters);
		if (nodes == null)
			return false;
		foreach (var node in EnumerateIl2CppList(nodes))
		{
			try
			{
				if (Convert.ToInt32(node) == nodeId)
					return true;
			}
			catch { }
		}
		return false;
	}

	private static string ShortResolverName(string methodName)
	{
		if (string.IsNullOrWhiteSpace(methodName))
			return "?";
		var marker = methodName.LastIndexOf("_PDM_", StringComparison.Ordinal);
		return marker >= 0 ? "PDM_" + methodName.Substring(marker + 5) : methodName;
	}

	private static string SanitizeLogFragment(string text)
	{
		if (string.IsNullOrWhiteSpace(text))
			return text;
		return text.Replace('\r', ' ').Replace('\n', ' ').Replace('|', '/').Trim();
	}

	private static int? TryParseEnumValue(string text)
	{
		if (string.IsNullOrWhiteSpace(text))
			return null;
		var open = text.LastIndexOf('(');
		var close = text.LastIndexOf(')');
		if (open >= 0 && close > open && int.TryParse(text.Substring(open + 1, close - open - 1), out var parsed))
			return parsed;
		return null;
	}

	private static bool TryBuildPropFractionResolverArgs(MethodInfo method, object map, int fractionValue, int contextId, out object[] args)
	{
		args = null;
		if (method == null || map == null)
			return false;
		ParameterInfo[] parameters;
		try { parameters = method.GetParameters(); }
		catch { return false; }
		if (parameters.Length != 3)
			return false;
		if (!parameters[0].ParameterType.IsEnum || parameters[1].ParameterType == null || !parameters[1].ParameterType.IsInstanceOfType(map))
			return false;
		if (!TryCreateIntegralArgument(parameters[2].ParameterType, contextId, out var idArg))
			return false;
		try
		{
			args = new[] { Enum.ToObject(parameters[0].ParameterType, fractionValue), map, idArg };
			return true;
		}
		catch
		{
			args = null;
			return false;
		}
	}

	private static Type FindType(string[] typeNames)
	{
		if (typeNames == null)
			return null;
		Assembly[] assemblies;
		try { assemblies = AppDomain.CurrentDomain.GetAssemblies(); }
		catch { return null; }
		for (var i = 0; i < typeNames.Length; i++)
		{
			var name = typeNames[i];
			if (string.IsNullOrWhiteSpace(name))
				continue;
			for (var j = 0; j < assemblies.Length; j++)
			{
				Type type;
				try { type = assemblies[j].GetType(name, throwOnError: false); }
				catch { type = null; }
				if (type != null)
					return type;
			}
		}
		return null;
	}

	private static IEnumerable<object> EnumerateMapObjectPropertiesById(object objectsProperties, int objectId)
	{
		if (objectsProperties == null)
			yield break;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var names = GameSymbols.CustomTownMapBillboard.MapObjectPropertiesGetters;
		for (var t = objectsProperties.GetType(); t != null; t = t.BaseType)
		{
			MethodInfo[] methods;
			try { methods = t.GetMethods(flags); }
			catch { methods = Array.Empty<MethodInfo>(); }
			for (var i = 0; i < names.Length; i++)
			{
				for (var j = 0; j < methods.Length; j++)
				{
					var method = methods[j];
					if (method == null || method.Name != names[i])
						continue;
					if (!TryBuildMapObjectPropertiesArgs(method, objectId, out var args))
						continue;
					object value = null;
					try
					{
						value = method.Invoke(objectsProperties, args);
					}
					catch { }
					if (value != null)
						yield return value;
				}
			}
		}
	}

	private static bool TryBuildMapObjectPropertiesArgs(MethodInfo method, int objectId, out object[] args)
	{
		args = null;
		if (method == null)
			return false;
		ParameterInfo[] parameters;
		try { parameters = method.GetParameters(); }
		catch { return false; }
		if (parameters == null || parameters.Length != 2)
			return false;
		if (!TryCreateIntegralArgument(parameters[0].ParameterType, 0, out var propTypeArg))
			return false;
		if (!TryCreateIntegralArgument(parameters[1].ParameterType, objectId, out var idArg))
			return false;
		args = new[] { propTypeArg, idArg };
		return true;
	}

	private static bool TryCreateIntegralArgument(Type parameterType, int value, out object arg)
	{
		arg = null;
		if (parameterType == null)
			return false;
		if (parameterType.IsEnum)
		{
			try
			{
				arg = Enum.ToObject(parameterType, value);
				return true;
			}
			catch
			{
				return false;
			}
		}
		if (parameterType == typeof(int))
		{
			arg = value;
			return true;
		}
		if (parameterType == typeof(byte))
		{
			arg = (byte)value;
			return true;
		}
		return false;
	}

	private static int? TryInvokeIntGetter(object obj, string[] names)
	{
		if (obj == null || names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var value = InvokeFirstNoArgByName(obj, new[] { names[i] });
			if (value == null)
				continue;
			try { return Convert.ToInt32(value); }
			catch { }
		}
		return null;
	}

	private static string DescribeScalar(object value)
	{
		if (value == null)
			return null;
		try
		{
			if (value.GetType().IsEnum)
				return value + "(" + Convert.ToInt32(value) + ")";
		}
		catch { }
		return value.ToString();
	}

	private static IEnumerable<object> EnumerateNoArgMemberValues(object obj, string[] names)
	{
		if (obj == null || names == null)
			yield break;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		for (var t = obj.GetType(); t != null; t = t.BaseType)
		{
			for (var i = 0; i < names.Length; i++)
			{
				MethodInfo method;
				try { method = t.GetMethod(names[i], flags, null, Type.EmptyTypes, null); }
				catch { method = null; }
				if (method == null)
					continue;
				object value = null;
				try { value = method.Invoke(obj, null); }
				catch { }
				if (value != null)
					yield return value;
			}
		}
	}

	private static IEnumerable<(string Name, object Value)> EnumerateNoArgMemberValuesWithName(object obj, string[] names)
	{
		if (obj == null || names == null)
			yield break;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		for (var t = obj.GetType(); t != null; t = t.BaseType)
		{
			for (var i = 0; i < names.Length; i++)
			{
				MethodInfo method;
				try { method = t.GetMethod(names[i], flags, null, Type.EmptyTypes, null); }
				catch { method = null; }
				if (method == null)
					continue;
				object value = null;
				try { value = method.Invoke(obj, null); }
				catch { }
				if (value != null)
					yield return (method.Name, value);
			}
		}
	}

	private static IEnumerable<object> EnumerateMemberValues(object obj, string[] names)
	{
		if (obj == null || names == null)
			yield break;
		for (var i = 0; i < names.Length; i++)
		{
			var value = GetMemberValue(obj, names[i]);
			if (value != null)
				yield return value;
		}
	}

	private static IEnumerable<(string Name, object Value)> EnumerateMemberValuesWithName(object obj, string[] names)
	{
		if (obj == null || names == null)
			yield break;
		for (var i = 0; i < names.Length; i++)
		{
			var value = GetMemberValue(obj, names[i]);
			if (value != null)
				yield return (names[i], value);
		}
	}

	private static object InvokeFirstNoArgByName(object obj, string[] names)
	{
		if (obj == null || names == null)
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		for (var t = obj.GetType(); t != null; t = t.BaseType)
		{
			for (var i = 0; i < names.Length; i++)
			{
				MethodInfo m;
				try { m = t.GetMethod(names[i], flags, null, Type.EmptyTypes, null); }
				catch { m = null; }
				if (m == null)
					continue;
				try
				{
					var value = m.Invoke(obj, null);
					if (value != null)
						return value;
				}
				catch { }
			}
		}
		return null;
	}

	private static IEnumerable<object> EnumerateIl2CppList(object listObj)
	{
		if (listObj == null)
			yield break;
		var type = listObj.GetType();
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		PropertyInfo countProp = null;
		MethodInfo countGetter = null;
		MethodInfo itemGetter = null;
		for (var t = type; t != null && countProp == null; t = t.BaseType)
		{
			try { countProp = t.GetProperty("Count", flags); }
			catch { countProp = null; }
		}
		if (countProp == null)
		{
			for (var t = type; t != null && countGetter == null; t = t.BaseType)
			{
				try { countGetter = t.GetMethod("get_Count", flags, null, Type.EmptyTypes, null); }
				catch { countGetter = null; }
			}
		}
		for (var t = type; t != null && itemGetter == null; t = t.BaseType)
		{
			try { itemGetter = t.GetMethod("get_Item", flags, null, new[] { typeof(int) }, null); }
			catch { itemGetter = null; }
		}
		if (itemGetter == null)
		{
			if (listObj is not System.Collections.IEnumerable enumerable)
				yield break;
			foreach (var item in enumerable)
			{
				if (item != null)
					yield return item;
			}
			yield break;
		}
		int count;
		try
		{
			count = countProp != null
				? Convert.ToInt32(countProp.GetValue(listObj))
				: Convert.ToInt32(countGetter.Invoke(listObj, null));
		}
		catch
		{
			yield break;
		}
		for (var i = 0; i < count; i++)
		{
			object item;
			try { item = itemGetter.Invoke(listObj, new object[] { i }); }
			catch { item = null; }
			if (item != null)
				yield return item;
		}
	}

	private static object GetFirstMemberValue(object obj, string[] names)
	{
		if (obj == null || names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var value = GetMemberValue(obj, names[i]);
			if (value != null)
				return value;
		}
		return null;
	}

	private static object GetMemberValue(object obj, string name)
	{
		if (obj == null)
			return null;
		for (var t = obj.GetType(); t != null; t = t.BaseType)
		{
			var f = t.GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
			if (f != null)
				return f.GetValue(obj);
		}
		return null;
	}
}
