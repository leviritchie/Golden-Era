using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using System.Text;

/// <summary>
/// Read-only live probe for the current map's propHeroes rows and DataObjects.prisonObjs.
/// This is source-prepared diagnostic evidence, not a gameplay mutation.
/// </summary>
public static class PrisonBindingProbe20260730
{
	private const BindingFlags All = BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;

	public static string Run(string requestJson)
	{
		try
		{
			var sb = new StringBuilder();
			var map = FindActiveMap(sb);
			var mapData = map == null ? null : GetMember(map, "mapData_", "mapData", "get_mapData", "get_MapData");
			var data = FindSessionData(sb);
			var dataObjects = data == null ? null : GetMember(data, "objects", "get_objects");
			var prisons = dataObjects == null ? null : GetMember(dataObjects, "prisonObjs", "get_prisonObjs");

			sb.Append("mapType=").Append(TypeName(map));
			sb.Append(" mapDataType=").Append(TypeName(mapData));
			sb.Append(" dataType=").Append(TypeName(data));
			sb.Append(" dataObjectsType=").Append(TypeName(dataObjects));
			sb.Append(" prisonListType=").Append(TypeName(prisons));
			sb.Append(" prisonCount=").Append(Count(prisons));
			sb.Append("\nmapPropHeroes=");
			AppendMapPropHeroes(sb, mapData);
			sb.Append("\ndataPrisons=");
			AppendDataPrisons(sb, prisons);
			return "{\"ok\":true,\"text\":\"" + Escape(sb.ToString()) + "\"}";
		}
		catch (Exception ex)
		{
			return "{\"ok\":false,\"exception\":\"" + Escape(ex.GetType().Name)
				+ "\",\"message\":\"" + Escape(ex.Message)
				+ "\",\"stack\":\"" + Escape(ex.StackTrace ?? "") + "\"}";
		}
	}

	private static object FindActiveMap(StringBuilder sb)
	{
		var cameraType = FindType("BhWorldCamera") ?? FindType("Hex.BhWorldCamera");
		if (cameraType == null)
		{
			sb.Append(" worldCameraType=missing");
			return null;
		}

		var singleton = FindNoArgMethod(cameraType, "Method_Public_Static_get_BhWorldCamera_PDM_0", "get_Instance");
		if (singleton == null)
		{
			sb.Append(" worldCameraSingleton=missing");
			return null;
		}
		var camera = singleton.IsStatic ? singleton.Invoke(null, null) : null;
		if (camera == null)
		{
			sb.Append(" worldCamera=null");
			return null;
		}

		var mapGetter = FindNoArgMethod(camera.GetType(), "Method_Public_Map_0", "get_map", "get_Map");
		if (mapGetter == null)
		{
			sb.Append(" currentMapGetter=missing");
			return null;
		}
		return mapGetter.Invoke(camera, null);
	}

	private static object FindSessionData(StringBuilder sb)
	{
		var holderType = FindType("ObjectPublicAbstractSealedSecaMaDacaStObHaca1Unique");
		if (holderType == null)
		{
			sb.Append(" sessionHolderType=missing");
			return null;
		}

		var data = GetStaticMember(holderType,
			"field_Private_Static_Data_0",
			"get_field_Private_Static_Data_0",
			"data",
			"get_data",
			"field_Public_Data_0",
			"get_field_Public_Data_0");
		if (data == null)
			sb.Append(" sessionData=missing");
		return data;
	}

	private static void AppendMapPropHeroes(StringBuilder sb, object mapData)
	{
		var properties = GetMember(mapData, "objectsProperties", "get_objectsProperties");
		var rows = GetMember(properties, "propHeroes", "get_propHeroes");
		if (rows == null)
		{
			sb.Append("null");
			return;
		}

		var list = Enumerate(rows);
		sb.Append('[');
		for (var i = 0; i < list.Count; i++)
		{
			if (i > 0)
				sb.Append(',');
			var row = list[i];
			sb.Append("{\"id\":").Append(IntValue(row, -1, "id", "get_id", "field_Public_Int32_1"))
				.Append(",\"heroSid\":\"").Append(Escape(StringValue(row, "heroSid", "get_heroSid", "field_Public_String_0")))
				.Append("\",\"type\":").Append(IntValue(row, -1, "type", "get_type", "field_Public_Int32_0"))
				.Append('}');
		}
		sb.Append(']');
	}

