using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using System.Text;
using UnityEngine;
using UnityEngine.SceneManagement;

/// <summary>
/// Live read-only: current map SID + Caryatid (object id 16) / land-on castle city nodes.
/// Uses Golden Era MapData member names (sizeX_, Il2Cpp list Count/get_Item, PropCity field_Public_Int32_0).
/// </summary>
public static class CaryatidLocationProbe20260710
{
	private const BindingFlags All = BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
	private const int CaryatidObjectId = 16;
	private const string LandonCastleSid = "homm3_landon_castle_city";
	private const string CityName = "Caryatid";

	public static string Run(string requestJson)
	{
		var sb = new StringBuilder();
		try
		{
			sb.Append("scene=").Append(SceneManager.GetActiveScene().name ?? "?");
			var map = FindActiveMap(sb);
			if (map == null)
				return Ok(sb.Append(" map=null").ToString());

			sb.Append(" mapType=").Append(map.GetType().FullName ?? "?");
			var mapData = GetMapData(map, sb);
			if (mapData == null)
				return Ok(sb.Append(" mapData=null").ToString());

			sb.Append(" mapDataType=").Append(mapData.GetType().FullName ?? "?");
			var fileMapName = FirstString(mapData, "fileMapName", "get_fileMapName")
				?? FirstString(map, "fileMapName", "get_fileMapName")
				?? "?";
			sb.Append(" fileMapName=").Append(fileMapName);

			var sizeX = FirstInt(mapData, "sizeX_", "sizeX");
			var sizeZ = FirstInt(mapData, "sizeZ_", "sizeZ");
			if (sizeX < 0)
				sizeX = InvokeIntGetter(mapData, "get_sizeX_", "Method_Public_get_Int32_0", "get_sizeX");
			if (sizeZ < 0)
				sizeZ = InvokeIntGetter(mapData, "get_sizeZ_", "Method_Public_get_Int32_1", "get_sizeZ");
			sb.Append(" sizeX=").Append(sizeX).Append(" sizeZ=").Append(sizeZ);
			var width = sizeX > 0 ? sizeX : 160;

			DumpObjectsSummary(sb, mapData);
			DumpObjectId(sb, mapData, CaryatidObjectId, width);
			DumpSid(sb, mapData, LandonCastleSid, width);
			DumpCityName(sb, mapData, CityName, width);
			DumpPlacedObjects(sb, width);
			return Ok(sb.ToString());
		}
		catch (Exception ex)
		{
			return "{\"ok\":false,\"exception\":\"" + Escape(ex.GetType().Name) + "\",\"message\":\"" + Escape(ex.Message) + "\",\"stack\":\"" + Escape(ex.StackTrace ?? "") + "\"}";
		}
	}

	private static string Ok(string text)
	{
		return "{\"ok\":true,\"text\":\"" + Escape(text) + "\"}";
	}

	private static object GetObjectsList(object mapData)
	{
		return FirstMember(mapData, "objects", "Objects", "<objects>k__BackingField")
			?? InvokeNoArg(mapData, "get_objects", "Method_Public_get_List_1_ObjectGroup_0");
	}

