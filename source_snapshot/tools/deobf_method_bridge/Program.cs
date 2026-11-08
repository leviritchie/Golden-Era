using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Globalization;
using System.Security.Cryptography;
using Mono.Cecil;
using Mono.Cecil.Cil;

var options = Options.Parse(args);
if (options == null)
{
    Console.Error.WriteLine(
        "Usage: DeobfMethodBridge --old-deobf <dir> --old-normal <dir> --new-deobf <dir> --new-normal <dir> " +
        "[--assembly Hex.dll] [--game-symbols <GameSymbols.cs>] [--json-out <path>] [--md-out <path>]");
    return 1;
}

var oldDeobf = LoadModule(Path.Combine(options.OldDeobfDir, options.AssemblyName));
var oldNormal = LoadModule(Path.Combine(options.OldNormalDir, options.AssemblyName));
var newDeobf = LoadModule(Path.Combine(options.NewDeobfDir, options.AssemblyName));
var newNormal = LoadModule(Path.Combine(options.NewNormalDir, options.AssemblyName));
if (oldDeobf == null || oldNormal == null || newDeobf == null || newNormal == null)
    return 1;

var hints = options.GameSymbolsPath == null
    ? new GameSymbolHints()
    : LoadGameSymbolHints(options.GameSymbolsPath);

var oldBridge = BridgeIndex.Build(oldDeobf, oldNormal);
var newBridge = BridgeIndex.Build(newDeobf, newNormal);
var rows = BuildRows(oldBridge, newBridge, hints);

var report = new Report
{
    AssemblyName = options.AssemblyName,
    OldDeobfDir = options.OldDeobfDir,
    OldNormalDir = options.OldNormalDir,
    NewDeobfDir = options.NewDeobfDir,
    NewNormalDir = options.NewNormalDir,
    GameSymbolsPath = options.GameSymbolsPath,
    GameSymbolsHintCount = hints.TotalHintCount,
    GameSymbolsMethodHintCount = hints.MethodHints.Count,
    GameSymbolsTypeHintCount = hints.TypeHints.Count,
    GameSymbolsFieldHintCount = hints.FieldHints.Count,
    OldStableMethodCount = oldBridge.Methods.Count,
    NewStableMethodCount = newBridge.Methods.Count,
    RawMethodRenameRows = rows,
    GameSymbolsRelevantRawMethodRenameRows = rows.Where(x => x.GameSymbolsRelevant).ToList(),
    UnambiguousGameSymbolsRelevantRows = rows.Where(x => x.GameSymbolsRelevant && !x.Ambiguous).ToList(),
    AmbiguousGameSymbolsRelevantRows = rows.Where(x => x.GameSymbolsRelevant && x.Ambiguous).ToList(),
    GameSymbolsMethodNameRows = rows.Where(x => x.GameSymbolsMethodRelevant).ToList(),
    UnambiguousGameSymbolsMethodNameRows = rows.Where(x => x.GameSymbolsMethodRelevant && !x.Ambiguous).ToList(),
    AmbiguousGameSymbolsMethodNameRows = rows.Where(x => x.GameSymbolsMethodRelevant && x.Ambiguous).ToList(),
    OwnerOnlyGameSymbolsRows = rows.Where(x => x.GameSymbolsOwnerRelevant && !x.GameSymbolsMethodRelevant).ToList()
};

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
    $"Compared {options.AssemblyName}: {rows.Count} raw method rename candidate(s), " +
    $"{report.GameSymbolsMethodNameRows.Count} method-name relevant, " +
    $"{report.AmbiguousGameSymbolsMethodNameRows.Count} ambiguous.");
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