	private static void AppendDataPrisons(StringBuilder sb, object prisons)
	{
		var list = Enumerate(prisons);
		sb.Append('[');
		for (var i = 0; i < list.Count; i++)
		{
			if (i > 0)
				sb.Append(',');
			var prison = list[i];
			sb.Append("{\"type\":\"").Append(Escape(TypeName(prison)))
				.Append("\",\"id\":").Append(IntValue(prison, -1, "idMapObject", "get_idMapObject", "field_Public_Int32_0"))
				.Append(",\"configSid\":\"").Append(Escape(StringValue(prison, "configSid", "get_configSid", "sidConfig", "get_sidConfig")))
				.Append("\",\"heroSid\":\"").Append(Escape(StringValue(prison, "heroSid", "get_heroSid")))
				.Append("\"}");
		}
		sb.Append(']');
	}

	private static Type FindType(string name)
	{
		foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
		{
			Type[] types;
			try { types = assembly.GetTypes(); }
			catch { continue; }
			for (var i = 0; i < types.Length; i++)
			{
				var type = types[i];
				if (string.Equals(type.Name, name, StringComparison.Ordinal)
				    || string.Equals(type.FullName, name, StringComparison.Ordinal))
					return type;
			}
		}
		return null;
	}

	private static MethodInfo FindNoArgMethod(Type type, params string[] names)
	{
		if (type == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var method = type.GetMethod(names[i], All, null, Type.EmptyTypes, null);
			if (method != null)
				return method;
		}
		return null;
	}

	private static object GetStaticMember(Type type, params string[] names)
	{
		if (type == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var field = type.GetField(names[i], All);
			if (field != null && field.IsStatic)
			{
				try { return field.GetValue(null); }
				catch { }
			}
			var property = type.GetProperty(names[i], All);
			if (property != null && property.GetIndexParameters().Length == 0
			    && property.GetGetMethod(true) != null && property.GetGetMethod(true).IsStatic)
			{
				try { return property.GetValue(null, null); }
				catch { }
			}
			var method = type.GetMethod(names[i], All, null, Type.EmptyTypes, null);
			if (method != null && method.IsStatic)
			{
				try { return method.Invoke(null, null); }
				catch { }
			}
		}
		return null;
	}

	private static object GetMember(object target, params string[] names)
	{
		if (target == null)
			return null;
		var type = target.GetType();
		for (var i = 0; i < names.Length; i++)
		{
			var field = type.GetField(names[i], All);
			if (field != null)
			{
				try { return field.GetValue(target); }
				catch { }
			}
			var property = type.GetProperty(names[i], All);
			if (property != null && property.GetIndexParameters().Length == 0)
			{
				try { return property.GetValue(target, null); }
				catch { }
			}
			var method = type.GetMethod(names[i], All, null, Type.EmptyTypes, null);
			if (method != null)
			{
				try { return method.Invoke(target, null); }
				catch { }
			}
		}
		return null;
	}

	private static List<object> Enumerate(object value)
	{
		var result = new List<object>();
		if (value is IEnumerable enumerable && value is not string)
		{
			foreach (var item in enumerable)
				result.Add(item);
			return result;
		}

		if (value == null)
			return result;
		var count = IntValue(value, -1, "Count", "count", "_size", "get_Count");
		var indexer = value.GetType().GetMethod("get_Item", All, null, new[] { typeof(int) }, null)
			?? value.GetType().GetMethod("Get", All, null, new[] { typeof(int) }, null);
		if (count < 0 || indexer == null)
			return result;
		for (var i = 0; i < count; i++)
		{
			try { result.Add(indexer.Invoke(value, new object[] { i })); }
			catch { }
		}
		return result;
	}

	private static int Count(object value)
	{
		return value == null ? 0 : Enumerate(value).Count;
	}

	private static int IntValue(object target, int fallback, params string[] names)
	{
		var value = GetMember(target, names);
		if (value is int i)
			return i;
		if (value is long l)
			return (int)l;
		if (value is short s)
			return s;
		return fallback;
	}

	private static string StringValue(object target, params string[] names)
	{
		var value = GetMember(target, names);
		return value as string ?? "";
	}

	private static string TypeName(object value)
	{
		return value?.GetType().FullName ?? "null";
	}

	private static string Escape(string value)
	{
		if (value == null)
			return "";
		return value.Replace("\\", "\\\\")
			.Replace("\"", "\\\"")
			.Replace("\r", "\\r")
			.Replace("\n", "\\n")
			.Replace("\t", "\\t");
	}
}