	private static void DumpObjectsSummary(StringBuilder sb, object mapData)
	{
		var objects = GetObjectsList(mapData);
		if (objects == null)
		{
			sb.Append("\nobjects=null");
			return;
		}
		var groups = new List<object>(EnumerateIl2CppList(objects));
		sb.Append("\nobjectsType=").Append(objects.GetType().FullName ?? "?")
			.Append(" groupCount=").Append(groups.Count);
		var sample = Math.Min(3, groups.Count);
		for (var g = 0; g < sample; g++)
		{
			var group = groups[g];
			if (group == null)
			{
				sb.Append("\n group[").Append(g).Append("]=null");
				continue;
			}
			sb.Append("\n group[").Append(g).Append("] type=").Append(group.GetType().Name);
			var sid = ReadGroupSid(group);
			if (!string.IsNullOrEmpty(sid))
				sb.Append(" sid=").Append(sid);
			var ids = FirstMember(group, "ids", "Ids", "field_Public_Il2CppStructArray_1_Int32_0")
				?? InvokeNoArg(group, "get_ids", "get_field_Public_Il2CppStructArray_1_Int32_0");
			var nodes = FirstMember(group, "nodes", "Nodes") ?? InvokeNoArg(group, "get_nodes");
			var rotations = FirstMember(group, "rotations", "Rotations") ?? InvokeNoArg(group, "get_rotations");
			if (ids != null)
				sb.Append(" idsCount=").Append(ToIntList(ids).Length);
			if (nodes != null)
				sb.Append(" nodesCount=").Append(ToIntList(nodes).Length);
			if (rotations != null)
				sb.Append(" rotationsCount=").Append(ToIntList(rotations).Length);
			if (string.IsNullOrEmpty(sid))
			{
				sb.Append(" fields=");
				foreach (var f in group.GetType().GetFields(All))
				{
					if (f.Name.StartsWith("Native", StringComparison.Ordinal))
						continue;
					object v = null;
					try { v = f.GetValue(group); } catch { continue; }
					sb.Append(f.Name).Append('=');
					if (v is string s)
						sb.Append(s);
					else if (v != null && v.GetType().IsPrimitive)
						sb.Append(v);
					else if (v != null)
						sb.Append(v.GetType().Name);
					sb.Append(';');
				}
			}
		}
	}

	private static void DumpObjectId(StringBuilder sb, object mapData, int objectId, int width)
	{
		sb.Append("\nobjectId=").Append(objectId);
		if (!TryFindObjectPlacement(mapData, objectId, out var sid, out var node, out var rotation))
		{
			sb.Append(" found=false");
			return;
		}
		AppendPlacement(sb, sid, node, rotation, width);
	}

	private static void DumpSid(StringBuilder sb, object mapData, string wantSid, int width)
	{
		sb.Append("\nsid=").Append(wantSid);
		var objects = GetObjectsList(mapData);
		if (objects == null)
		{
			sb.Append(" objects=null");
			return;
		}
		var count = 0;
		foreach (var group in EnumerateIl2CppList(objects))
		{
			if (group == null)
				continue;
			var sid = ReadGroupSid(group);
			if (!string.Equals(sid, wantSid, StringComparison.Ordinal))
				continue;
			var idList = ReadGroupIds(group);
			var nodeList = ReadGroupNodes(group);
			var rotList = ReadGroupRotations(group);
			for (var i = 0; i < Math.Max(idList.Length, Math.Max(nodeList.Length, 1)); i++)
			{
				count++;
				var id = i < idList.Length ? idList[i] : -1;
				var node = i < nodeList.Length ? nodeList[i] : -1;
				var rot = i < rotList.Length ? rotList[i] : -1;
				sb.Append(" [id=").Append(id);
				AppendPlacement(sb, sid, node, rot, width);
				sb.Append(']');
			}
		}
		sb.Append(" matchCount=").Append(count);
	}

	private static void DumpCityName(StringBuilder sb, object mapData, string cityName, int width)
	{
		sb.Append("\ncityName=").Append(cityName);
		var props = FirstMember(mapData, "objectsProperties", "ObjectsProperties", "<objectsProperties>k__BackingField", "cmtm", "cmsp")
			?? InvokeNoArg(mapData, "get_objectsProperties", "ogc", "cmwh", "Method_Public_get_ObjectsProperties_0");
		if (props == null)
		{
			sb.Append(" objectsProperties=null");
			return;
		}
		var cities = FirstMember(props, "propCities", "<propCities>k__BackingField", "_propCities")
			?? InvokeNoArg(props, "get_propCities", "oum", "cmxl", "Method_Public_get_List_1_PropCity_0");
		if (cities == null)
		{
			sb.Append(" propCities=null propsType=").Append(props.GetType().FullName ?? "?");
			return;
		}
		var hits = 0;
		foreach (var row in EnumerateIl2CppList(cities))
		{
			if (row == null)
				continue;
			var name = Convert.ToString(
				FirstMember(row, "customCityName", "CustomCityName", "name", "Name")
				?? InvokeNoArg(row, "get_customCityName", "get_name")
				?? "");
			if (!string.Equals(name, cityName, StringComparison.OrdinalIgnoreCase))
				continue;
			hits++;
			var id = FirstInt(row, "field_Public_Int32_0", "id", "<id>k__BackingField", "_id", "Id");
			if (id < 0)
				id = InvokeIntGetter(row, "get_field_Public_Int32_0", "get_id");
			sb.Append(" [propCities.id=").Append(id).Append(" name=").Append(name).Append(']');
			DumpRowFields(sb, row);
			if (id >= 0 && TryFindObjectPlacement(mapData, id, out var sid, out var node, out var rotation))
				AppendPlacement(sb, sid, node, rotation, width);
		}
		sb.Append(" cityHits=").Append(hits);
	}