static GameSymbolHints LoadGameSymbolHints(string path)
{
    var hints = new GameSymbolHints();
    if (!File.Exists(path))
    {
        Console.Error.WriteLine("GameSymbols path not found: " + path);
        return hints;
    }

    var text = File.ReadAllText(path);
    foreach (Match match in Regex.Matches(text, @"MethodSymbol\s+\w+\s*=\s*new\s*\((?<args>.*?)\);", RegexOptions.Singleline))
    {
        var args = match.Groups["args"].Value;
        foreach (var value in ExtractQuotedStrings(args).Skip(1))
            hints.MethodHints.Add(value);
    }

    foreach (Match match in Regex.Matches(text, @"FieldSymbol\s+\w+\s*=\s*new\s*\((?<args>.*?)\);", RegexOptions.Singleline))
    {
        var values = ExtractQuotedStrings(match.Groups["args"].Value).ToList();
        if (values.Count >= 3)
            hints.FieldHints.Add(values[2]);
    }

    foreach (Match match in Regex.Matches(text, @"FieldSymbol\[\]\s+\w+\s*=\s*\{(?<body>.*?)\};", RegexOptions.Singleline))
    {
        var body = match.Groups["body"].Value;
        foreach (Match item in Regex.Matches(body, @"new\s*\((?<args>.*?)\)", RegexOptions.Singleline))
        {
            var values = ExtractQuotedStrings(item.Groups["args"].Value).ToList();
            if (values.Count >= 3)
                hints.FieldHints.Add(values[2]);
        }
    }

    foreach (Match match in Regex.Matches(text, @"TypeHint\s*=\s*""(?<value>[^""]+)""", RegexOptions.Singleline))
        hints.TypeHints.Add(match.Groups["value"].Value);

    foreach (Match match in Regex.Matches(text, @"(?:TypeHint|TypeHints)\s*=\s*(?:new\s+string\[\]\s*)?\{(?<args>.*?)\}", RegexOptions.Singleline))
    {
        foreach (var value in ExtractQuotedStrings(match.Groups["args"].Value))
            hints.TypeHints.Add(value);
    }

    return hints;
}

static List<string> ExtractQuotedStrings(string text)
{
    var values = new List<string>();
    foreach (Match match in Regex.Matches(text, "\"([^\"]+)\""))
        values.Add(match.Groups[1].Value);
    return values;
}

static List<MethodRenameRow> BuildRows(BridgeIndex oldBridge, BridgeIndex newBridge, GameSymbolHints hints)
{
    var rows = new List<MethodRenameRow>();
    foreach (var stableKey in oldBridge.Methods.Keys.Intersect(newBridge.Methods.Keys, StringComparer.Ordinal).OrderBy(x => x, StringComparer.Ordinal))
    {
        var oldMethod = oldBridge.Methods[stableKey];
        var newMethod = newBridge.Methods[stableKey];
        if (string.Equals(oldMethod.RawMethodName, newMethod.RawMethodName, StringComparison.Ordinal)
            && string.Equals(oldMethod.RawOwnerName, newMethod.RawOwnerName, StringComparison.Ordinal))
        {
            continue;
        }

        rows.Add(new MethodRenameRow
        {
            StableMethodKey = stableKey,
            StableOwnerName = oldMethod.StableOwnerName,
            StableMethodName = oldMethod.StableMethodName,
            RawSignature = oldMethod.RawSignature,
            OldRawOwnerName = oldMethod.RawOwnerName,
            OldRawMethodName = oldMethod.RawMethodName,
            NewRawOwnerName = newMethod.RawOwnerName,
            NewRawMethodName = newMethod.RawMethodName,
            OldOrdinal = oldMethod.Ordinal,
            NewOrdinal = newMethod.Ordinal,
            OldOverloadCount = oldMethod.OverloadCount,
            NewOverloadCount = newMethod.OverloadCount,
            OldEvidenceKey = oldMethod.EvidenceKey,
            NewEvidenceKey = newMethod.EvidenceKey,
            OldSelectionBasis = oldMethod.SelectionBasis,
            NewSelectionBasis = newMethod.SelectionBasis,
            OldCandidateCount = oldMethod.CandidateCount,
            NewCandidateCount = newMethod.CandidateCount,
            OldEvidenceMatchCount = oldMethod.EvidenceMatchCount,
            NewEvidenceMatchCount = newMethod.EvidenceMatchCount,
            OldFingerprintMatchCount = oldMethod.FingerprintMatchCount,
            NewFingerprintMatchCount = newMethod.FingerprintMatchCount,
            Ambiguous = oldMethod.Ambiguous || newMethod.Ambiguous,
            GameSymbolsMethodRelevant = hints.MethodHints.Contains(oldMethod.RawMethodName) || hints.MethodHints.Contains(newMethod.RawMethodName),
            GameSymbolsOwnerRelevant = hints.TypeHints.Contains(oldMethod.RawOwnerName) || hints.TypeHints.Contains(newMethod.RawOwnerName),
        });
    }
    return rows;
}

