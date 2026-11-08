using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Player.log: <c>Store state</c> failed, then <c>Hex.InitScene.BhAppStartScript.Update</c> throws
/// a repeating <see cref="TypeInitializationException"/> (inner <see cref="NullReferenceException"/>
/// in <c>in.hjs(Hex.UI.ELang, …)</c>) — not from the mod, but the loop blocks progress.
/// A Harmony <em>finalizer</em> on <c>Update</c> swallows that case when
/// <see cref="LauncherConfig.SuppressBhAppStartTypeInitLoop"/> is on.
/// </summary>
internal static class BhAppStartTypeInitLoopWorkaround
{
	private static bool _logged;

	internal static void TryRegister(Harmony h, ManualLogSource log, bool enable)
	{
		if (!enable)
			return;
		var t = FindBhAppStartType();
		if (t == null)
		{
			log?.LogWarning("BhAppStart: Hex.InitScene.BhAppStartScript not found; type-init workaround skipped.");
			return;
		}
		var update = AccessTools.DeclaredMethod(t, "Update");
		if (update == null)
		{
			log?.LogWarning("BhAppStart: Update not found; type-init workaround skipped.");
			return;
		}
		h.Patch(
			original: update,
			finalizer: new HarmonyMethod(
				typeof(BhAppStartTypeInitLoopWorkaround),
				nameof(SuppressKnownInitException)));
		log?.LogInfo("BhAppStart: Harmony finalizer on " + t.FullName + ".Update (suppress known ELang TIE).");
		TryPatchDeobfBootstrapChain(h, log);
	}

	private static void TryPatchDeobfBootstrapChain(Harmony h, ManualLogSource log)
	{
		var hexAsm = FindHexAssembly();
		if (hexAsm == null)
			return;

		// Deobf/offline init path: BhAppStartScript.Update -> byu.pml -> zi.jyv before ELang bootstrap completes.
		TryPatchChainFinalizer(h, log, hexAsm, "byu", "pml");
		TryPatchChainFinalizer(h, log, hexAsm, "zi", "jyv");
		TryPatchChainFinalizerByObfuscatedName(h, log, hexAsm, "byu", "pml");
		TryPatchChainFinalizerByObfuscatedName(h, log, hexAsm, "zi", "jyv");
	}

	private static Assembly FindHexAssembly()
	{
		foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
		{
			if (asm != null && string.Equals(asm.GetName().Name, "Hex", StringComparison.OrdinalIgnoreCase))
				return asm;
		}
		return null;
	}

	private static void TryPatchChainFinalizerByObfuscatedName(
		Harmony h,
		ManualLogSource log,
		Assembly hexAsm,
		string obfuscatedTypeName,
		string obfuscatedMethodName)
	{
		try
		{
			Type[] types;
			try { types = hexAsm.GetTypes(); }
			catch (ReflectionTypeLoadException ex) { types = ex.Types ?? Array.Empty<Type>(); }
			foreach (var owner in types)
			{
				if (owner == null || !string.Equals(ReadObfuscatedName(owner), obfuscatedTypeName, StringComparison.Ordinal))
					continue;
				var method = AccessTools.DeclaredMethod(owner, obfuscatedMethodName, Type.EmptyTypes)
				             ?? FindDeclaredVoidMethodByObfuscatedName(owner, obfuscatedMethodName);
				if (method == null)
					continue;
				h.Patch(
					method,
					finalizer: new HarmonyMethod(
						typeof(BhAppStartTypeInitLoopWorkaround),
						nameof(SuppressKnownInitException)));
				log?.LogInfo(
					"BhAppStart: Harmony finalizer on "
					+ owner.FullName
					+ "."
					+ method.Name
					+ " (offline bootstrap chain via "
					+ obfuscatedTypeName
					+ "."
					+ obfuscatedMethodName
					+ ").");
				return;
			}
		}
		catch (Exception ex)
		{
			log?.LogDebug(
				"BhAppStart: skipped obfuscated chain patch "
				+ obfuscatedTypeName
				+ "."
				+ obfuscatedMethodName
				+ ": "
				+ ex.Message);
		}
	}

	private static MethodInfo FindDeclaredVoidMethodByObfuscatedName(Type owner, string obfuscatedMethodName)
	{
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.Instance | BindingFlags.DeclaredOnly;
		MethodInfo[] methods;
		try { methods = owner.GetMethods(flags); }
		catch { return null; }
		foreach (var method in methods)
		{
			if (method == null || method.IsSpecialName || method.ReturnType != typeof(void))
				continue;
			if (method.GetParameters().Length != 0)
				continue;
			if (string.Equals(method.Name, obfuscatedMethodName, StringComparison.Ordinal)
			    || string.Equals(ReadObfuscatedName(method), obfuscatedMethodName, StringComparison.Ordinal))
				return method;
		}
		return null;
	}

