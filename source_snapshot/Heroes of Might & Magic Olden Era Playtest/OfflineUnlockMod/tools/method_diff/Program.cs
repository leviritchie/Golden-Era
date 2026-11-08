using System.Reflection;
using System.Text.RegularExpressions;
using Mono.Cecil;

if (args.Length < 2)
{
    Console.Error.WriteLine("Usage: MethodDiff <old-interop-dlv> <new-interop-dlv> [--source <src-dlv>] [--type <TypeName>]...");
    Console.Error.WriteLine("  Scans source for GameMember calls and diffs interop assemblies.");
    Console.Error.WriteLine("  Without --source or --type, diffs all types present in both assemblies.");
    return 1;
}

var oldDir = args[0];
var newDir = args[1];
var sourceDirs = new List<string>();
var filterTypes = new List<string>();

for (var i = 2; i < args.Length; i++)
{
    if (args[i] == "--source" && i + 1 < args.Length)
        sourceDirs.Add(args[++i]);
    else if (args[i] == "--type" && i + 1 < args.Length)
        filterTypes.Add(args[++i]);
}

// Load assemblies
var oldAsm = LoadAssembly(Path.Combine(oldDir, "Hex.dll"));
var newAsm = LoadAssembly(Path.Combine(newDir, "Hex.dll"));
if (oldAsm == null || newAsm == null)
{
    Console.Error.WriteLine("Failed to load one or both Hex.dll assemblies.");
    return 1;
}

// Discover types we care about from source
var referencedTypes = new HashSet<string>(StringComparer.Ordinal);
foreach (var srcDir in sourceDirs)
    ScanSourceForTypes(srcDir, referencedTypes);
foreach (var t in filterTypes)
    referencedTypes.Add(t);

// If no types specified, show summary of all changed types
var showAll = referencedTypes.Count == 0;

// Build type maps (FullName -> TypeDefinition) for both assemblies
var oldTypes = BuildTypeMap(oldAsm);
var newTypes = BuildTypeMap(newAsm);

var typeNamesToCheck = showAll
    ? oldTypes.Keys.Intersect(newTypes.Keys, StringComparer.Ordinal).OrderBy(x => x, StringComparer.Ordinal).ToList()
    : referencedTypes.OrderBy(x => x, StringComparer.Ordinal).ToList();

var totalChanged = 0;
var totalMethodsChanged = 0;

foreach (var typeName in typeNamesToCheck)
{
    oldTypes.TryGetValue(typeName, out var oldType);
    newTypes.TryGetValue(typeName, out var newType);

    if (oldType == null && newType == null) continue;

    if (oldType == null) { Console.WriteLine($"ADDED  {typeName}"); totalChanged++; continue; }
    if (newType == null) { Console.WriteLine($"REMOVED {typeName}"); totalChanged++; continue; }

    // Build method signature maps: signature -> list of names
    var oldSigs = BuildMethodMap(oldType);
    var newSigs = BuildMethodMap(newType);

    var typeHasChanges = false;

    // Find renamed methods (same signature, different name) and new/removed ones
    foreach (var (sig, oldNames) in oldSigs)
    {
        if (newSigs.TryGetValue(sig, out var newNames))
        {
            // Same signature exists in both – check for name changes
            var oldSet = new HashSet<string>(oldNames, StringComparer.Ordinal);
            var newSet = new HashSet<string>(newNames, StringComparer.Ordinal);
            var added = newSet.Except(oldSet).ToList();
            var removed = oldSet.Except(newSet).ToList();

            if (added.Count > 0 || removed.Count > 0)
            {
                if (!typeHasChanges) { Console.WriteLine($"\n--- {typeName} ---"); typeHasChanges = true; }
                Console.WriteLine($"  RENAMED {sig}");
                if (removed.Count > 0) Console.WriteLine($"    - {string.Join(", ", removed)}");
                if (added.Count > 0) Console.WriteLine($"    + {string.Join(", ", added)}");
                totalMethodsChanged += added.Count + removed.Count;
            }
        }
        else
        {
            if (!typeHasChanges) { Console.WriteLine($"\n--- {typeName} ---"); typeHasChanges = true; }
            Console.WriteLine($"  REMOVED {sig} (was: {string.Join(", ", oldNames)})");
            totalMethodsChanged++;
        }
    }

    // Find new signatures in new assembly
    foreach (var (sig, newNames) in newSigs)
    {
        if (!oldSigs.ContainsKey(sig))
        {
            if (!typeHasChanges) { Console.WriteLine($"\n--- {typeName} ---"); typeHasChanges = true; }
            Console.WriteLine($"  NEW    {sig} (now: {string.Join(", ", newNames)})");
            totalMethodsChanged++;
        }
    }

    if (typeHasChanges) totalChanged++;
}