	private static void DumpRowFields(StringBuilder sb, object row)
	{
		sb.Append(" rowFields=");
		foreach (var f in row.GetType().GetFields(All))
		{
			object v = null;
			try { v = f.GetValue(row); } catch { continue; }
			if (v == null)
				continue;
			if (v is string || v.GetType().IsPrimitive)
				sb.Append(f.Name).Append('=').Append(v).Append(';');
		}
	}

	private static void DumpPlacedObjects(StringBuilder sb, int width)
	{
		sb.Append("\nplaced=");
		var placedType =
			FindType("ObjectPublicObInbvByInSiLi1MaLiUnique")
			?? FindType("bvb")
			?? FindType("Hex.Map.bvb")
			?? FindType("bvc");
		if (placedType == null)
		{
			sb.Append("typeMissing");
			return;
		}
		var all = FindObjectsOfTypeDynamic(placedType);
		sb.Append("type=").Append(placedType.FullName).Append(" count=").Append(all == null ? 0 : all.Length);
		var hits = 0;
		if (all == null)
			return;
		foreach (var obj in all)
		{
			if (obj == null)
				continue;
			var sid = Convert.ToString(FirstMember(obj,
				"bvoy", "bvno", "sid", "objectSid",
				"field_Private_String_0", "field_Public_String_0",
				"<bvno>k__BackingField", "_bvno_k__BackingField") ?? "");
			var id = FirstInt(obj, "field_Public_Int32_0", "id", "bvoc", "<bvoc>k__BackingField", "bvms", "<bvms>k__BackingField");
			var node = FirstInt(obj,
				"<bvod>k__BackingField", "_bvod_k__BackingField", "bvod",
				"<bvmt>k__BackingField", "_bvmt_k__BackingField", "bvmt",
				"<bvqf>k__BackingField", "_bvqf_k__BackingField", "bvqf",
				"node", "<node>k__BackingField");
			var nameHit = false;
			string goName = null;
			try
			{
				var go = obj as Component;
				goName = go != null ? go.gameObject.name : obj.name;
				if (!string.IsNullOrEmpty(goName) && goName.IndexOf("castle_city", StringComparison.OrdinalIgnoreCase) >= 0)
					nameHit = true;
				if (!string.IsNullOrEmpty(goName) && goName.IndexOf("Caryatid", StringComparison.OrdinalIgnoreCase) >= 0)
					nameHit = true;
				if (!string.IsNullOrEmpty(goName) && goName.IndexOf("landon", StringComparison.OrdinalIgnoreCase) >= 0)
					nameHit = true;
			}
			catch { /* ignore */ }

			var sidHit = string.Equals(sid, LandonCastleSid, StringComparison.Ordinal)
				|| (!string.IsNullOrEmpty(sid) && sid.IndexOf("castle_city", StringComparison.OrdinalIgnoreCase) >= 0)
				|| (!string.IsNullOrEmpty(sid) && sid.IndexOf("landon", StringComparison.OrdinalIgnoreCase) >= 0);
			var idHit = id == CaryatidObjectId;
			if (!sidHit && !idHit && !nameHit)
				continue;
			hits++;
			sb.Append(" [id=").Append(id).Append(" sid=").Append(string.IsNullOrEmpty(sid) ? "?" : sid)
				.Append(" node=").Append(node);
			if (node >= 0)
				sb.Append(" xy=(").Append(node % width).Append(',').Append(node / width).Append(')');
			try
			{
				var go = obj as Component;
				if (go != null)
				{
					var p = go.transform.position;
					sb.Append(" world=(")
						.Append(p.x.ToString("0.###")).Append(',')
						.Append(p.y.ToString("0.###")).Append(',')
						.Append(p.z.ToString("0.###")).Append(')')
						.Append(" go=").Append(goName ?? go.gameObject.name);
				}
			}
			catch { /* ignore */ }
			sb.Append(']');
			if (hits >= 12)
				break;
		}
		sb.Append(" placedHits=").Append(hits);
	}

