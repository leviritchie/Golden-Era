using System.Collections;
using System.Reflection;

namespace OfflineUnlockMod;

/// <summary>
/// Enumerates managed collections, Il2Cpp arrays and Il2Cpp <c>List&lt;T&gt;</c> alike. Il2CppInterop's
/// Il2CppSystem.Collections.Generic.List&lt;T&gt; is not a System.Collections.IEnumerable, so a plain
/// <c>x is IEnumerable</c> check silently treats it as "not a collection"; this falls back to Count/Length + get_Item.
/// </summary>
internal static class Il2CppCollections
{
	private const BindingFlags Flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;

	internal static bool TryEnumerate(object collection, out IEnumerable enumerable)
	{
		enumerable = null;
		if (collection == null || collection is string)
			return false;
		if (collection is IEnumerable direct)
		{
			enumerable = direct;
			return true;
		}
		var type = collection.GetType();
		PropertyInfo countProperty;
		MethodInfo indexer;
		try
		{
			countProperty = type.GetProperty("Count", Flags) ?? type.GetProperty("Length", Flags);
			indexer = type.GetMethod("get_Item", Flags, null, new[] { typeof(int) }, null);
		}
		catch (AmbiguousMatchException)
		{
			return false;
		}
		if (countProperty?.GetMethod == null || indexer == null)
			return false;
		enumerable = EnumerateIndexed(collection, countProperty, indexer);
		return true;
	}

	private static IEnumerable EnumerateIndexed(object collection, PropertyInfo countProperty, MethodInfo indexer)
	{
		int count;
		try { count = System.Convert.ToInt32(countProperty.GetValue(collection)); }
		catch { yield break; }
		var args = new object[1];
		for (var i = 0; i < count; i++)
		{
			args[0] = i;
			object item;
			try { item = indexer.Invoke(collection, args); }
			catch { yield break; }
			yield return item;
		}
	}
}