static string RenderMarkdown(Report report)
{
    var sb = new StringBuilder();
    sb.AppendLine("# Deobfuscated Method Bridge Probe");
    sb.AppendLine();
    sb.AppendLine($"- Assembly: `{report.AssemblyName}`");
    sb.AppendLine($"- Old deobf: `{report.OldDeobfDir}`");
    sb.AppendLine($"- Old normal: `{report.OldNormalDir}`");
    sb.AppendLine($"- New deobf: `{report.NewDeobfDir}`");
    sb.AppendLine($"- New normal: `{report.NewNormalDir}`");
    sb.AppendLine($"- GameSymbols hints: `{report.GameSymbolsHintCount}`");
    sb.AppendLine($"- Method hints: `{report.GameSymbolsMethodHintCount}`");
    sb.AppendLine($"- Type hints: `{report.GameSymbolsTypeHintCount}`");
    sb.AppendLine($"- Field hints: `{report.GameSymbolsFieldHintCount}`");
    sb.AppendLine();
    sb.AppendLine("## Summary");
    sb.AppendLine();
    sb.AppendLine($"- Old stable bridged methods: {report.OldStableMethodCount}");
    sb.AppendLine($"- New stable bridged methods: {report.NewStableMethodCount}");
    sb.AppendLine($"- Raw method rename candidates: {report.RawMethodRenameRows.Count}");
    sb.AppendLine($"- GameSymbols method-name candidates: {report.GameSymbolsMethodNameRows.Count}");
    sb.AppendLine($"- Unambiguous GameSymbols method-name candidates: {report.UnambiguousGameSymbolsMethodNameRows.Count}");
    sb.AppendLine($"- Ambiguous GameSymbols method-name candidates: {report.AmbiguousGameSymbolsMethodNameRows.Count}");
    sb.AppendLine($"- Fingerprint-resolved GameSymbols method-name candidates: {report.GameSymbolsMethodNameRows.Count(x => x.SelectionBasis.StartsWith("fingerprint", StringComparison.Ordinal))}");
    sb.AppendLine($"- Evidence-resolved GameSymbols method-name candidates: {report.GameSymbolsMethodNameRows.Count(x => x.SelectionBasis.StartsWith("evidence", StringComparison.Ordinal))}");
    sb.AppendLine($"- Ordinal-fallback GameSymbols method-name candidates: {report.GameSymbolsMethodNameRows.Count(x => x.SelectionBasis.StartsWith("ordinal", StringComparison.Ordinal))}");
    sb.AppendLine($"- Owner-only GameSymbols candidates: {report.OwnerOnlyGameSymbolsRows.Count}");
    sb.AppendLine();
    AppendRows(sb, "Unambiguous GameSymbols Method-Name Candidates", report.UnambiguousGameSymbolsMethodNameRows, 200);
    AppendRows(sb, "Ambiguous GameSymbols Method-Name Candidates", report.AmbiguousGameSymbolsMethodNameRows, 200);
    return sb.ToString();
}

static void AppendRows(StringBuilder sb, string title, IReadOnlyList<MethodRenameRow> rows, int limit)
{
    sb.AppendLine("## " + title);
    sb.AppendLine();
    if (rows.Count == 0)
    {
        sb.AppendLine("No matches.");
        sb.AppendLine();
        return;
    }

    sb.AppendLine("| Stable owner | Stable method | Old raw | New raw | Signature | Ordinal | Basis |");
    sb.AppendLine("| --- | --- | --- | --- | --- | --- | --- |");
    foreach (var row in rows.Take(limit))
    {
        sb.Append("| `").Append(Escape(row.StableOwnerName)).Append("` ");
        sb.Append("| `").Append(Escape(row.StableMethodName)).Append("` ");
        sb.Append("| `").Append(row.OldRawOwnerName).Append(".").Append(row.OldRawMethodName).Append("` ");
        sb.Append("| `").Append(row.NewRawOwnerName).Append(".").Append(row.NewRawMethodName).Append("` ");
        sb.Append("| `").Append(Escape(row.RawSignature)).Append("` ");
        sb.Append("| `").Append(row.OldOrdinal).Append("/").Append(row.OldOverloadCount)
            .Append(" -> ").Append(row.NewOrdinal).Append("/").Append(row.NewOverloadCount).Append("` ");
        sb.Append("| `").Append(Escape(row.OldSelectionBasis)).Append(" / ").Append(Escape(row.NewSelectionBasis)).AppendLine("` |");
    }
    if (rows.Count > limit)
    {
        sb.AppendLine();
        sb.AppendLine("Only the first " + limit + " rows are shown; use the JSON report for the full list.");
    }
    sb.AppendLine();
}

static string Escape(string value)
{
    return value.Replace("`", "\\`");
}

sealed class Options
{
    public required string OldDeobfDir { get; init; }
    public required string OldNormalDir { get; init; }
    public required string NewDeobfDir { get; init; }
    public required string NewNormalDir { get; init; }
    public string AssemblyName { get; init; } = "Hex.dll";
    public string? GameSymbolsPath { get; init; }
    public string? JsonOut { get; init; }
    public string? MdOut { get; init; }

