// Shape index of an Il2CppInterop directory, consumed by tools/validate_game_symbols_hint_contract.py.
//
// Counts mirror what the plugin's runtime resolver (GameMember.TypeShape.Of) reads by reflection,
// so a shape pinned from this index is the shape the plugin checks in game:
//   fields  = Type.GetFields(Public|NonPublic|Instance|Static|DeclaredOnly).Length
//   methods = Type.GetMethods(Public|NonPublic|Instance|Static|DeclaredOnly).Length (constructors excluded)
//   base    = BaseType generic definition FullName, nested types joined with '+'
// Output (TSV, UTF-8):
//   T  asm  runtimeFullName  name  obfuscatedName  base  fields  methods
//   M  asm  ownerRuntimeFullName  name  returnType  paramTypes(comma)          (Hex*/Assembly-CSharp only)
//   F  asm  ownerRuntimeFullName  name  fieldType                              (Hex*/Assembly-CSharp only)
using Mono.Cecil;

if (args.Length != 2)
{
    Console.Error.WriteLine("usage: InteropShapeIndex <interopDir> <out.tsv>");
    return 2;
}
var dir = args[0];
var outPath = args[1];
if (!File.Exists(Path.Combine(dir, "Hex.dll")))
{
    Console.Error.WriteLine("interop dir has no Hex.dll: " + dir);
    return 2;
}

static string RuntimeName(TypeReference t)
{
    // Cecil nests with '/', reflection with '+'.
    return t.FullName.Replace('/', '+');
}

static string BaseDef(TypeDefinition t)
{
    var bt = t.BaseType;
    if (bt == null) return "";
    if (bt is GenericInstanceType git) bt = git.ElementType;
    return RuntimeName(bt);
}

static string Obf(ICustomAttributeProvider p)
{
    foreach (var a in p.CustomAttributes)
        if (a.AttributeType.Name == "ObfuscatedNameAttribute" && a.ConstructorArguments.Count > 0)
            return a.ConstructorArguments[0].Value?.ToString() ?? "";
    return "";
}

static string Clean(string s) => s.Replace('\t', ' ').Replace('\n', ' ').Replace('\r', ' ');

var rows = 0;
using (var w = new StreamWriter(outPath, false, new System.Text.UTF8Encoding(false)))
{
    w.NewLine = "\n";
    foreach (var f in Directory.GetFiles(dir, "*.dll").OrderBy(p => p, StringComparer.Ordinal))
    {
        var asmName = Path.GetFileNameWithoutExtension(f);
        ModuleDefinition module;
        try { module = ModuleDefinition.ReadModule(f); }
        catch (Exception ex)
        {
            Console.Error.WriteLine("skip " + asmName + ": " + ex.Message);
            continue;
        }
        using (module)
        {
            var members = asmName.StartsWith("Hex", StringComparison.Ordinal) || asmName == "Assembly-CSharp";
            foreach (var t in module.GetTypes())
            {
                if (t.Name == "<Module>") continue;
                var full = RuntimeName(t);
                var methods = t.Methods.Count(m => !m.IsConstructor);
                w.WriteLine($"T\t{asmName}\t{Clean(full)}\t{Clean(t.Name)}\t{Clean(Obf(t))}\t{Clean(BaseDef(t))}\t{t.Fields.Count}\t{methods}");
                rows++;
                if (!members) continue;
                foreach (var m in t.Methods)
                {
                    if (m.IsConstructor) continue;
                    w.WriteLine($"M\t{asmName}\t{Clean(full)}\t{Clean(m.Name)}\t{Clean(m.ReturnType.Name)}\t{Clean(string.Join(",", m.Parameters.Select(p => p.ParameterType.Name)))}");
                    rows++;
                }
                foreach (var fd in t.Fields)
                {
                    w.WriteLine($"F\t{asmName}\t{Clean(full)}\t{Clean(fd.Name)}\t{Clean(fd.FieldType.Name)}");
                    rows++;
                }
            }
        }
    }
}
Console.WriteLine("InteropShapeIndex: " + rows + " rows -> " + outPath);
return 0;
