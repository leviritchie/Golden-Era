using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using ICSharpCode.Decompiler;
using ICSharpCode.Decompiler.CSharp;
using ICSharpCode.Decompiler.TypeSystem;
using Mono.Cecil;

// Usage:
//   Dc <dll> [out.cs]                         — whole module (slow on Hex.dll)
//   Dc <dll> <out.cs> --filter <substring>    — only types whose FullName contains substring (repeatable)
//   Dc <dll> <out.cs> --exact <name>           — only types whose FullName or Name exactly matches name (repeatable)
//
// Examples:
//   Dc Hex.dll city_ui.cs --filter BhCity --filter ObjCity --filter cityDungeon

if (args.Length < 1)
{
	Console.Error.WriteLine(
		"Usage: Dc <path-to.dll> [out.cs] [--filter <substring> ...]\n"
			+ "       Without --filter: decompile entire module (very slow for large Hex.dll)."
	);
	Environment.Exit(1);
}

var dll = Path.GetFullPath(args[0]);
if (!File.Exists(dll))
{
	Console.Error.WriteLine("File not found: " + dll);
	Environment.Exit(1);
}

var filters = new System.Collections.Generic.List<string>();
var exactFilters = new System.Collections.Generic.List<string>();
string? outPath = null;
for (var i = 1; i < args.Length; i++)
{
	if (string.Equals(args[i], "--filter", StringComparison.OrdinalIgnoreCase) && i + 1 < args.Length)
	{
		filters.Add(args[++i]);
		continue;
	}

	if (string.Equals(args[i], "--exact", StringComparison.OrdinalIgnoreCase) && i + 1 < args.Length)
	{
		exactFilters.Add(args[++i]);
		continue;
	}

	if (outPath == null && !args[i].StartsWith("--", StringComparison.Ordinal))
	{
		outPath = Path.GetFullPath(args[i]);
	}
}

outPath ??= Path.Combine(
	Path.GetDirectoryName(dll)!,
	Path.GetFileNameWithoutExtension(dll) + ".decompiled.cs");

var settings = new DecompilerSettings
{
	ThrowOnAssemblyResolveErrors = false
};

var decompiler = new CSharpDecompiler(dll, settings);

if (filters.Count == 0 && exactFilters.Count == 0)
{
	string text = decompiler.DecompileWholeModuleAsString();
	Directory.CreateDirectory(Path.GetDirectoryName(outPath)!);
	File.WriteAllText(outPath, text, System.Text.Encoding.UTF8);
	Console.WriteLine("Wrote " + outPath + " (" + new FileInfo(outPath).Length + " bytes).");
	return;
}

// Filtered: enumerate types with Mono.Cecil (no Assembly.Load — IL2CPP interop often fails full reflection).
static IEnumerable<TypeDefinition> FlattenTypes(TypeDefinition td)
{
	yield return td;
	foreach (var nt in td.NestedTypes)
	{
		foreach (var x in FlattenTypes(nt))
		{
			yield return x;
		}
	}
}

ModuleDefinition mod;
try
{
	var resolver = new DefaultAssemblyResolver();
	resolver.AddSearchDirectory(Path.GetDirectoryName(dll)!);
	mod = ModuleDefinition.ReadModule(dll, new ReaderParameters { AssemblyResolver = resolver });
}
catch (Exception ex)
{
	Console.Error.WriteLine("Mono.Cecil read failed: " + ex.Message);
	Environment.Exit(1);
	return;
}

var typeNames = new List<string>();
foreach (var top in mod.Types)
{
	foreach (var td in FlattenTypes(top))
	{
		var fn = td.FullName.Replace("/", "+"); // nested → IL name
		if (!filters.Any(f => fn.Contains(f, StringComparison.OrdinalIgnoreCase))
			&& !exactFilters.Any(f => string.Equals(fn, f, StringComparison.Ordinal)
				|| string.Equals(td.Name, f, StringComparison.Ordinal)))
		{
			continue;
		}

		typeNames.Add(fn);
	}
}

typeNames = typeNames.Distinct(StringComparer.Ordinal).OrderBy(x => x, StringComparer.Ordinal).ToList();

var sb = new StringBuilder();
var matched = 0;
foreach (var fn in typeNames)
{
	try
	{
		var code = decompiler.DecompileTypeAsString(new FullTypeName(fn));
		sb.AppendLine("// --- ").AppendLine("// ").AppendLine(fn).AppendLine("// --- ");
		sb.AppendLine(code);
		sb.AppendLine();
		matched++;
	}
	catch (Exception ex)
	{
		sb.AppendLine("// FAILED: " + fn + " — " + ex.Message).AppendLine();
	}
}

Directory.CreateDirectory(Path.GetDirectoryName(outPath)!);
File.WriteAllText(outPath, sb.ToString(), Encoding.UTF8);
Console.WriteLine(
	"Wrote " + outPath + " (" + new FileInfo(outPath).Length + " bytes), " + matched + " type(s) matching filter."
);
