using System;
using System.Reflection;
using UnityEngine;

namespace OfflineUnlockMod;

internal static class Homm3NativeSpriteCatalogRegistrar
{
	internal delegate bool SpriteResolver(string key, out Sprite sprite);

	// Runtime probe on June 24 proved cko.sfo resolves keys from dictionary 0 before returning WIP; keep these symbols exact and fail closed if they drift.
	// The names live in GameSymbols.NativeSpriteCatalog so each build's scope (or refusal sentinel) applies.
	internal static string ResolverTypeName => GameSymbols.NativeSpriteCatalog.ResolverTypeHints[0];
	internal static string ResolverSingletonMethodName => GameSymbols.NativeSpriteCatalog.ResolverSingleton.NameHints[0];
	internal static string SpriteCatalogGetterName => GameSymbols.NativeSpriteCatalog.SpriteCatalogGetter.NameHints[0];
	internal static string ResolverMethodName => GameSymbols.NativeSpriteCatalog.ResolveSprite.NameHints[0];
	private static readonly object SyncRoot = new();
	private static object _resolverInstance;
	private static object _spriteCatalog;
	private static int _loggedRegister;
	private static int _loggedMiss;

	internal static bool TryEnsureRegistered(string key, SpriteResolver resolveSprite, out Sprite sprite, out string reason)
	{
		sprite = null;
		reason = null;
		if (string.IsNullOrWhiteSpace(key))
		{
			reason = "empty-key";
			return false;
		}
		if (resolveSprite == null)
		{
			reason = "missing-sprite-resolver";
			return false;
		}

		var sid = key.Trim();
		lock (SyncRoot)
		{
			if (!TryGetSpriteCatalog(out var catalog, out reason))
				return false;

			var hadEntry = CatalogContains(catalog, sid);
			if (hadEntry)
			{
				sprite = GetCatalogSprite(catalog, sid);
				if (sprite)
					return true;
			}

			if (!resolveSprite(sid, out sprite) || !sprite)
			{
				reason = "sprite-unresolved";
				return false;
			}

			// An entry whose sprite was freed must be overwritten: Add would throw on the existing
			// key and leave the native resolver returning the dead sprite (a blank icon).
			if (hadEntry)
			{
				if (!SetCatalogSprite(catalog, sid, sprite, out reason))
					return false;
				Plugin.LogSource?.LogWarning("Homm3NativeSpriteCatalog: replaced freed sprite for key '" + sid + "' with '" + sprite.name + "'.");
				return true;
			}

			if (!AddCatalogSprite(catalog, sid, sprite, out reason))
				return false;

			if (_loggedRegister++ < 40)
				Plugin.LogSource?.LogInfo("Homm3NativeSpriteCatalog: registered key '" + sid + "' as sprite '" + sprite.name + "'.");
			return true;
		}
	}

	private static bool TryGetSpriteCatalog(out object catalog, out string reason)
	{
		catalog = null;
		reason = null;
		if (_spriteCatalog != null)
		{
			catalog = _spriteCatalog;
			return true;
		}

		if (!TryGetResolverInstance(out var resolver, out reason))
			return false;

		var getter = resolver.GetType().GetMethod(
			SpriteCatalogGetterName,
			BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly,
			null,
			Type.EmptyTypes,
			null);
		if (getter == null)
		{
			reason = "missing-catalog-getter:" + SpriteCatalogGetterName;
			LogMiss(reason);
			return false;
		}

		try
		{
			catalog = getter.Invoke(resolver, null);
		}
		catch (Exception ex)
		{
			reason = "catalog-getter-failed:" + ex.GetType().Name;
			LogMiss(reason);
			return false;
		}

		if (catalog == null)
		{
			reason = "catalog-null";
			LogMiss(reason);
			return false;
		}

		_spriteCatalog = catalog;
		return true;
	}

	private static bool TryGetResolverInstance(out object resolver, out string reason)
	{
		resolver = _resolverInstance;
		reason = null;
		if (resolver != null)
			return true;

		var type = ModActions.GetHexType(ResolverTypeName);
		if (type == null)
		{
			foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
			{
				try
				{
					type = asm.GetType(ResolverTypeName, throwOnError: false);
					if (type != null)
						break;
				}
				catch
				{
				}
			}
		}
		if (type == null)
		{
			reason = "missing-resolver-type:" + ResolverTypeName;
			LogMiss(reason);
			return false;
		}

		var singleton = type.GetMethod(
			ResolverSingletonMethodName,
			BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.DeclaredOnly,
			null,
			Type.EmptyTypes,
			null);
		if (singleton == null)
		{
			reason = "missing-singleton:" + ResolverSingletonMethodName;
			LogMiss(reason);
			return false;
		}

		try
		{
			resolver = singleton.Invoke(null, null);
		}
		catch (Exception ex)
		{
			reason = "singleton-failed:" + ex.GetType().Name;
			LogMiss(reason);
			return false;
		}

		if (resolver == null)
		{
			reason = "resolver-null";
			LogMiss(reason);
			return false;
		}

		_resolverInstance = resolver;
		return true;
	}

	private static bool CatalogContains(object catalog, string key)
	{
		var method = catalog.GetType().GetMethod("ContainsKey", new[] { typeof(string) });
		if (method == null)
			return false;
		try
		{
			return method.Invoke(catalog, new object[] { key }) is bool result && result;
		}
		catch
		{
			return false;
		}
	}

	private static Sprite GetCatalogSprite(object catalog, string key)
	{
		var method = catalog.GetType().GetMethod("get_Item", new[] { typeof(string) });
		if (method == null)
			return null;
		try
		{
			return method.Invoke(catalog, new object[] { key }) as Sprite;
		}
		catch
		{
			return null;
		}
	}

	private static bool AddCatalogSprite(object catalog, string key, Sprite sprite, out string reason)
	{
		reason = null;
		var add = catalog.GetType().GetMethod("Add", new[] { typeof(string), typeof(Sprite) });
		if (add != null)
		{
			try
			{
				add.Invoke(catalog, new object[] { key, sprite });
				return true;
			}
			catch (TargetInvocationException) when (CatalogContains(catalog, key))
			{
				return true;
			}
			catch (Exception ex)
			{
				reason = "catalog-add-failed:" + ex.GetType().Name;
				LogMiss(reason);
				return false;
			}
		}

		return SetCatalogSprite(catalog, key, sprite, out reason);
	}

	private static bool SetCatalogSprite(object catalog, string key, Sprite sprite, out string reason)
	{
		reason = null;
		var setItem = catalog.GetType().GetMethod("set_Item", new[] { typeof(string), typeof(Sprite) });
		if (setItem == null)
		{
			reason = "catalog-add-missing";
			LogMiss(reason);
			return false;
		}
		try
		{
			setItem.Invoke(catalog, new object[] { key, sprite });
			return true;
		}
		catch (Exception ex)
		{
			reason = "catalog-set-failed:" + ex.GetType().Name;
			LogMiss(reason);
			return false;
		}
	}

	private static void LogMiss(string reason)
	{
		if (_loggedMiss++ >= 40)
			return;
		Plugin.LogSource?.LogWarning("Homm3NativeSpriteCatalog: " + reason + ".");
	}
}