if (!showAll)
    Console.WriteLine($"\nTotal: {totalChanged} types changed, {totalMethodsChanged} methods affected.");
else
    Console.WriteLine($"\nTotal: {totalChanged} types with changes.");

return 0;

// ── helpers ──

static ModuleDefinition? LoadAssembly(string path)
{
    if (!File.Exists(path)) { Console.Error.WriteLine($"Not found: {path}"); return null; }
    try
    {
        var resolver = new DefaultAssemblyResolver();
        resolver.AddSearchDirectory(Path.GetDirectoryName(path)!);
        return ModuleDefinition.ReadModule(path, new ReaderParameters { AssemblyResolver = resolver, InMemory = true });
    }
    catch (Exception ex) { Console.Error.WriteLine($"Failed to load {path}: {ex.Message}"); return null; }
}

static Dictionary<string, TypeDefinition> BuildTypeMap(ModuleDefinition mod)
{
    var map = new Dictionary<string, TypeDefinition>(StringComparer.Ordinal);
    foreach (var t in mod.Types)
        CollectTypes(t, map);
    return map;
}

static void CollectTypes(TypeDefinition type, Dictionary<string, TypeDefinition> map)
{
    map[type.FullName.Replace("/", "+")] = type;
    foreach (var nested in type.NestedTypes)
        CollectTypes(nested, map);
}

static Dictionary<string, List<string>> BuildMethodMap(TypeDefinition type)
{
    // signature -> list of method names
    var map = new Dictionary<string, List<string>>(StringComparer.Ordinal);
    foreach (var m in type.Methods)
    {
        // Skip special-name methods (get_/set_/add_/remove_) and constructors
        if (m.IsSpecialName || m.IsConstructor || m.Name == "Finalize") continue;
        var sig = MethodSignature(m);
        if (!map.TryGetValue(sig, out var list))
        {
            list = new List<string>();
            map[sig] = list;
        }
        list.Add(m.Name);
    }
    return map;
}

static string MethodSignature(MethodDefinition m)
{
    var ret = m.ReturnType.FullName;
    var parms = string.Join(", ", m.Parameters.Select(p => p.ParameterType.FullName));
    return $"{ret} ({parms})";
}

static void ScanSourceForTypes(string dlv, HashSet<string> types)
{
    foreach (var file in Directory.EnumerateFiles(dlv, "*.cs", SearchOption.AllDirectories))
    {
        // Skip tools/, bin/, obj/, artifacts/
        if (file.Contains("\\tools\\") || file.Contains("\\bin\\") || file.Contains("\\obj\\") || file.Contains("\\artifacts\\"))
            continue;

        string content;
        try { content = File.ReadAllText(file); }
        catch { continue; }

        // GameMember.FindType uses hint names, not type names — skip.

        // Extract "Hex.<TypeName>" patterns from GetHexType calls
        foreach (Match match in Regex.Matches(content, "GetHexType\\(\"([^\"]+)\"\\)"))
        {
            types.Add(match.Groups[1].Value);
        }

        // Extract declaringType references from FindMethods/FindMethodsByNames calls
        foreach (Match match in Regex.Matches(content, @"typeof\(([^)]+)\)"))
        {
            var t = match.Groups[1].Value;
            if (t.Contains("Hex.") || t.Contains("Bh"))
                types.Add(t);
        }

        // Also catch "Hex.Session..." strings used with FindRuntimeType
        foreach (Match match in Regex.Matches(content, "\"Hex\\.\\w[\\w\\.]+\""))
        {
            var t = match.Value.Trim('"');
            if (t.StartsWith("Hex.", StringComparison.Ordinal) && t.Count(c => c == '.') >= 2)
                types.Add(t);
        }
    }
}