	private static UnityEngine.Object[] FindObjectsOfTypeDynamic(Type objectType)
	{
		if (objectType == null)
			return Array.Empty<UnityEngine.Object>();
		foreach (var method in typeof(UnityEngine.Object).GetMethods(BindingFlags.Static | BindingFlags.Public))
		{
			if (!string.Equals(method.Name, "FindObjectsOfType", StringComparison.Ordinal))
				continue;
			if (!method.IsGenericMethodDefinition)
				continue;
			if (method.GetGenericArguments().Length != 1)
				continue;
			var ps = method.GetParameters();
			try
			{
				if (ps.Length == 1 && ps[0].ParameterType == typeof(bool))
				{
					var closed = method.MakeGenericMethod(objectType);
					return closed.Invoke(null, new object[] { true }) as UnityEngine.Object[]
						?? Array.Empty<UnityEngine.Object>();
				}
				if (ps.Length == 0)
				{
					var closed = method.MakeGenericMethod(objectType);
					return closed.Invoke(null, null) as UnityEngine.Object[]
						?? Array.Empty<UnityEngine.Object>();
				}
			}
			catch { /* try next overload */ }
		}
		var resourcesMethod = typeof(Resources).GetMethod("FindObjectsOfTypeAll", All, null, new[] { typeof(Type) }, null);
		if (resourcesMethod != null)
		{
			try
			{
				return resourcesMethod.Invoke(null, new object[] { objectType }) as UnityEngine.Object[]
					?? Array.Empty<UnityEngine.Object>();
			}
			catch { /* fall through */ }
		}
		return Array.Empty<UnityEngine.Object>();
	}

	private static int InvokeIntGetter(object obj, params string[] names)
	{
		if (obj == null)
			return -1;
		foreach (var name in names)
		{
			MethodInfo method = null;
			for (var t = obj.GetType(); t != null && method == null; t = t.BaseType)
			{
				try { method = t.GetMethod(name, All, null, Type.EmptyTypes, null); }
				catch { method = null; }
			}
			if (method == null)
				continue;
			try
			{
				var value = method.Invoke(obj, null);
				if (value != null)
					return Convert.ToInt32(value);
			}
			catch { /* try next */ }
		}
		return -1;
	}

	private static void AppendPlacement(StringBuilder sb, string sid, int node, int rotation, int width)
	{
		sb.Append(" sid=").Append(sid ?? "?")
			.Append(" node=").Append(node)
			.Append(" xy=(").Append(node >= 0 ? (node % width).ToString() : "?")
			.Append(',').Append(node >= 0 ? (node / width).ToString() : "?").Append(')')
			.Append(" rotation=").Append(rotation);
	}

	private static bool TryFindObjectPlacement(object mapData, int objectId, out string sid, out int node, out int rotation)
	{
		sid = null;
		node = -1;
		rotation = -1;
		var objects = GetObjectsList(mapData);
		if (objects == null)
			return false;
		foreach (var group in EnumerateIl2CppList(objects))
		{
			if (group == null)
				continue;
			var ids = ReadGroupIds(group);
			var nodes = ReadGroupNodes(group);
			var rotations = ReadGroupRotations(group);
			for (var i = 0; i < ids.Length; i++)
			{
				if (ids[i] != objectId)
					continue;
				sid = ReadGroupSid(group);
				node = i < nodes.Length ? nodes[i] : -1;
				rotation = i < rotations.Length ? rotations[i] : -1;
				return true;
			}
		}
		return false;
	}

	private static string ReadGroupSid(object group)
	{
		var value = FirstMember(group, "sid", "Sid", "field_Public_String_0")
			?? InvokeNoArg(group, "get_sid", "get_field_Public_String_0");
		return Convert.ToString(value ?? "");
	}

