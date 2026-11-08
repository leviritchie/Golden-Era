using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using Mono.Cecil;

var options = Options.Parse(args);
if (options == null)
{
    Console.Error.WriteLine(
        "Usage: DeobfSymbolProbe --old <old-interop-dir> --new <new-interop-dir> " +
        "[--assembly Hex.dll] [--game-symbols <GameSymbols.cs>] [--json-out <path>] [--md-out <path>]");
    return 1;
}

var oldAssemblyPath = Path.Combine(options.OldInteropDir, options.AssemblyName);
var newAssemblyPath = Path.Combine(options.NewInteropDir, options.AssemblyName);
var oldModule = LoadModule(oldAssemblyPath);
var newModule = LoadModule(newAssemblyPath);
if (oldModule == null || newModule == null)
    return 1;

var symbolHints = options.GameSymbolsPath == null
    ? new HashSet<string>(StringComparer.Ordinal)
    : LoadGameSymbolHints(options.GameSymbolsPath);

var oldIndex = AssemblyIndex.Build(oldModule);
var newIndex = AssemblyIndex.Build(newModule);
var report = BuildReport(oldIndex, newIndex, symbolHints, options);

var json = JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true });
if (!string.IsNullOrWhiteSpace(options.JsonOut))
{
    Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(options.JsonOut))!);
    File.WriteAllText(options.JsonOut, json);
}
else
{
    Console.WriteLine(json);
}

if (!string.IsNullOrWhiteSpace(options.MdOut))
{
    Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(options.MdOut))!);
    File.WriteAllText(options.MdOut, RenderMarkdown(report));
}

Console.Error.WriteLine(
    $"Compared {options.AssemblyName}: {report.TypeRenames.Count} type rename(s), " +
    $"{report.MethodRenames.Count} method rename(s), {report.FieldRenames.Count} field rename(s).");
return 0;

static ModuleDefinition? LoadModule(string path)
{
    if (!File.Exists(path))
    {
        Console.Error.WriteLine("Missing assembly: " + path);
        return null;
    }

    try
    {
        var resolver = new DefaultAssemblyResolver();
        resolver.AddSearchDirectory(Path.GetDirectoryName(path)!);
        return ModuleDefinition.ReadModule(path, new ReaderParameters
        {
            AssemblyResolver = resolver,
            InMemory = true
        });
    }
    catch (Exception ex)
    {
        Console.Error.WriteLine("Failed to load " + path + ": " + ex.Message);
        return null;
    }
}

static HashSet<string> LoadGameSymbolHints(string path)
{
    var hints = new HashSet<string>(StringComparer.Ordinal);
    if (!File.Exists(path))
    {
        Console.Error.WriteLine("GameSymbols path not found: " + path);
        return hints;
    }

    var text = File.ReadAllText(path);
    foreach (Match match in Regex.Matches(text, "\"([a-z]{2}|[a-z]{3}|[a-c][a-z]{3})\""))
        hints.Add(match.Groups[1].Value);
    return hints;
}

static Report BuildReport(AssemblyIndex oldIndex, AssemblyIndex newIndex, HashSet<string> symbolHints, Options options)
{
    var typeRenames = new List<RenameEntry>();
    foreach (var key in oldIndex.Types.Keys.Intersect(newIndex.Types.Keys, StringComparer.Ordinal).OrderBy(x => x, StringComparer.Ordinal))
    {
        var oldSymbol = oldIndex.Types[key];
        var newSymbol = newIndex.Types[key];
        if (!IsRename(oldSymbol.ObfuscatedName, newSymbol.ObfuscatedName))
            continue;
        typeRenames.Add(RenameEntry.From(key, oldSymbol, newSymbol, symbolHints));
    }

    var methodRenames = new List<RenameEntry>();
    foreach (var key in oldIndex.Methods.Keys.Intersect(newIndex.Methods.Keys, StringComparer.Ordinal).OrderBy(x => x, StringComparer.Ordinal))
    {
        var oldSymbol = oldIndex.Methods[key];
        var newSymbol = newIndex.Methods[key];
        if (!IsRename(oldSymbol.ObfuscatedName, newSymbol.ObfuscatedName))
            continue;
        methodRenames.Add(RenameEntry.From(key, oldSymbol, newSymbol, symbolHints));
    }

    var fieldRenames = new List<RenameEntry>();
    foreach (var key in oldIndex.Fields.Keys.Intersect(newIndex.Fields.Keys, StringComparer.Ordinal).OrderBy(x => x, StringComparer.Ordinal))
    {
        var oldSymbol = oldIndex.Fields[key];
        var newSymbol = newIndex.Fields[key];
        if (!IsRename(oldSymbol.ObfuscatedName, newSymbol.ObfuscatedName))
            continue;
        fieldRenames.Add(RenameEntry.From(key, oldSymbol, newSymbol, symbolHints));
    }

    return new Report
    {
        OldInteropDir = options.OldInteropDir,
        NewInteropDir = options.NewInteropDir,
        AssemblyName = options.AssemblyName,
        GameSymbolsPath = options.GameSymbolsPath,
        GameSymbolsHintCount = symbolHints.Count,
        TypeRenames = typeRenames,
        MethodRenames = methodRenames,
        FieldRenames = fieldRenames,
        GameSymbolsRelevantTypeRenames = typeRenames.Where(x => x.GameSymbolsRelevant).ToList(),
        GameSymbolsRelevantMethodRenames = methodRenames.Where(x => x.GameSymbolsRelevant).ToList(),
        GameSymbolsRelevantFieldRenames = fieldRenames.Where(x => x.GameSymbolsRelevant).ToList()
    };
}

