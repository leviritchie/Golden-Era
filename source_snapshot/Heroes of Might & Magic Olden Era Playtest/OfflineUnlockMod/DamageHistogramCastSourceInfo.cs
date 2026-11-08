using System;
using System.Collections.Generic;
using System.Reflection;

namespace OfflineUnlockMod;

internal static class DamageHistogramCastSourceInfo
{
	internal static bool TryReadPrimaryTriggerCounter(object castSource, out bool triggerCounter, out string source)
	{
		triggerCounter = false;
		source = null;
		if (castSource == null)
		{
			return false;
		}

		foreach (var dealer in EnumerateDealerConfigs(castSource, GameSymbols.DamageCastSource.PrimaryDamageDealerGetters))
		{
			if (TryReadBoolMember(dealer, GameSymbols.DamageCastSource.TriggerCounterMember, out triggerCounter))
			{
				source = dealer.GetType().FullName + "." + GameSymbols.DamageCastSource.TriggerCounterMember;
				return true;
			}
		}
		return false;
	}

	internal static List<string> CollectAttackPatternSids(object castSource)
	{
		var sids = new List<string>(4);
		if (castSource == null)
		{
			return sids;
		}

		AddAttackPatternSids(sids, castSource, GameSymbols.DamageCastSource.PrimaryDamageDealerGetters);
		AddAttackPatternSids(sids, castSource, GameSymbols.DamageCastSource.SecondaryDamageDealerGetters);
		return sids;
	}

	internal static bool TryReadCastSourceId(object castSource, out int id)
	{
		id = 0;
		if (castSource == null)
		{
			return false;
		}

		foreach (var name in GameSymbols.DamageCastSource.CastSourceIdGetters)
		{
			try
			{
				var value = InvokeNoArg(castSource, name);
				if (value == null)
				{
					continue;
				}
				id = Convert.ToInt32(value);
				return true;
			}
			catch
			{
			}
		}
		return false;
	}

	private static void AddAttackPatternSids(List<string> sids, object castSource, string[] getterNames)
	{
		foreach (var dealer in EnumerateDealerConfigs(castSource, getterNames))
		{
			var sid = ReadStringMember(dealer, GameSymbols.DamageCastSource.AttackPatternSidMember);
			if (!string.IsNullOrEmpty(sid))
			{
				sids.Add(sid);
			}
		}
	}

	private static IEnumerable<object> EnumerateDealerConfigs(object castSource, string[] getterNames)
	{
		foreach (var getterName in getterNames)
		{
			object wrapper;
			try
			{
				wrapper = InvokeNoArg(castSource, getterName);
			}
			catch
			{
				continue;
			}

			if (wrapper == null)
			{
				continue;
			}

			var yieldedNested = false;
			foreach (var memberName in GameSymbols.DamageCastSource.RuntimeDealerMembers)
			{
				var dealer = ReadMember(wrapper, memberName);
				if (dealer == null)
				{
					continue;
				}
				yieldedNested = true;
				yield return dealer;
			}

			if (!yieldedNested)
			{
				yield return wrapper;
			}
		}
	}

	private static object InvokeNoArg(object instance, string name)
	{
		if (instance == null || string.IsNullOrEmpty(name))
		{
			return null;
		}
		return instance.GetType()
			.GetMethod(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null)
			?.Invoke(instance, Array.Empty<object>());
	}

	private static object ReadMember(object owner, string name)
	{
		if (owner == null || string.IsNullOrEmpty(name))
		{
			return null;
		}
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var type = owner.GetType();
		var field = type.GetField(name, flags);
		if (field != null)
		{
			return field.GetValue(owner);
		}
		var property = type.GetProperty(name, flags);
		return property != null && property.GetIndexParameters().Length == 0
			? property.GetValue(owner, null)
			: null;
	}

	private static string ReadStringMember(object owner, string name)
	{
		return ReadMember(owner, name) as string;
	}

	private static bool TryReadBoolMember(object owner, string name, out bool value)
	{
		value = false;
		var raw = ReadMember(owner, name);
		if (raw == null)
		{
			return false;
		}
		try
		{
			value = Convert.ToBoolean(raw);
			return true;
		}
		catch
		{
			return false;
		}
	}
}