	private static int[] ReadGroupIds(object group)
	{
		return ToIntList(FirstMember(group, "ids", "Ids", "field_Public_Il2CppStructArray_1_Int32_0")
			?? InvokeNoArg(group, "get_ids", "get_field_Public_Il2CppStructArray_1_Int32_0"));
	}

	private static int[] ReadGroupNodes(object group)
	{
		return ToIntList(FirstMember(group, "nodes", "Nodes") ?? InvokeNoArg(group, "get_nodes"));
	}

	private static int[] ReadGroupRotations(object group)
	{
		return ToIntList(FirstMember(group, "rotations", "Rotations") ?? InvokeNoArg(group, "get_rotations"));
	}

	private static object FindActiveMap(StringBuilder sb)
	{
		var cameraType = FindType("BhWorldCamera") ?? FindType("Hex.BhWorldCamera");
		if (cameraType == null)
		{
			sb.Append(" worldCameraType=missing");
			return null;
		}
		var singletonGetter = cameraType.GetMethod("Method_Public_Static_get_BhWorldCamera_PDM_0", All, null, Type.EmptyTypes, null);
		if (singletonGetter == null)
		{
			sb.Append(" worldCameraSingleton=missing");
			return null;
		}
		var camera = singletonGetter.Invoke(null, null);
		if (camera == null)
		{
			sb.Append(" worldCamera=null");
			return null;
		}
		var currentMapGetter = cameraType.GetMethod("Method_Public_Map_0", All, null, Type.EmptyTypes, null);
		if (currentMapGetter == null)
		{
			sb.Append(" currentMapGetter=missing");
			return null;
		}
		return currentMapGetter.Invoke(camera, null);
	}

	private static object GetMapData(object map, StringBuilder sb)
	{
		var direct = FirstMember(map, "mapData_", "mapData");
		if (direct != null)
			return direct;
		var getter = map.GetType().GetMethod("Method_Public_get_MapData_0", All, null, Type.EmptyTypes, null);
		if (getter == null)
		{
			sb.Append(" mapDataGetter=missing");
			return null;
		}
		return getter.Invoke(map, null);
	}

	private static Type FindType(string name)
	{
		foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
		{
			Type[] types;
			try { types = assembly.GetTypes(); }
			catch { continue; }
			foreach (var type in types)
			{
				if (string.Equals(type.Name, name, StringComparison.Ordinal)
				    || string.Equals(type.FullName, name, StringComparison.Ordinal))
					return type;
			}
		}
		return null;
	}

	private static object GetMember(object obj, string name)
	{
		if (obj == null || string.IsNullOrEmpty(name))
			return null;
		var type = obj.GetType();
		for (var t = type; t != null; t = t.BaseType)
		{
			FieldInfo field;
			try { field = t.GetField(name, All); }
			catch { field = null; }
			if (field != null)
				return field.GetValue(obj);
		}
		for (var t = type; t != null; t = t.BaseType)
		{
			PropertyInfo prop;
			try { prop = t.GetProperty(name, All); }
			catch { prop = null; }
			if (prop != null && prop.GetIndexParameters().Length == 0)
			{
				try { return prop.GetValue(obj, null); }
				catch { return null; }
			}
		}
		return null;
	}

	private static object FirstMember(object obj, params string[] names)
	{
		foreach (var name in names)
		{
			var value = GetMember(obj, name);
			if (value != null)
				return value;
		}
		return null;
	}

	private static string FirstString(object obj, params string[] names)
	{
		foreach (var name in names)
		{
			var value = GetMember(obj, name);
			if (value is string s && !string.IsNullOrEmpty(s))
				return s;
			if (name.StartsWith("get_", StringComparison.Ordinal))
			{
				var m = obj.GetType().GetMethod(name, All, null, Type.EmptyTypes, null);
				if (m != null)
				{
					try
					{
						var v = m.Invoke(obj, null) as string;
						if (!string.IsNullOrEmpty(v))
							return v;
					}
					catch { /* ignore */ }
				}
			}
		}
		return null;
	}

