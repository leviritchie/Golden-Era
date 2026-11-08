using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using System.Text;
using UnityEngine.SceneManagement;

/// <summary>
/// Live read-only: current MapData fileMapName + markers[] / markersFreeId.
/// Confirms whether the installed invisible event-zone fix is loaded in-session.
/// </summary>
public static class MapMarkersProbe20260714
{
	private const BindingFlags All = BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;

	public static string Run(string requestJson)
	{
		var sb = new StringBuilder();
		try
		{
			sb.Append("scene=").Append(SceneManager.GetActiveScene().name ?? "?");
			var map = FindActiveMap(sb);
			if (map == null)
				return Ok(sb.Append(" map=null").ToString());

			var mapData = GetMapData(map, sb);
			if (mapData == null)
				return Ok(sb.Append(" mapData=null").ToString());

			var fileMapName = FirstString(mapData, "fileMapName", "get_fileMapName")
				?? FirstString(map, "fileMapName", "get_fileMapName")
				?? "?";
			sb.Append(" fileMapName=").Append(fileMapName);

			var sizeX = FirstInt(mapData, "sizeX_", "sizeX");
			if (sizeX < 0)
				sizeX = InvokeIntGetter(mapData, "get_sizeX_", "Method_Public_get_Int32_0", "get_sizeX");
			var width = sizeX > 0 ? sizeX : 160;
			sb.Append(" sizeX=").Append(sizeX);

			var markersFreeId = FirstInt(mapData, "markersFreeId", "MarkersFreeId");
			sb.Append(" markersFreeId=").Append(markersFreeId);

			var markers = FirstMember(mapData, "markers", "Markers", "<markers>k__BackingField")
				?? InvokeNoArg(mapData, "get_markers");
			if (markers == null)
				return Ok(sb.Append(" markers=null").ToString());

			var rows = new List<object>(EnumerateIl2CppList(markers));
			sb.Append(" markerCount=").Append(rows.Count);
			for (var i = 0; i < rows.Count; i++)
			{
				var row = rows[i];
				if (row == null)
				{
					sb.Append("\n marker[").Append(i).Append("]=null");
					continue;
				}
				var id = FirstInt(row, "id", "Id", "field_Public_Int32_0");
				var node = FirstInt(row, "node", "Node", "field_Public_Int32_1");
				var sid = FirstString(row, "sid", "Sid", "field_Public_String_0", "get_sid") ?? "?";
				var v = FirstString(row, "v", "V", "field_Public_String_1") ?? "";
				var x = node >= 0 && width > 0 ? node % width : -1;
				var y = node >= 0 && width > 0 ? node / width : -1;
				sb.Append("\n marker[").Append(i).Append("] id=").Append(id)
					.Append(" node=").Append(node)
					.Append(" xy=(").Append(x).Append(',').Append(y).Append(')')
					.Append(" sid=").Append(sid)
					.Append(" v=").Append(v);
			}

			DumpPropMarkers(sb, mapData);
			return Ok(sb.ToString());
		}
		catch (Exception ex)
		{
			return "{\"ok\":false,\"exception\":\"" + Escape(ex.GetType().Name)
				+ "\",\"message\":\"" + Escape(ex.Message)
				+ "\",\"stack\":\"" + Escape(ex.StackTrace ?? "") + "\"}";
		}
	}

	private static void DumpPropMarkers(StringBuilder sb, object mapData)
	{
		var props = FirstMember(mapData, "objectsProperties", "ObjectsProperties")
			?? InvokeNoArg(mapData, "get_objectsProperties");
		if (props == null)
		{
			sb.Append("\nobjectsProperties=null");
			return;
		}
		var propMarkers = FirstMember(props, "propMarkers", "PropMarkers")
			?? InvokeNoArg(props, "get_propMarkers");
		if (propMarkers == null)
		{
			sb.Append("\npropMarkers=null");
			return;
		}
		var rows = new List<object>(EnumerateIl2CppList(propMarkers));
		sb.Append("\npropMarkerCount=").Append(rows.Count);
		for (var i = 0; i < Math.Min(rows.Count, 8); i++)
		{
			var row = rows[i];
			if (row == null)
				continue;
			sb.Append("\n propMarker[").Append(i).Append("]")
				.Append(" type=").Append(FirstInt(row, "type", "Type", "field_Public_Int32_0"))
				.Append(" id=").Append(FirstInt(row, "id", "Id", "field_Public_Int32_1"))
				.Append(" isDelete=").Append(FirstBool(row, "isDelete", "IsDelete"))
				.Append(" isActivate=").Append(FirstBool(row, "isActivate", "IsActivate"));
		}
	}

	private static string Ok(string text)
	{
		return "{\"ok\":true,\"text\":\"" + Escape(text) + "\"}";
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

	private static IEnumerable<object> EnumerateIl2CppList(object list)
	{
		if (list == null)
			yield break;
		if (list is IEnumerable enumerable && list is not string)
		{
			foreach (var item in enumerable)
				yield return item;
			yield break;
		}
		var count = FirstInt(list, "Count", "count", "_size");
		if (count < 0)
		{
			var countObj = InvokeNoArg(list, "get_Count", "get_count");
			if (countObj is int c)
				count = c;
		}
		var indexer = list.GetType().GetMethod("get_Item", All, null, new[] { typeof(int) }, null)
			?? list.GetType().GetMethod("Get", All, null, new[] { typeof(int) }, null);
		if (indexer == null || count < 0)
			yield break;
		for (var i = 0; i < count; i++)
			yield return indexer.Invoke(list, new object[] { i });
	}

	private static object FirstMember(object target, params string[] names)
	{
		if (target == null)
			return null;
		var type = target.GetType();
		foreach (var name in names)
		{
			var field = type.GetField(name, All);
			if (field != null)
			{
				try { return field.GetValue(target); } catch { }
			}
			var prop = type.GetProperty(name, All);
			if (prop != null && prop.GetIndexParameters().Length == 0)
			{
				try { return prop.GetValue(target, null); } catch { }
			}
		}
		return null;
	}

	private static object InvokeNoArg(object target, params string[] names)
	{
		if (target == null)
			return null;
		var type = target.GetType();
		foreach (var name in names)
		{
			var method = type.GetMethod(name, All, null, Type.EmptyTypes, null);
			if (method == null)
				continue;
			try { return method.Invoke(target, null); } catch { }
		}
		return null;
	}

	private static string FirstString(object target, params string[] names)
	{
		foreach (var name in names)
		{
			var value = FirstMember(target, name) ?? InvokeNoArg(target, name);
			if (value is string s && !string.IsNullOrWhiteSpace(s))
				return s;
		}
		return null;
	}

	private static int FirstInt(object target, params string[] names)
	{
		foreach (var name in names)
		{
			var value = FirstMember(target, name) ?? InvokeNoArg(target, name);
			if (value is int i)
				return i;
			if (value is long l)
				return (int)l;
			if (value is short s)
				return s;
			if (value is byte b)
				return b;
		}
		return -1;
	}

	private static bool? FirstBool(object target, params string[] names)
	{
		foreach (var name in names)
		{
			var value = FirstMember(target, name) ?? InvokeNoArg(target, name);
			if (value is bool b)
				return b;
		}
		return null;
	}

	private static int InvokeIntGetter(object target, params string[] names)
	{
		var value = InvokeNoArg(target, names);
		if (value is int i)
			return i;
		return -1;
	}

	private static string Escape(string value)
	{
		return (value ?? string.Empty)
			.Replace("\\", "\\\\")
			.Replace("\"", "\\\"")
			.Replace("\r", "\\r")
			.Replace("\n", "\\n");
	}
}