    public static Options? Parse(string[] args)
    {
        string? oldDeobf = null;
        string? oldNormal = null;
        string? newDeobf = null;
        string? newNormal = null;
        string assemblyName = "Hex.dll";
        string? gameSymbols = null;
        string? jsonOut = null;
        string? mdOut = null;

        for (var i = 0; i < args.Length; i++)
        {
            string? ReadValue() => i + 1 < args.Length ? args[++i] : null;
            switch (args[i])
            {
                case "--old-deobf": oldDeobf = ReadValue(); break;
                case "--old-normal": oldNormal = ReadValue(); break;
                case "--new-deobf": newDeobf = ReadValue(); break;
                case "--new-normal": newNormal = ReadValue(); break;
                case "--assembly": assemblyName = ReadValue() ?? assemblyName; break;
                case "--game-symbols": gameSymbols = ReadValue(); break;
                case "--json-out": jsonOut = ReadValue(); break;
                case "--md-out": mdOut = ReadValue(); break;
            }
        }

        if (string.IsNullOrWhiteSpace(oldDeobf)
            || string.IsNullOrWhiteSpace(oldNormal)
            || string.IsNullOrWhiteSpace(newDeobf)
            || string.IsNullOrWhiteSpace(newNormal))
        {
            return null;
        }

        return new Options
        {
            OldDeobfDir = oldDeobf,
            OldNormalDir = oldNormal,
            NewDeobfDir = newDeobf,
            NewNormalDir = newNormal,
            AssemblyName = assemblyName,
            GameSymbolsPath = gameSymbols,
            JsonOut = jsonOut,
            MdOut = mdOut
        };
    }
}

sealed class BridgeIndex
{
    public Dictionary<string, BridgedMethod> Methods { get; } = new(StringComparer.Ordinal);

    public static BridgeIndex Build(ModuleDefinition deobfModule, ModuleDefinition normalModule)
    {
        var typeMap = BuildDeobfTypeToRawMap(deobfModule);
        var normalTypes = Flatten(normalModule.Types).ToDictionary(t => NormalizeTypeName(t.FullName), StringComparer.Ordinal);
        var index = new BridgeIndex();

        foreach (var deobfType in Flatten(deobfModule.Types))
        {
            var stableOwner = NormalizeTypeName(deobfType.FullName);
            if (!typeMap.TryGetValue(stableOwner, out var rawOwner))
                continue;
            if (!normalTypes.TryGetValue(rawOwner, out var normalType))
                continue;

            var deobfMethods = deobfType.Methods
                .Where(m => !m.IsConstructor && m.Name != "Finalize")
                .Select((m, metadataIndex) => new MethodWithSignature(
                    m,
                    metadataIndex,
                    NormalizeMethodSignature(m, typeMap),
                    GetMethodEvidenceKey(m),
                    GetMethodFingerprint(m, typeMap)))
                .ToList();
            var normalMethods = normalType.Methods
                .Where(m => !m.IsConstructor && m.Name != "Finalize")
                .Select((m, metadataIndex) => new MethodWithSignature(
                    m,
                    metadataIndex,
                    NormalizeMethodSignature(m, null),
                    GetMethodEvidenceKey(m),
                    GetMethodFingerprint(m, null)))
                .ToList();

            var normalBySignature = normalMethods
                .GroupBy(x => x.Signature, StringComparer.Ordinal)
                .ToDictionary(g => g.Key, g => g.OrderBy(x => x.MetadataIndex).ToList(), StringComparer.Ordinal);
            var deobfBySignature = deobfMethods
                .GroupBy(x => x.Signature, StringComparer.Ordinal)
                .ToDictionary(g => g.Key, g => g.OrderBy(x => x.MetadataIndex).ToList(), StringComparer.Ordinal);

            foreach (var deobfMethod in deobfMethods)
            {
                if (!normalBySignature.TryGetValue(deobfMethod.Signature, out var normalGroup))
                    continue;
                var deobfGroup = deobfBySignature[deobfMethod.Signature];
                var ordinal = deobfGroup.FindIndex(x => ReferenceEquals(x.Method, deobfMethod.Method));
                if (ordinal < 0 || ordinal >= normalGroup.Count)
                    continue;
                var selection = SelectNormalMethod(deobfMethod, normalGroup, ordinal);
                var normalMethod = selection.Method.Method;
                var stableKey = stableOwner + "::" + deobfMethod.Method.Name + deobfMethod.Signature;
                index.Methods[stableKey] = new BridgedMethod
                {
                    StableMethodKey = stableKey,
                    StableOwnerName = stableOwner,
                    StableMethodName = deobfMethod.Method.Name,
                    RawOwnerName = rawOwner,
                    RawMethodName = normalMethod.Name,
                    RawSignature = deobfMethod.Signature,
                    Ordinal = ordinal,
                    OverloadCount = Math.Max(deobfGroup.Count, normalGroup.Count),
                    EvidenceKey = selection.Method.EvidenceKey,
                    Fingerprint = selection.Method.Fingerprint,
                    SelectionBasis = selection.Basis,
                    CandidateCount = selection.CandidateCount,
                    EvidenceMatchCount = selection.EvidenceMatchCount,
                    FingerprintMatchCount = selection.FingerprintMatchCount,
                    Ambiguous = selection.Ambiguous
                };
            }
        }

        return index;
    }