	private static int FirstInt(object obj, params string[] names)
	{
		foreach (var name in names)
		{
			var value = GetMember(obj, name);
			if (value == null)
				continue;
			try { return Convert.ToInt32(value); }
			catch { /* try next */ }
		}
		return -1;
	}

	private static object InvokeNoArg(object obj, params string[] names)
	{
		if (obj == null)
			return null;
		foreach (var name in names)
		{
			MethodInfo method = null;
			for (var t = obj.GetType(); t != null && method == null; t = t.BaseType)
			{
				try { method = t.GetMethod(name, All, null, Type.EmptyTypes, null); }
				catch { method = null; }
			}
			if (method == null)
				continue;
			try
			{
				var value = method.Invoke(obj, null);
				if (value != null)
					return value;
			}
			catch { /* try next */ }
		}
		return null;
	}

	private static IEnumerable<object> EnumerateIl2CppList(object listObj)
	{
		if (listObj == null)
			yield break;
		var type = listObj.GetType();
		PropertyInfo countProp = null;
		MethodInfo countGetter = null;
		MethodInfo itemGetter = null;
		for (var t = type; t != null && countProp == null; t = t.BaseType)
		{
			try { countProp = t.GetProperty("Count", All); }
			catch { countProp = null; }
		}
		if (countProp == null)
		{
			for (var t = type; t != null && countGetter == null; t = t.BaseType)
			{
				try { countGetter = t.GetMethod("get_Count", All, null, Type.EmptyTypes, null); }
				catch { countGetter = null; }
			}
		}
		for (var t = type; t != null && itemGetter == null; t = t.BaseType)
		{
			try { itemGetter = t.GetMethod("get_Item", All, null, new[] { typeof(int) }, null); }
			catch { itemGetter = null; }
		}
		int count;
		if (countProp != null)
			count = Convert.ToInt32(countProp.GetValue(listObj, null));
		else if (countGetter != null)
			count = Convert.ToInt32(countGetter.Invoke(listObj, null));
		else
			count = -1;

		if (itemGetter != null && count >= 0)
		{
			for (var i = 0; i < count; i++)
			{
				object item = null;
				try { item = itemGetter.Invoke(listObj, new object[] { i }); }
				catch { item = null; }
				if (item != null)
					yield return item;
			}
			yield break;
		}

		if (listObj is IEnumerable enumerable)
		{
			foreach (var item in enumerable)
			{
				if (item != null)
					yield return item;
			}
		}
	}

	private static int[] ToIntList(object value)
	{
		if (value == null)
			return Array.Empty<int>();
		if (value is int[] arr)
			return arr;
		var list = new List<int>();
		// Il2CppStructArray / List<int>
		var countObj = GetMember(value, "Count") ?? GetMember(value, "Length");
		MethodInfo itemGetter = null;
		for (var t = value.GetType(); t != null && itemGetter == null; t = t.BaseType)
		{
			try { itemGetter = t.GetMethod("get_Item", All, null, new[] { typeof(int) }, null); }
			catch { itemGetter = null; }
		}
		if (countObj != null && itemGetter != null)
		{
			var count = Convert.ToInt32(countObj);
			for (var i = 0; i < count; i++)
			{
				try { list.Add(Convert.ToInt32(itemGetter.Invoke(value, new object[] { i }))); }
				catch { /* skip */ }
			}
			return list.ToArray();
		}
		foreach (var item in EnumerateIl2CppList(value))
		{
			if (item == null)
				continue;
			try { list.Add(Convert.ToInt32(item)); }
			catch { /* skip */ }
		}
		if (list.Count == 0 && value is IEnumerable enumerable)
		{
			foreach (var item in enumerable)
			{
				if (item == null)
					continue;
				try { list.Add(Convert.ToInt32(item)); }
				catch { /* skip */ }
			}
		}
		return list.ToArray();
	}

	private static string Escape(string value)
	{
		if (string.IsNullOrEmpty(value))
			return "";
		return value
			.Replace("\\", "\\\\")
			.Replace("\"", "\\\"")
			.Replace("\r", "\\r")
			.Replace("\n", "\\n")
			.Replace("\t", "\\t");
	}
}
