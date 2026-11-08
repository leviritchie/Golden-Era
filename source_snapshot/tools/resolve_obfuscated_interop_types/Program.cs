using Mono.Cecil;

if (args.Length < 2)
{
    Console.Error.WriteLine("Usage: ResolveObfuscatedInteropTypes <Hex.dll> <obfuscatedName> [...]");
    return 1;
}

var assemblyPath = Path.GetFullPath(args[0]);
var targets = args.Skip(1).ToHashSet(StringComparer.Ordinal);
if (!File.Exists(assemblyPath))
{
    Console.Error.WriteLine("Missing assembly: " + assemblyPath);
    return 1;
}

var module = ModuleDefinition.ReadModule(assemblyPath, new ReaderParameters { InMemory = true });
var found = new HashSet<string>(StringComparer.Ordinal);
foreach (var type in module.Types.Concat(module.Types.SelectMany(t => t.NestedTypes)))
{
    var obfuscatedName = ReadObfuscatedName(type);
    if (obfuscatedName == null || !targets.Contains(obfuscatedName))
        continue;

    found.Add(obfuscatedName);
    Console.WriteLine($"{obfuscatedName}\t{type.FullName}");
}

foreach (var missing in targets.Where(name => !found.Contains(name)).OrderBy(name => name))
    Console.Error.WriteLine("MISSING\t" + missing);

return 0;

static string? ReadObfuscatedName(TypeDefinition type)
{
    foreach (var attribute in type.CustomAttributes)
    {
        if (attribute.AttributeType.Name != "ObfuscatedNameAttribute")
            continue;
        if (attribute.ConstructorArguments.Count == 0)
            continue;
        return attribute.ConstructorArguments[0].Value as string;
    }

    return null;
}