    private static Dictionary<string, string> BuildDeobfTypeToRawMap(ModuleDefinition module)
    {
        var result = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var type in Flatten(module.Types))
        {
            var raw = GetObfuscatedName(type.CustomAttributes);
            if (string.IsNullOrWhiteSpace(raw))
                continue;
            result[NormalizeTypeName(type.FullName)] = NormalizeTypeName(raw);
        }
        return result;
    }

    private static string NormalizeMethodSignature(MethodDefinition method, Dictionary<string, string>? deobfTypeMap)
    {
        var parameters = string.Join(",", method.Parameters.Select(p => NormalizeTypeReference(p.ParameterType, deobfTypeMap)));
        return "(" + parameters + "):" + NormalizeTypeReference(method.ReturnType, deobfTypeMap);
    }

    private static string NormalizeTypeReference(TypeReference type, Dictionary<string, string>? deobfTypeMap)
    {
        if (type is ByReferenceType byRef)
            return NormalizeTypeReference(byRef.ElementType, deobfTypeMap) + "&";
        if (type is PointerType pointer)
            return NormalizeTypeReference(pointer.ElementType, deobfTypeMap) + "*";
        if (type is ArrayType array)
            return NormalizeTypeReference(array.ElementType, deobfTypeMap) + "[" + new string(',', Math.Max(0, array.Rank - 1)) + "]";
        if (type is GenericInstanceType generic)
        {
            var args = string.Join(",", generic.GenericArguments.Select(a => NormalizeTypeReference(a, deobfTypeMap)));
            return NormalizeTypeReference(generic.ElementType, deobfTypeMap) + "<" + args + ">";
        }
        if (type is GenericParameter gp)
            return "!" + gp.Position + ":" + gp.Name;

        var normalized = NormalizeTypeName(type.FullName);
        if (deobfTypeMap != null && deobfTypeMap.TryGetValue(normalized, out var raw))
            return raw;
        return normalized;
    }

    private static IEnumerable<TypeDefinition> Flatten(IEnumerable<TypeDefinition> types)
    {
        foreach (var type in types)
        {
            yield return type;
            foreach (var nested in Flatten(type.NestedTypes))
                yield return nested;
        }
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

    private static MethodSelection SelectNormalMethod(MethodWithSignature deobfMethod, IReadOnlyList<MethodWithSignature> normalGroup, int ordinal)
    {
        var ranked = normalGroup
            .Select((method, candidateOrdinal) => new MethodCandidateScore(
                method,
                candidateOrdinal,
                string.Equals(method.Fingerprint, deobfMethod.Fingerprint, StringComparison.Ordinal) && !string.IsNullOrWhiteSpace(deobfMethod.Fingerprint),
                string.Equals(method.EvidenceKey, deobfMethod.EvidenceKey, StringComparison.Ordinal) && !string.IsNullOrWhiteSpace(deobfMethod.EvidenceKey),
                Math.Abs(candidateOrdinal - ordinal)))
            .OrderByDescending(x => x.FingerprintMatch)
            .ThenByDescending(x => x.EvidenceMatch)
            .ThenBy(x => x.OrdinalDistance)
            .ThenBy(x => x.CandidateOrdinal)
            .ToList();

        var best = ranked[0];
        var bestTuple = (best.FingerprintMatch, best.EvidenceMatch, best.OrdinalDistance);
        var bestCount = ranked.Count(x => (x.FingerprintMatch, x.EvidenceMatch, x.OrdinalDistance) == bestTuple);
        var bestBasis = BuildSelectionBasis(best.FingerprintMatch, best.EvidenceMatch, best.OrdinalDistance == 0);

        if (bestCount == 1 && (best.FingerprintMatch || best.EvidenceMatch || best.OrdinalDistance == 0))
        {
            return new MethodSelection(
                best.Method,
                bestBasis,
                normalGroup.Count,
                ranked.Count(x => x.EvidenceMatch),
                ranked.Count(x => x.FingerprintMatch),
                false);
        }

        var fallback = normalGroup[Math.Min(ordinal, normalGroup.Count - 1)];
        return new MethodSelection(
            fallback,
            string.IsNullOrWhiteSpace(deobfMethod.EvidenceKey) && string.IsNullOrWhiteSpace(deobfMethod.Fingerprint)
                ? "ordinal"
                : "ordinal-fallback",
            normalGroup.Count,
            ranked.Count(x => x.EvidenceMatch),
            ranked.Count(x => x.FingerprintMatch),
            true);
    }

    private static string? GetMethodEvidenceKey(MethodDefinition method)
    {
        var parts = new List<string>();
        var callerCount = CanonicalizeAttribute(method.CustomAttributes, "CallerCountAttribute");
        if (callerCount != null)
            parts.Add("caller=" + callerCount);

        var cachedScan = CanonicalizeAttribute(method.CustomAttributes, "CachedScanResultsAttribute");
        if (cachedScan != null)
            parts.Add("scan=" + cachedScan);

        if (parts.Count == 0)
            return null;

        return string.Join("|", parts);
    }

    private static string? CanonicalizeAttribute(IEnumerable<CustomAttribute> attributes, string attributeName)
    {
        foreach (var attribute in attributes)
        {
            if (!attribute.AttributeType.Name.Contains(attributeName, StringComparison.Ordinal))
                continue;
            return CanonicalizeCustomAttribute(attribute);
        }
        return null;
    }

    private static string CanonicalizeCustomAttribute(CustomAttribute attribute)
    {
        var parts = new List<string>();
        for (var i = 0; i < attribute.ConstructorArguments.Count; i++)
            parts.Add("ctor" + i + "=" + CanonicalizeValue(attribute.ConstructorArguments[i].Value));
        foreach (var property in attribute.Properties.OrderBy(p => p.Name, StringComparer.Ordinal))
            parts.Add(property.Name + "=" + CanonicalizeValue(property.Argument.Value));
        foreach (var field in attribute.Fields.OrderBy(f => f.Name, StringComparer.Ordinal))
            parts.Add(field.Name + "=" + CanonicalizeValue(field.Argument.Value));
        return attribute.AttributeType.Name + "(" + string.Join(",", parts) + ")";
    }

    private static string CanonicalizeValue(object? value)
    {
        if (value == null)
            return "null";
        if (value is CustomAttributeArgument nested)
            return CanonicalizeCustomAttributeArgument(nested);
        if (value is IEnumerable<CustomAttributeArgument> array)
            return "[" + string.Join(",", array.Select(CanonicalizeCustomAttributeArgument)) + "]";
        if (value is System.Collections.IEnumerable enumerable && value is not string)
            return "[" + string.Join(",", enumerable.Cast<object?>().Select(CanonicalizeValue)) + "]";
        return value.ToString() ?? string.Empty;
    }

    private static string CanonicalizeCustomAttributeArgument(CustomAttributeArgument argument)
    {
        return CanonicalizeValue(argument.Value);
    }

    private static string BuildSelectionBasis(bool fingerprintMatch, bool evidenceMatch, bool ordinalMatch)
    {
        var parts = new List<string>(3);
        if (fingerprintMatch)
            parts.Add("fingerprint");
        if (evidenceMatch)
            parts.Add("evidence");
        if (ordinalMatch)
            parts.Add("ordinal");
        return parts.Count == 0 ? "ordinal-fallback" : string.Join("+", parts);
    }

    private static string? GetMethodFingerprint(MethodDefinition method, Dictionary<string, string>? deobfTypeMap)
    {
        if (!method.HasBody || method.Body == null)
            return null;

        var body = method.Body;
        var instructionIndex = body.Instructions
            .Select((instruction, index) => (instruction, index))
            .ToDictionary(x => x.instruction, x => x.index);

        var tokens = new StringBuilder();
        tokens.Append("ms=").Append(body.MaxStackSize).Append(';');
        tokens.Append("lv=").Append(body.Variables.Count).Append(';');
        tokens.Append("eh=").Append(body.ExceptionHandlers.Count).Append(';');
        tokens.Append("il=").Append(body.InitLocals ? '1' : '0').Append(';');
        tokens.Append("ic=").Append(body.Instructions.Count).Append(';');

        foreach (var instruction in body.Instructions)
        {
            tokens.Append(instruction.OpCode.Code).Append(':').Append(NormalizeOperand(instruction.Operand, deobfTypeMap, instructionIndex)).Append('|');
        }

        foreach (var handler in body.ExceptionHandlers.OrderBy(x => x.TryStart?.Offset ?? -1)
                     .ThenBy(x => x.HandlerStart?.Offset ?? -1)
                     .ThenBy(x => x.FilterStart?.Offset ?? -1))
        {
            tokens.Append("eh[").Append(handler.HandlerType).Append("]:")
                .Append(handler.TryStart?.Offset ?? -1).Append(',')
                .Append(handler.TryEnd?.Offset ?? -1).Append(',')
                .Append(handler.HandlerStart?.Offset ?? -1).Append(',')
                .Append(handler.HandlerEnd?.Offset ?? -1).Append(',')
                .Append(handler.FilterStart?.Offset ?? -1).Append('|');
        }

        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(tokens.ToString()));
        return Convert.ToHexString(hash);
    }

    private static string NormalizeOperand(object? operand, Dictionary<string, string>? deobfTypeMap, IReadOnlyDictionary<Instruction, int> instructionIndex)
    {
        return operand switch
        {
            null => "n",
            string s => "s:" + s,
            sbyte sb => "i:" + sb.ToString(CultureInfo.InvariantCulture),
            byte b => "i:" + b.ToString(CultureInfo.InvariantCulture),
            short sh => "i:" + sh.ToString(CultureInfo.InvariantCulture),
            ushort ush => "i:" + ush.ToString(CultureInfo.InvariantCulture),
            int i => "i:" + i.ToString(CultureInfo.InvariantCulture),
            uint ui => "i:" + ui.ToString(CultureInfo.InvariantCulture),
            long l => "i:" + l.ToString(CultureInfo.InvariantCulture),
            ulong ul => "i:" + ul.ToString(CultureInfo.InvariantCulture),
            float f => "f:" + BitConverter.SingleToInt32Bits(f).ToString(CultureInfo.InvariantCulture),
            double d => "f:" + BitConverter.DoubleToInt64Bits(d).ToString(CultureInfo.InvariantCulture),
            Instruction instruction => "br:" + instructionIndex.GetValueOrDefault(instruction, -1).ToString(CultureInfo.InvariantCulture),
            Instruction[] instructions => "brs:" + string.Join(",", instructions.Select(i => instructionIndex.GetValueOrDefault(i, -1))),
            VariableDefinition variable => "v:" + variable.Index.ToString(CultureInfo.InvariantCulture),
            ParameterDefinition parameter => "p:" + parameter.Index.ToString(CultureInfo.InvariantCulture),
            MethodReference methodReference => "m:" + NormalizeMethodReference(methodReference, deobfTypeMap),
            FieldReference fieldReference => "f:" + NormalizeFieldReference(fieldReference, deobfTypeMap),
            TypeReference typeReference => "t:" + NormalizeTypeReference(typeReference, deobfTypeMap),
            CallSite callSite => "c:" + NormalizeCallSite(callSite, deobfTypeMap),
            CustomAttributeArgument customAttributeArgument => "ca:" + CanonicalizeValue(customAttributeArgument.Value),
            _ when operand is System.Collections.IEnumerable enumerable && operand is not string =>
                "e:[" + string.Join(",", enumerable.Cast<object?>().Select(item => NormalizeOperand(item, deobfTypeMap, instructionIndex))) + "]",
            _ => "o:" + operand.ToString()
        };
    }

    private static string NormalizeMethodReference(MethodReference methodReference, Dictionary<string, string>? typeMap)
    {
        var owner = methodReference.DeclaringType == null ? "?" : NormalizeTypeReference(methodReference.DeclaringType, typeMap);
        var parameters = string.Join(",", methodReference.Parameters.Select(p => NormalizeTypeReference(p.ParameterType, typeMap)));
        var genericArity = methodReference.GenericParameters.Count;
        return owner + "::(" + parameters + "):" + NormalizeTypeReference(methodReference.ReturnType, typeMap) + "#" + genericArity;
    }

    private static string NormalizeFieldReference(FieldReference fieldReference, Dictionary<string, string>? typeMap)
    {
        var owner = fieldReference.DeclaringType == null ? "?" : NormalizeTypeReference(fieldReference.DeclaringType, typeMap);
        return owner + ":" + NormalizeTypeReference(fieldReference.FieldType, typeMap);
    }

    private static string NormalizeCallSite(CallSite callSite, Dictionary<string, string>? typeMap)
    {
        var parameters = string.Join(",", callSite.Parameters.Select(p => NormalizeTypeReference(p.ParameterType, typeMap)));
        return "(" + parameters + "):" + NormalizeTypeReference(callSite.ReturnType, typeMap);
    }
}