static bool IsRename(string? oldName, string? newName)
{
    return !string.IsNullOrWhiteSpace(oldName)
        && !string.IsNullOrWhiteSpace(newName)
        && !string.Equals(oldName, newName, StringComparison.Ordinal);
}

static string RenderMarkdown(Report report)
{
    var sb = new StringBuilder();
    sb.AppendLine("# Deobfuscated Interop Symbol Probe");
    sb.AppendLine();
    sb.AppendLine($"- Old interop: `{report.OldInteropDir}`");
    sb.AppendLine($"- New interop: `{report.NewInteropDir}`");
    sb.AppendLine($"- Assembly: `{report.AssemblyName}`");
    sb.AppendLine($"- GameSymbols hints: `{report.GameSymbolsHintCount}`");
    sb.AppendLine();
    sb.AppendLine("## Summary");
    sb.AppendLine();
    sb.AppendLine($"- Type obfuscated-name changes: {report.TypeRenames.Count}");
    sb.AppendLine($"- Method obfuscated-name changes: {report.MethodRenames.Count}");
    sb.AppendLine($"- Field obfuscated-name changes: {report.FieldRenames.Count}");
    sb.AppendLine($"- Type changes touching GameSymbols hints: {report.GameSymbolsRelevantTypeRenames.Count}");
    sb.AppendLine($"- Method changes touching GameSymbols hints: {report.GameSymbolsRelevantMethodRenames.Count}");
    sb.AppendLine($"- Field changes touching GameSymbols hints: {report.GameSymbolsRelevantFieldRenames.Count}");
    sb.AppendLine();

    AppendTable(sb, "GameSymbols-Relevant Type Renames", report.GameSymbolsRelevantTypeRenames);
    AppendTable(sb, "GameSymbols-Relevant Method Renames", report.GameSymbolsRelevantMethodRenames);
    AppendTable(sb, "GameSymbols-Relevant Field Renames", report.GameSymbolsRelevantFieldRenames);
    return sb.ToString();
}

static void AppendTable(StringBuilder sb, string title, IReadOnlyList<RenameEntry> entries)
{
    sb.AppendLine("## " + title);
    sb.AppendLine();
    if (entries.Count == 0)
    {
        sb.AppendLine("No matches.");
        sb.AppendLine();
        return;
    }

    sb.AppendLine("| Stable key | Old obfuscated | New obfuscated |");
    sb.AppendLine("| --- | --- | --- |");
    foreach (var entry in entries.Take(200))
    {
        sb.Append("| `").Append(EscapeMarkdown(entry.StableKey)).Append("` ");
        sb.Append("| `").Append(entry.OldObfuscatedName).Append("` ");
        sb.Append("| `").Append(entry.NewObfuscatedName).AppendLine("` |");
    }
    if (entries.Count > 200)
        sb.AppendLine();
    if (entries.Count > 200)
        sb.AppendLine("Only the first 200 rows are shown; use the JSON report for the full list.");
    sb.AppendLine();
}

static string EscapeMarkdown(string value)
{
    return value.Replace("`", "\\`");
}

sealed class Options
{
    public required string OldInteropDir { get; init; }
    public required string NewInteropDir { get; init; }
    public string AssemblyName { get; init; } = "Hex.dll";
    public string? GameSymbolsPath { get; init; }
    public string? JsonOut { get; init; }
    public string? MdOut { get; init; }

    public static Options? Parse(string[] args)
    {
        string? oldDir = null;
        string? newDir = null;
        string assemblyName = "Hex.dll";
        string? gameSymbols = null;
        string? jsonOut = null;
        string? mdOut = null;

        for (var i = 0; i < args.Length; i++)
        {
            string? ReadValue()
            {
                if (i + 1 >= args.Length)
                    return null;
                return args[++i];
            }

            switch (args[i])
            {
                case "--old":
                    oldDir = ReadValue();
                    break;
                case "--new":
                    newDir = ReadValue();
                    break;
                case "--assembly":
                    assemblyName = ReadValue() ?? assemblyName;
                    break;
                case "--game-symbols":
                    gameSymbols = ReadValue();
                    break;
                case "--json-out":
                    jsonOut = ReadValue();
                    break;
                case "--md-out":
                    mdOut = ReadValue();
                    break;
            }
        }

        if (string.IsNullOrWhiteSpace(oldDir) || string.IsNullOrWhiteSpace(newDir))
            return null;

        return new Options
        {
            OldInteropDir = oldDir,
            NewInteropDir = newDir,
            AssemblyName = assemblyName,
            GameSymbolsPath = gameSymbols,
            JsonOut = jsonOut,
            MdOut = mdOut
        };
    }
}

