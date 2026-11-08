// dotnet harness: same interop type/method resolution as EsquirePikemanVisuals + MakeGenericMethod(GameObject).

using System.IO;
using System.Linq;
using System.Reflection;
using OfflineUnlockMod;

const string envPlaytest = "HEROES_OE_PLAYTEST";

var playtest = ParseArgs(args) ?? Environment.GetEnvironmentVariable(envPlaytest);
if (string.IsNullOrWhiteSpace(playtest))
	playtest = FindPlaytestRoot();

if (string.IsNullOrWhiteSpace(playtest) || !Directory.Exists(playtest))
{
	Console.Error.WriteLine(
		"Playtest root not found. Use --playtest-root <path> or set {0}, or run from a clone where "
		+ "'Heroes of Might & Magic Olden Era Playtest' exists under the repo root. Got: {1}",
		envPlaytest,
		playtest ?? "(null)");
	return 1;
}

var bepinex = Path.Combine(playtest, "BepInEx");
var interop = Path.Combine(bepinex, "interop");
var core = Path.Combine(bepinex, "core");
if (!Directory.Exists(interop))
{
	Console.Error.WriteLine("BepInEx interop not found: {0}", interop);
	return 1;
}
if (!Directory.Exists(core))
{
	Console.Error.WriteLine("BepInEx core not found: {0}", core);
	return 1;
}

try
{
	foreach (var rel in AssembliesInLoadOrder())
	{
		var relNorm = rel.Replace('/', Path.DirectorySeparatorChar);
		var full = relNorm.StartsWith("core" + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)
			? Path.Combine(bepinex, relNorm)
			: Path.Combine(interop, relNorm);
		if (!File.Exists(full))
		{
			Console.Error.WriteLine("Missing assembly: {0}", full);
			return 1;
		}
		Assembly.LoadFrom(full);
	}
}
catch (Exception e)
{
	Console.Error.WriteLine("Assembly load failed: {0}", e);
	return 1;
}

void Log(string s) => Console.WriteLine(s);

var resAsm = AppDomain.CurrentDomain.GetAssemblies()
	.FirstOrDefault(a => string.Equals(a.GetName().Name, "Hex.ResManager", StringComparison.Ordinal));
if (resAsm == null)
{
	Console.Error.WriteLine("After loading, Hex.ResManager assembly is not in the app domain.");
	return 1;
}

var resType = ResManagerInteropProbe.TryResolveResManagerType(resAsm, Log);
if (resType == null)
{
	Console.Error.WriteLine("Type ResManager (namespace Hex) not found.");
	return 1;
}

var unity = AppDomain.CurrentDomain.GetAssemblies()
	.FirstOrDefault(a => string.Equals(a.GetName().Name, "UnityEngine.CoreModule", StringComparison.Ordinal));
if (unity == null)
{
	Console.Error.WriteLine("UnityEngine.CoreModule not loaded.");
	return 1;
}

var gameObject = unity.GetType("UnityEngine.GameObject", false);
if (gameObject == null)
{
	Console.Error.WriteLine("UnityEngine.GameObject type not found.");
	return 1;
}

if (string.Equals(Environment.GetEnvironmentVariable("VERIFY_RES_DUMP"), "1", StringComparison.Ordinal))
{
	var flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static
		| BindingFlags.DeclaredOnly;
	Console.Error.WriteLine("--- {0} (declared) ---", resType.FullName);
	foreach (var m in resType.GetMethods(flags)
	         .OrderBy(m => m.MetadataToken).Where(
		         m => m.IsGenericMethodDefinition
			         || m.Name.Contains("Get", StringComparison.Ordinal)))
		Console.Error.WriteLine(
			"  {0} genDef={1} ret={2} p=[{3}]",
			m.Name,
			m.IsGenericMethodDefinition,
			m.ReturnType.Name,
			string.Join(
				", ",
				m.GetParameters().Select(p => p.ParameterType.FullName + " " + p.Name)));
}

var open = ResManagerInteropProbe.FindResManagerGetOpenGeneric(resType);
if (open == null)
{
	Console.Error.WriteLine("Open generic Get<T>(path) on ResManager not found.");
	return 1;
}

try
{
	var closed = open.MakeGenericMethod(gameObject);
	Console.WriteLine(closed.ToString());
	if (string.Equals(Environment.GetEnvironmentVariable("VERIFY_RES_PTR"), "1", StringComparison.Ordinal))
	{
		var textAsset = unity.GetType("UnityEngine.TextAsset", false);
		if (textAsset != null)
		{
			var closedTa = open.MakeGenericMethod(textAsset);
			var pGo = closed.MethodHandle.GetFunctionPointer();
			var pTa = closedTa.MethodHandle.GetFunctionPointer();
			Console.Error.WriteLine(
				"PtrCompare: bmeo[GameObject]=" + pGo + " bmeo[TextAsset]=" + pTa + " sameNativeCode=" + (pGo == pTa));
		}
	}

	return 0;
}
catch (Exception e)
{
	Console.Error.WriteLine("MakeGenericMethod failed: {0}", e);
	return 1;
}

static IEnumerable<string> AssembliesInLoadOrder()
{
	// BepInEx core hosts Il2Cpp glue; interop is game assemblies.
	yield return @"core\Il2CppInterop.Runtime.dll";
	yield return @"core\Il2CppInterop.Common.dll";
	yield return "Il2Cppmscorlib.dll";
	yield return "Il2CppSystem.dll";
	yield return "Il2CppSystem.Core.dll";
	yield return "UnityEngine.CoreModule.dll";
	yield return "Hex.dll";
	yield return "Hex.Shared.dll";
	yield return "Hex.ResManager.dll";
}

static string? ParseArgs(string[] a)
{
	for (var i = 0; i < a.Length; i++)
	{
		if (a[i] is "--playtest-root" or "-p" && i + 1 < a.Length)
			return a[i + 1];
	}
	return null;
}

static string? FindPlaytestRoot()
{
	var fromCwd = Path.Combine(
		Directory.GetCurrentDirectory(),
		"Heroes of Might & Magic Olden Era Playtest");
	if (Directory.Exists(fromCwd))
		return Path.GetFullPath(fromCwd);

	var baseDir = AppContext.BaseDirectory;
	for (var dir = new DirectoryInfo(baseDir); dir != null; dir = dir.Parent)
	{
		var child = Path.Combine(dir.FullName, "Heroes of Might & Magic Olden Era Playtest");
		if (Directory.Exists(child))
			return child;
	}
	return null;
}