sealed record MethodWithSignature(MethodDefinition Method, int MetadataIndex, string Signature, string? EvidenceKey, string? Fingerprint);

sealed record MethodSelection(MethodWithSignature Method, string Basis, int CandidateCount, int EvidenceMatchCount, int FingerprintMatchCount, bool Ambiguous);
sealed record MethodCandidateScore(MethodWithSignature Method, int CandidateOrdinal, bool FingerprintMatch, bool EvidenceMatch, int OrdinalDistance);

sealed class BridgedMethod
{
    public required string StableMethodKey { get; init; }
    public required string StableOwnerName { get; init; }
    public required string StableMethodName { get; init; }
    public required string RawOwnerName { get; init; }
    public required string RawMethodName { get; init; }
    public required string RawSignature { get; init; }
    public required int Ordinal { get; init; }
    public required int OverloadCount { get; init; }
    public string? EvidenceKey { get; init; }
    public string? Fingerprint { get; init; }
    public required string SelectionBasis { get; init; }
    public required int CandidateCount { get; init; }
    public required int EvidenceMatchCount { get; init; }
    public required int FingerprintMatchCount { get; init; }
    public required bool Ambiguous { get; init; }
}

sealed class MethodRenameRow
{
    public required string StableMethodKey { get; init; }
    public required string StableOwnerName { get; init; }
    public required string StableMethodName { get; init; }
    public required string RawSignature { get; init; }
    public required string OldRawOwnerName { get; init; }
    public required string OldRawMethodName { get; init; }
    public required string NewRawOwnerName { get; init; }
    public required string NewRawMethodName { get; init; }
    public required int OldOrdinal { get; init; }
    public required int NewOrdinal { get; init; }
    public required int OldOverloadCount { get; init; }
    public required int NewOverloadCount { get; init; }
    public string? OldEvidenceKey { get; init; }
    public string? NewEvidenceKey { get; init; }
    public string? OldFingerprint { get; init; }
    public string? NewFingerprint { get; init; }
    public required string OldSelectionBasis { get; init; }
    public required string NewSelectionBasis { get; init; }
    public required int OldCandidateCount { get; init; }
    public required int NewCandidateCount { get; init; }
    public required int OldEvidenceMatchCount { get; init; }
    public required int NewEvidenceMatchCount { get; init; }
    public required int OldFingerprintMatchCount { get; init; }
    public required int NewFingerprintMatchCount { get; init; }
    public required bool Ambiguous { get; init; }
    public required bool GameSymbolsMethodRelevant { get; init; }
    public required bool GameSymbolsOwnerRelevant { get; init; }
    public bool GameSymbolsRelevant => GameSymbolsMethodRelevant || GameSymbolsOwnerRelevant;
    public string SelectionBasis => OldSelectionBasis + " / " + NewSelectionBasis;
}

