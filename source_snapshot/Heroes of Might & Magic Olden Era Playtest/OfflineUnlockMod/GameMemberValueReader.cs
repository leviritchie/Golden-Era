using System;
using System.Reflection;

namespace OfflineUnlockMod;

// Resolves exact runtime members only; a successful read does not prove gameplay behavior.
internal static class GameMemberValueReader
{
	private const BindingFlags MemberFlags = BindingFlags.Public | BindingFlags.NonPublic
		| BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly;

	internal static bool TryRead(object target, string[] names, out object value, out string failure)
	{
		value = null;
		failure = null;
		if (target == null || names == null)
			return false;

		var type = target.GetType();
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;

			var property = FindProperty(type, name, out var metadataFailure);
			if (metadataFailure != null)
			{
				failure = FormatFailure(type, name, "property metadata", metadataFailure);
				return false;
			}
			if (property != null)
			{
				bool canRead;
				try
				{
					canRead = property.GetMethod != null && property.GetIndexParameters().Length == 0;
				}
				catch (Exception ex)
				{
					failure = FormatFailure(type, name, "property metadata", ex);
					return false;
				}

				if (canRead)
				{
					try
					{
						value = property.GetValue(target, null);
					}
					catch (Exception ex)
					{
						failure = FormatFailure(type, name, "property getter", ex);
						return false;
					}
					if (value != null)
						return true;
				}
			}

			var field = FindField(type, name, out metadataFailure);
			if (metadataFailure != null)
			{
				failure = FormatFailure(type, name, "field metadata", metadataFailure);
				return false;
			}
			if (field != null)
			{
				try
				{
					value = field.GetValue(target);
				}
				catch (Exception ex)
				{
					failure = FormatFailure(type, name, "field read", ex);
					return false;
				}
				if (value != null)
					return true;
			}

			var method = FindParameterlessMethod(type, name, out metadataFailure);
			if (metadataFailure != null)
			{
				failure = FormatFailure(type, name, "method metadata", metadataFailure);
				return false;
			}
			if (method == null)
				continue;

			try
			{
				value = method.Invoke(target, Array.Empty<object>());
			}
			catch (Exception ex)
			{
				failure = FormatFailure(type, name, "method invocation", ex);
				return false;
			}
			if (value != null)
				return true;
		}

		return false;
	}

	private static PropertyInfo FindProperty(Type type, string name, out Exception failure)
	{
		failure = null;
		for (var current = type; current != null; current = current.BaseType)
		{
			try
			{
				var property = current.GetProperty(name, MemberFlags);
				if (property != null)
					return property;
			}
			catch (Exception ex)
			{
				failure = ex;
				return null;
			}
		}
		return null;
	}

	private static FieldInfo FindField(Type type, string name, out Exception failure)
	{
		failure = null;
		for (var current = type; current != null; current = current.BaseType)
		{
			try
			{
				var field = current.GetField(name, MemberFlags);
				if (field != null)
					return field;
			}
			catch (Exception ex)
			{
				failure = ex;
				return null;
			}
		}
		return null;
	}

	private static MethodInfo FindParameterlessMethod(Type type, string name, out Exception failure)
	{
		failure = null;
		for (var current = type; current != null; current = current.BaseType)
		{
			MethodInfo[] methods;
			try
			{
				methods = current.GetMethods(MemberFlags);
			}
			catch (Exception ex)
			{
				failure = ex;
				return null;
			}

			foreach (var method in methods)
			{
				if (!string.Equals(method.Name, name, StringComparison.Ordinal)
					|| method.ContainsGenericParameters)
					continue;

				try
				{
					if (method.GetParameters().Length == 0)
						return method;
				}
				catch (Exception ex)
				{
					failure = ex;
					return null;
				}
			}
		}
		return null;
	}

	private static string FormatFailure(Type type, string name, string operation, Exception exception)
	{
		var cause = exception;
		while (cause is TargetInvocationException && cause.InnerException != null)
			cause = cause.InnerException;
		return (type.FullName ?? type.Name) + "." + name + " " + operation + " failed: "
			+ cause.GetType().Name + ": " + cause.Message;
	}
}