sealed class AssemblyIndex
{
    public Dictionary<string, SymbolRecord> Types { get; } = new(StringComparer.Ordinal);
    public Dictionary<string, SymbolRecord> Methods { get; } = new(StringComparer.Ordinal);
    public Dictionary<string, SymbolRecord> Fields { get; } = new(StringComparer.Ordinal);

    public static AssemblyIndex Build(ModuleDefinition module)
    {
        var index = new AssemblyIndex();
        foreach (var type in module.Types)
            CollectType(index, type);
        return index;
    }

    private static void CollectType(AssemblyIndex index, TypeDefinition type)
    {
        var typeKey = NormalizeTypeName(type.FullName);
        index.Types[typeKey] = new SymbolRecord
        {
            StableName = typeKey,
            ObfuscatedName = GetObfuscatedName(type.CustomAttributes),
            OwnerStableName = null,
            Signature = "type"
        };

        foreach (var method in type.Methods)
        {
            if (method.IsConstructor || method.Name == "Finalize")
                continue;
            var signature = MethodSignature(method);
            var key = typeKey + "::" + method.Name + signature;
            index.Methods[key] = new SymbolRecord
            {
                StableName = method.Name,
                ObfuscatedName = GetObfuscatedName(method.CustomAttributes),
                OwnerStableName = typeKey,
                Signature = signature
            };
        }

        foreach (var field in type.Fields)
        {
            var signature = field.FieldType.FullName;
            var key = typeKey + "::" + field.Name + ":" + signature;
            index.Fields[key] = new SymbolRecord
            {
                StableName = field.Name,
                ObfuscatedName = GetObfuscatedName(field.CustomAttributes),
                OwnerStableName = typeKey,
                Signature = signature
            };
        }

        foreach (var nested in type.NestedTypes)
            CollectType(index, nested);
    }

    private static string MethodSignature(MethodDefinition method)
    {
        var parameters = string.Join(",", method.Parameters.Select(p => p.ParameterType.FullName));
        return "(" + parameters + "):" + method.ReturnType.FullName;
    }

    private static string NormalizeTypeName(string fullName)
    {
        return fullName.Replace("/", "+");
    }

    private static string? GetObfuscatedName(IEnumerable<CustomAttribute> attributes)
    {
        foreach (var attribute in attributes)
        {
            if (!attribute.AttributeType.Name.Contains("ObfuscatedNameAttribute", StringComparison.Ordinal))
                continue;
            if (attribute.ConstructorArguments.Count == 0)
                continue;
            return attribute.ConstructorArguments[0].Value?.ToString();
        }
        return null;
    }
}

sealed class SymbolRecord
{
    public required string StableName { get; init; }
    public string? ObfuscatedName { get; init; }
    public string? OwnerStableName { get; init; }
    public required string Signature { get; init; }
}

sealed class RenameEntry
{
    public required string StableKey { get; init; }
    public string? OwnerStableName { get; init; }
    public required string StableName { get; init; }
    public required string Signature { get; init; }
    public required string OldObfuscatedName { get; init; }
    public required string NewObfuscatedName { get; init; }
    public bool GameSymbolsRelevant { get; init; }

    public static RenameEntry From(string stableKey, SymbolRecord oldSymbol, SymbolRecord newSymbol, HashSet<string> symbolHints)
    {
        var oldName = oldSymbol.ObfuscatedName ?? "";
        var newName = newSymbol.ObfuscatedName ?? "";
        return new RenameEntry
        {
            StableKey = stableKey,
            OwnerStableName = oldSymbol.OwnerStableName,
            StableName = oldSymbol.StableName,
            Signature = oldSymbol.Signature,
            OldObfuscatedName = oldName,
            NewObfuscatedName = newName,
            GameSymbolsRelevant = symbolHints.Contains(oldName) || symbolHints.Contains(newName)
        };
    }
}

sealed class Report
{
    public required string OldInteropDir { get; init; }
    public required string NewInteropDir { get; init; }
    public required string AssemblyName { get; init; }
    public string? GameSymbolsPath { get; init; }
    public int GameSymbolsHintCount { get; init; }
    public required List<RenameEntry> TypeRenames { get; init; }
    public required List<RenameEntry> MethodRenames { get; init; }
    public required List<RenameEntry> FieldRenames { get; init; }
    public required List<RenameEntry> GameSymbolsRelevantTypeRenames { get; init; }
    public required List<RenameEntry> GameSymbolsRelevantMethodRenames { get; init; }
    public required List<RenameEntry> GameSymbolsRelevantFieldRenames { get; init; }
}