sealed class Report
{
    public required string AssemblyName { get; init; }
    public required string OldDeobfDir { get; init; }
    public required string OldNormalDir { get; init; }
    public required string NewDeobfDir { get; init; }
    public required string NewNormalDir { get; init; }
    public string? GameSymbolsPath { get; init; }
    public int GameSymbolsHintCount { get; init; }
    public int GameSymbolsMethodHintCount { get; init; }
    public int GameSymbolsTypeHintCount { get; init; }
    public int GameSymbolsFieldHintCount { get; init; }
    public int OldStableMethodCount { get; init; }
    public int NewStableMethodCount { get; init; }
    public required List<MethodRenameRow> RawMethodRenameRows { get; init; }
    public required List<MethodRenameRow> GameSymbolsRelevantRawMethodRenameRows { get; init; }
    public required List<MethodRenameRow> UnambiguousGameSymbolsRelevantRows { get; init; }
    public required List<MethodRenameRow> AmbiguousGameSymbolsRelevantRows { get; init; }
    public required List<MethodRenameRow> GameSymbolsMethodNameRows { get; init; }
    public required List<MethodRenameRow> UnambiguousGameSymbolsMethodNameRows { get; init; }
    public required List<MethodRenameRow> AmbiguousGameSymbolsMethodNameRows { get; init; }
    public required List<MethodRenameRow> OwnerOnlyGameSymbolsRows { get; init; }
}

sealed class GameSymbolHints
{
    public HashSet<string> MethodHints { get; } = new(StringComparer.Ordinal);
    public HashSet<string> TypeHints { get; } = new(StringComparer.Ordinal);
    public HashSet<string> FieldHints { get; } = new(StringComparer.Ordinal);
    public int TotalHintCount => MethodHints.Count + TypeHints.Count + FieldHints.Count;
}