	private static string ReadObfuscatedName(MemberInfo member)
	{
		if (member == null)
			return null;
		try
		{
			foreach (var data in member.GetCustomAttributesData())
			{
				if (data?.AttributeType?.Name != "ObfuscatedNameAttribute" || data.ConstructorArguments.Count == 0)
					continue;
				return data.ConstructorArguments[0].Value as string;
			}
		}
		catch { }
		return null;
	}

	private static void TryPatchChainFinalizer(Harmony h, ManualLogSource log, Assembly hexAsm, string typeName, string methodName)
	{
		try
		{
			var owner = hexAsm.GetType(typeName, false, false);
			if (owner == null)
				return;
			var method = AccessTools.DeclaredMethod(owner, methodName, Type.EmptyTypes);
			if (method == null || method.ReturnType != typeof(void))
				return;
			h.Patch(
				method,
				finalizer: new HarmonyMethod(
					typeof(BhAppStartTypeInitLoopWorkaround),
					nameof(SuppressKnownInitException)));
			log?.LogInfo("BhAppStart: Harmony finalizer on " + owner.FullName + "." + method.Name + " (offline bootstrap chain).");
		}
		catch (Exception ex)
		{
			log?.LogDebug("BhAppStart: skipped " + typeName + "." + methodName + " chain patch: " + ex.Message);
		}
	}

	private static Type FindBhAppStartType()
	{
		const string name = "Hex.InitScene.BhAppStartScript";
		var t = Type.GetType(name + ", Assembly-CSharp, Version=0.0.0.0, Culture=neutral, PublicKeyToken=null");
		if (t != null)
			return t;
		t = Type.GetType(name);
		if (t != null)
			return t;
		foreach (var a in AppDomain.CurrentDomain.GetAssemblies())
		{
			try
			{
				t = a.GetType(name, false);
				if (t != null)
					return t;
			}
			catch
			{
			}
		}
		return null;
	}

	/// <summary>Harmony finalizer: return <c>null</c> to swallow the exception.</summary>
	// ReSharper disable once InconsistentNaming — Harmony injects
	private static Exception SuppressKnownInitException(Exception __exception)
	{
		if (!Plugin.SuppressBhAppStartTypeInitLoop)
			return __exception;
		if (__exception == null)
			return null;
		if (!IsKnownBhAppTypeInitException(__exception))
			return __exception;
		if (!_logged)
		{
			Plugin.LogSource?.LogWarning(
				"BhAppStart: Suppressed a known BhAppStartScript.Update bootstrap exception (ELang / store bootstrap). "
				+ "Set suppressBhAppStartTypeInitLoop=false in config to show errors. See Player.log for full stack."
			);
			_logged = true;
		}
		return null;
	}

	/// <summary>
	/// Finalizer targets are scoped to BhAppStartScript.Update and its offline bootstrap callees only.
	/// Il2CppInterop often passes a bare <see cref="NullReferenceException"/> without BhAppStart stack text.
	/// </summary>
	private static bool IsKnownBhAppTypeInitException(Exception ex)
	{
		for (var e = ex; e != null; e = e.InnerException)
		{
			if (e is TypeInitializationException)
				return true;
		}

		var t = CollectExceptionText(ex);
		if (t.IndexOf("TypeInitializationException", StringComparison.Ordinal) >= 0)
			return true;
		if (t.IndexOf("NullReferenceException", StringComparison.Ordinal) < 0)
			return false;

		// Do not swallow bare NRE without bootstrap-chain evidence; InputManager/TextAsset failures need to surface.
		return t.IndexOf("BhAppStartScript", StringComparison.Ordinal) >= 0
			&& (t.IndexOf("in.hjs", StringComparison.Ordinal) >= 0
			    || t.IndexOf("::hjs", StringComparison.Ordinal) >= 0
			    || t.IndexOf("Hex.UI.ELang", StringComparison.Ordinal) >= 0
			    || t.IndexOf("Hex.UI.FontByLang", StringComparison.Ordinal) >= 0
			    || t.IndexOf("il..cctor", StringComparison.Ordinal) >= 0
			    || t.IndexOf("Method_Private_Static_Void_ELang_Dictionary_2_String_FontByLang", StringComparison.Ordinal) >= 0
			    || t.IndexOf("ObjectPublicAbstractSealedDi2StFobpTMDi2StbpUnique", StringComparison.Ordinal) >= 0
			    || t.IndexOf("InterfacePublicAbstracthmVo2", StringComparison.Ordinal) >= 0
			    || t.IndexOf(".jyv()", StringComparison.Ordinal) >= 0
			    || t.IndexOf(" at zi.", StringComparison.Ordinal) >= 0);
	}

	private static string CollectExceptionText(Exception ex)
	{
		if (ex == null)
			return string.Empty;
		var parts = new List<string>();
		for (var e = ex; e != null; e = e.InnerException)
			parts.Add(e.ToString());
		return string.Join("\n", parts);
	}
}
