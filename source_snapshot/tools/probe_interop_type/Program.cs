using Mono.Cecil;

if (args.Length >= 2 && string.Equals(args[0], "--find-native-field", StringComparison.OrdinalIgnoreCase))
{
    var path = Path.GetFullPath(args[1]);
    var needle = args.Length > 2 ? args[2] : null;
    var module = ModuleDefinition.ReadModule(path, new ReaderParameters { InMemory = true });
    foreach (var type in module.Types.Concat(module.Types.SelectMany(t => t.NestedTypes)))
    {
        foreach (var field in type.Fields)
        {
            if (needle != null
                && field.Name.IndexOf(needle, StringComparison.Ordinal) < 0
                && !string.Equals(field.Name, "NativeFieldInfoPtr_" + needle, StringComparison.Ordinal))
                continue;
            if (!field.Name.StartsWith("NativeFieldInfoPtr", StringComparison.Ordinal))
                continue;
            var typeObf = ReadObfuscatedName(type);
            var fieldObf = ReadObfuscatedName(field);
            Console.WriteLine(type.Name + (typeObf != null ? " typeObf=" + typeObf : "") + "\t" + field.Name + (fieldObf != null ? " fieldObf=" + fieldObf : ""));
        }
    }
    return 0;
}

if (args.Length >= 2 && string.Equals(args[0], "--find-field-obf", StringComparison.OrdinalIgnoreCase))
{
    var path = Path.GetFullPath(args[1]);
    var wanted = args.Skip(2).ToHashSet(StringComparer.Ordinal);
    var module = ModuleDefinition.ReadModule(path, new ReaderParameters { InMemory = true });
    foreach (var type in module.Types.Concat(module.Types.SelectMany(t => t.NestedTypes)))
    {
        foreach (var field in type.Fields)
        {
            var obf = ReadObfuscatedName(field);
            if (obf == null || (wanted.Count > 0 && !wanted.Contains(obf)))
                continue;
            Console.WriteLine(obf + "\t" + type.Name + "." + field.Name + "\t" + field.FieldType.Name);
        }
    }
    return 0;
}

if (args.Length >= 2 && string.Equals(args[0], "--find-fieldobject-methods", StringComparison.OrdinalIgnoreCase))
{
    var path = Path.GetFullPath(args[1]);
    var module = ModuleDefinition.ReadModule(path, new ReaderParameters { InMemory = true });
    foreach (var type in module.Types.Concat(module.Types.SelectMany(t => t.NestedTypes)))
    {
        foreach (var method in type.Methods)
        {
            if (!method.ReturnType.Name.Contains("FieldObject", StringComparison.Ordinal)
                && method.ReturnType.FullName?.Contains("FieldObject", StringComparison.Ordinal) != true)
                continue;
            if (method.Parameters.Count < 2 || method.Parameters.Count > 8)
                continue;
            var typeObf = ReadObfuscatedName(type);
            var methodObf = ReadObfuscatedName(method);
            var pars = string.Join(", ", method.Parameters.Select(p => p.ParameterType.Name));
            Console.WriteLine((method.IsStatic ? "static " : "instance ")
                + type.Name + (typeObf != null ? " typeObf=" + typeObf : "") + "." + method.Name
                + (methodObf != null ? " obf=" + methodObf : "") + " (" + pars + ") -> " + method.ReturnType.Name);
        }
    }
    return 0;
}

if (args.Length >= 2 && string.Equals(args[0], "--find-spawn-object", StringComparison.OrdinalIgnoreCase))
{
    var path = Path.GetFullPath(args[1]);
    var module = ModuleDefinition.ReadModule(path, new ReaderParameters { InMemory = true });
    foreach (var type in module.Types.Concat(module.Types.SelectMany(t => t.NestedTypes)))
    {
        foreach (var method in type.Methods)
        {
            if (method.Parameters.Count != 6)
                continue;
            if (!string.Equals(method.ReturnType.Name, "FieldObject", StringComparison.Ordinal)
                && method.ReturnType.FullName?.IndexOf("FieldObject", StringComparison.Ordinal) < 0)
                continue;
            if (method.Parameters[1].ParameterType.Name != "Unit")
                continue;
            if (method.Parameters[3].ParameterType.Name != "Int32"
                || method.Parameters[4].ParameterType.Name != "String"
                || method.Parameters[5].ParameterType.Name != "Boolean")
                continue;
            var typeObf = ReadObfuscatedName(type);
            var methodObf = ReadObfuscatedName(method);
            var pars = string.Join(", ", method.Parameters.Select(p => p.ParameterType.Name));
            Console.WriteLine((method.IsStatic ? "static " : "instance ")
                + type.Name + (typeObf != null ? " typeObf=" + typeObf : "") + "." + method.Name
                + (methodObf != null ? " obf=" + methodObf : "") + " (" + pars + ")");
        }
    }
    return 0;
}

if (args.Length >= 3 && string.Equals(args[0], "--native-field-chain", StringComparison.OrdinalIgnoreCase))
{
    var path = Path.GetFullPath(args[1]);
    var ownerTypeName = args[2];
    var module = ModuleDefinition.ReadModule(path, new ReaderParameters { InMemory = true });
    TypeDefinition? FindType(string name)
    {
        foreach (var type in module.Types.Concat(module.Types.SelectMany(t => t.NestedTypes)))
        {
            if (string.Equals(type.Name, name, StringComparison.Ordinal)
                || string.Equals(type.FullName, name, StringComparison.Ordinal))
                return type;
        }
        return null;
    }
    for (var type = FindType(ownerTypeName); type != null; type = type.BaseType?.Resolve())
    {
        var typeObf = ReadObfuscatedName(type);
        Console.WriteLine("TYPE " + type.FullName + (typeObf != null ? " obf=" + typeObf : ""));
        foreach (var field in type.Fields.Where(f => f.Name.StartsWith("NativeFieldInfoPtr", StringComparison.Ordinal)))
        {
            var fieldObf = ReadObfuscatedName(field);
            Console.WriteLine("  " + field.Name + (fieldObf != null ? " obf=" + fieldObf : ""));
        }
    }
    return 0;
}

if (args.Length >= 3 && string.Equals(args[0], "--native-method-fields", StringComparison.OrdinalIgnoreCase))
{
    var path = Path.GetFullPath(args[1]);
    var ownerTypeName = args[2];
    var module = ModuleDefinition.ReadModule(path, new ReaderParameters { InMemory = true });
    TypeDefinition? FindType(string name)
    {
        foreach (var type in module.Types.Concat(module.Types.SelectMany(t => t.NestedTypes)))
        {
            if (string.Equals(type.Name, name, StringComparison.Ordinal)
                || string.Equals(type.FullName, name, StringComparison.Ordinal))
                return type;
        }
        return null;
    }

    var owner = FindType(ownerTypeName);
    if (owner == null)
    {
        Console.Error.WriteLine("Type not found: " + ownerTypeName);
        return 1;
    }

    Console.WriteLine("TYPE " + owner.FullName + " obf=" + ReadObfuscatedName(owner) + " native-method-fields=metadata-order");
    foreach (var field in owner.Fields.Where(f => f.Name.StartsWith("NativeMethodInfoPtr", StringComparison.Ordinal)))
        Console.WriteLine("  " + field.Name);
    return 0;
}

if (args.Length >= 2 && string.Equals(args[0], "--fields-of-type", StringComparison.OrdinalIgnoreCase))
{
    var path = Path.GetFullPath(args[1]);
    var ownerName = args.Length > 2 ? args[2] : null;
    var fieldTypeNeedle = args.Length > 3 ? args[3] : null;
    var module = ModuleDefinition.ReadModule(path, new ReaderParameters { InMemory = true });
    foreach (var type in module.Types.Concat(module.Types.SelectMany(t => t.NestedTypes)))
    {
        if (ownerName != null && !string.Equals(type.Name, ownerName, StringComparison.Ordinal)
            && !string.Equals(type.FullName, ownerName, StringComparison.Ordinal))
            continue;
        foreach (var field in type.Fields)
        {
            if (fieldTypeNeedle != null
                && !string.Equals(field.FieldType.Name, fieldTypeNeedle, StringComparison.Ordinal)
                && field.FieldType.Name.IndexOf(fieldTypeNeedle, StringComparison.Ordinal) < 0
                && (field.FieldType.FullName?.IndexOf(fieldTypeNeedle, StringComparison.Ordinal) ?? -1) < 0)
                continue;
            Console.WriteLine(type.Name + "." + field.Name + "\t" + field.FieldType.FullName);
        }
    }
    return 0;
}

if (args.Length >= 3 && string.Equals(args[0], "--find-fields-of-type", StringComparison.OrdinalIgnoreCase))
{
    var path = Path.GetFullPath(args[1]);
    var fieldTypeNeedle = args[2];
    var module = ModuleDefinition.ReadModule(path, new ReaderParameters { InMemory = true });
    foreach (var type in module.Types.Concat(module.Types.SelectMany(t => t.NestedTypes)))
    {
        foreach (var field in type.Fields)
        {
            if (!string.Equals(field.FieldType.Name, fieldTypeNeedle, StringComparison.Ordinal)
                && field.FieldType.Name.IndexOf(fieldTypeNeedle, StringComparison.Ordinal) < 0
                && (field.FieldType.FullName?.IndexOf(fieldTypeNeedle, StringComparison.Ordinal) ?? -1) < 0)
                continue;
            var typeObf = ReadObfuscatedName(type);
            var fieldObf = ReadObfuscatedName(field);
            Console.WriteLine(type.Name
                + (typeObf != null ? " typeObf=" + typeObf : "")
                + "."
                + field.Name
                + (fieldObf != null ? " fieldObf=" + fieldObf : "")
                + "\t"
                + field.FieldType.FullName);
        }
    }
    return 0;
}

if (args.Length >= 3 && string.Equals(args[0], "--find-members-of-type", StringComparison.OrdinalIgnoreCase))
{
    var path = Path.GetFullPath(args[1]);
    var typeNeedle = args[2];
    var module = ModuleDefinition.ReadModule(path, new ReaderParameters { InMemory = true });
    foreach (var type in module.Types.Concat(module.Types.SelectMany(t => t.NestedTypes)))
    {
        var typeObf = ReadObfuscatedName(type);
        foreach (var property in type.Properties)
        {
            if (MemberTypeMatches(property.PropertyType, typeNeedle))
                Console.WriteLine(type.Name
                    + (typeObf != null ? " typeObf=" + typeObf : "")
                    + ".property "
                    + property.Name
                    + "\t"
                    + property.PropertyType.FullName);
        }
        foreach (var method in type.Methods.Where(m => !m.IsConstructor))
        {
            if (!MemberTypeMatches(method.ReturnType, typeNeedle))
                continue;
            var methodObf = ReadObfuscatedName(method);
            Console.WriteLine(type.Name
                + (typeObf != null ? " typeObf=" + typeObf : "")
                + ".method "
                + method.Name
                + (methodObf != null ? " methodObf=" + methodObf : "")
                + "\t"
                + method.ReturnType.FullName
                + "("
                + string.Join(", ", method.Parameters.Select(p => p.ParameterType.Name))
                + ")");
        }
    }
    return 0;
}

if (args.Length >= 2 && string.Equals(args[0], "--inspect-logic-hero", StringComparison.OrdinalIgnoreCase))
{
    var path = Path.GetFullPath(args[1]);
    var module = ModuleDefinition.ReadModule(path, new ReaderParameters { InMemory = true });
    var heroType = module.Types.Concat(module.Types.SelectMany(t => t.NestedTypes))
        .FirstOrDefault(t => string.Equals(t.FullName, "Hex.Session.Logic.Hero", StringComparison.Ordinal));
    if (heroType == null)
    {
        Console.Error.WriteLine("Hex.Session.Logic.Hero not found");
        return 1;
    }
    Console.WriteLine("TYPE " + heroType.FullName);
    foreach (var property in heroType.Properties.OrderBy(p => p.Name))
    {
        Console.WriteLine("  property " + property.Name + " -> " + property.PropertyType.FullName);
    }
    foreach (var field in heroType.Fields.Where(f => !f.Name.StartsWith("Native", StringComparison.Ordinal)).OrderBy(f => f.Name))
    {
        Console.WriteLine("  field " + field.Name + " -> " + field.FieldType.FullName);
    }
    foreach (var method in heroType.Methods.Where(m => !m.IsConstructor && m.Parameters.Count == 0 && m.ReturnType.FullName != "System.Void").OrderBy(m => m.Name))
    {
        Console.WriteLine("  method " + method.Name + " -> " + method.ReturnType.FullName);
    }
    return 0;
}

if (args.Length >= 2 && string.Equals(args[0], "--inspect-type-shape", StringComparison.OrdinalIgnoreCase))
{
    var path = Path.GetFullPath(args[1]);
    var wantedTypeName = args.Length > 2 ? args[2] : "Hex.Session.Logic.Hero";
    var module = ModuleDefinition.ReadModule(path, new ReaderParameters { InMemory = true });
    var heroType = module.Types.Concat(module.Types.SelectMany(t => t.NestedTypes))
        .FirstOrDefault(t => string.Equals(t.FullName, wantedTypeName, StringComparison.Ordinal) || string.Equals(t.Name, wantedTypeName, StringComparison.Ordinal));
    if (heroType == null)
    {
        Console.Error.WriteLine("Type not found: " + wantedTypeName);
        return 1;
    }
    Console.WriteLine("TYPE " + heroType.FullName);
    foreach (var property in heroType.Properties.OrderBy(p => p.Name))
    {
        var party = property.PropertyType.Resolve().Properties.Any(p => p.Name.IndexOf("party", StringComparison.OrdinalIgnoreCase) >= 0);
        var status = property.PropertyType.Resolve().Properties.Any(p => p.Name.IndexOf("status", StringComparison.OrdinalIgnoreCase) >= 0);
        if (party || status)
            Console.WriteLine("  bridge? " + property.Name + " -> " + property.PropertyType.Name + " party=" + party + " status=" + status);
    }
    return 0;
}

static bool MemberTypeMatches(TypeReference type, string needle)
{
    return string.Equals(type.Name, needle, StringComparison.Ordinal)
           || type.Name.IndexOf(needle, StringComparison.Ordinal) >= 0
           || (type.FullName?.IndexOf(needle, StringComparison.Ordinal) ?? -1) >= 0;
}

if (args.Length >= 3 && string.Equals(args[0], "--list-methods", StringComparison.OrdinalIgnoreCase))
{
    var path = Path.GetFullPath(args[1]);
    var wantedTypeName = args[2];
    var module = ModuleDefinition.ReadModule(path, new ReaderParameters { InMemory = true });
    var listedType = module.Types.Concat(module.Types.SelectMany(t => t.NestedTypes))
        .FirstOrDefault(t => string.Equals(t.FullName, wantedTypeName, StringComparison.Ordinal) || string.Equals(t.Name, wantedTypeName, StringComparison.Ordinal));
    if (listedType == null)
    {
        Console.Error.WriteLine("Type not found: " + wantedTypeName);
        return 1;
    }
    Console.WriteLine("TYPE " + listedType.FullName + " obf=" + ReadObfuscatedName(listedType));
    foreach (var method in listedType.Methods.Where(m => !m.IsConstructor).OrderBy(m => m.Name))
    {
        var pars = string.Join(", ", method.Parameters.Select(p => p.ParameterType.FullName));
        Console.WriteLine(
            (method.IsStatic ? "static " : "instance ")
            + method.ReturnType.FullName
            + " "
            + method.Name
            + "("
            + pars
            + ") obf="
            + ReadObfuscatedName(method));
    }
    return 0;
}

if (args.Length >= 2 && string.Equals(args[0], "--list-properties", StringComparison.OrdinalIgnoreCase))
{
    var path = Path.GetFullPath(args[1]);
    var wantedTypeName = args.Length > 2 ? args[2] : "Hex.Session.Data.Hero";
    var module = ModuleDefinition.ReadModule(path, new ReaderParameters { InMemory = true });
    var listedType = module.Types.Concat(module.Types.SelectMany(t => t.NestedTypes))
        .FirstOrDefault(t => string.Equals(t.FullName, wantedTypeName, StringComparison.Ordinal));
    if (listedType == null)
    {
        Console.Error.WriteLine("Type not found: " + wantedTypeName);
        return 1;
    }
    Console.WriteLine("TYPE " + listedType.FullName);
    foreach (var property in listedType.Properties.OrderBy(p => p.Name))
        Console.WriteLine("  property " + property.Name + " -> " + property.PropertyType.FullName);
    foreach (var field in listedType.Fields.Where(f => !f.Name.StartsWith("Native", StringComparison.Ordinal)).OrderBy(f => f.Name))
        Console.WriteLine("  field " + field.Name + " -> " + field.FieldType.FullName);
    return 0;
}

if (args.Length >= 2 && string.Equals(args[0], "--has-type", StringComparison.OrdinalIgnoreCase))
{
    var path = Path.GetFullPath(args[1]);
    var wanted = args.Skip(2).ToHashSet(StringComparer.Ordinal);
    var module = ModuleDefinition.ReadModule(path, new ReaderParameters { InMemory = true });
    foreach (var type in module.Types.Concat(module.Types.SelectMany(t => t.NestedTypes)))
    {
        if (wanted.Count > 0 && !wanted.Contains(type.Name) && !wanted.Any(w => type.Name.Contains(w, StringComparison.Ordinal)))
            continue;
        var obf = type.CustomAttributes.FirstOrDefault(a => a.AttributeType.Name == "ObfuscatedNameAttribute");
        var obfName = obf?.ConstructorArguments.Count > 0 ? obf.ConstructorArguments[0].Value?.ToString() : null;
        Console.WriteLine(type.Name + (obfName != null ? "\tobf=" + obfName : ""));
    }
    return 0;
}

if (args.Length >= 2 && string.Equals(args[0], "--find-hero-biome-lookup", StringComparison.OrdinalIgnoreCase))
{
    var path = Path.GetFullPath(args[1]);
    var module = ModuleDefinition.ReadModule(path, new ReaderParameters { InMemory = true });
    foreach (var type in module.Types.Concat(module.Types.SelectMany(t => t.NestedTypes)))
    {
        foreach (var method in type.Methods)
        {
            if (method.Parameters.Count != 1 || method.Parameters[0].ParameterType.Name != "Int32")
                continue;
            if (method.ReturnType.Name != "EHeroSoundType")
                continue;
            var obf = method.CustomAttributes.FirstOrDefault(a => a.AttributeType.Name == "ObfuscatedNameAttribute");
            var obfName = obf?.ConstructorArguments.Count > 0 ? obf.ConstructorArguments[0].Value?.ToString() : null;
            Console.WriteLine(type.Name + "." + method.Name + (obfName != null ? " obf=" + obfName : ""));
        }
    }
    return 0;
}

if (args.Length >= 2 && string.Equals(args[0], "--find-map-build", StringComparison.OrdinalIgnoreCase))
{
    var path = Path.GetFullPath(args[1]);
    var wantedHints = args.Skip(2).ToHashSet(StringComparer.Ordinal);
    var module = ModuleDefinition.ReadModule(path, new ReaderParameters { InMemory = true });
    foreach (var type in module.Types.Concat(module.Types.SelectMany(t => t.NestedTypes)))
    {
        foreach (var method in type.Methods)
        {
            if (method.Parameters.Count != 1 || method.ReturnType.Name != "Void")
                continue;
            var firstParam = method.Parameters[0].ParameterType;
            if (!string.Equals(firstParam.Name, "Map", StringComparison.Ordinal)
                && firstParam.FullName?.EndsWith(".Map", StringComparison.Ordinal) != true)
                continue;
            var obf = method.CustomAttributes.FirstOrDefault(a => a.AttributeType.Name == "ObfuscatedNameAttribute");
            var obfName = obf?.ConstructorArguments.Count > 0 ? obf.ConstructorArguments[0].Value?.ToString() : null;
            if (wantedHints.Count > 0 && (obfName == null || !wantedHints.Contains(obfName)) && !wantedHints.Contains(method.Name))
                continue;
            Console.WriteLine(type.Name + "." + method.Name + (obfName != null ? " obf=" + obfName : ""));
        }
    }
    return 0;
}

if (args.Length >= 2 && string.Equals(args[0], "--type-methods", StringComparison.OrdinalIgnoreCase))
{
    var path = Path.GetFullPath(args[1]);
    var typeNeedle = args.Length > 2 ? args[2] : null;
    var module = ModuleDefinition.ReadModule(path, new ReaderParameters { InMemory = true });
    foreach (var type in module.Types.Concat(module.Types.SelectMany(t => t.NestedTypes)))
    {
        if (typeNeedle != null
            && type.FullName?.IndexOf(typeNeedle, StringComparison.Ordinal) < 0
            && type.Name.IndexOf(typeNeedle, StringComparison.Ordinal) < 0)
            continue;
        var typeObf = type.CustomAttributes.FirstOrDefault(a => a.AttributeType.Name == "ObfuscatedNameAttribute");
        var typeObfName = typeObf?.ConstructorArguments.Count > 0 ? typeObf.ConstructorArguments[0].Value?.ToString() : null;
        Console.WriteLine("== " + type.FullName + (typeObfName != null ? " obf=" + typeObfName : ""));
        foreach (var method in type.Methods.OrderBy(m => m.Name))
        {
            if (method.IsConstructor)
                continue;
            var obf = method.CustomAttributes.FirstOrDefault(a => a.AttributeType.Name == "ObfuscatedNameAttribute");
            var obfName = obf?.ConstructorArguments.Count > 0 ? obf.ConstructorArguments[0].Value?.ToString() : null;
            var pars = string.Join(", ", method.Parameters.Select(p => p.ParameterType.FullName));
            Console.WriteLine("  " + method.Name + (obfName != null ? " obf=" + obfName : "") + " (" + pars + ") -> " + method.ReturnType.FullName);
        }
    }
    return 0;
}

if (args.Length >= 2 && string.Equals(args[0], "--find-unit-init", StringComparison.OrdinalIgnoreCase))
{
    var path = Path.GetFullPath(args[1]);
    var module = ModuleDefinition.ReadModule(path, new ReaderParameters { InMemory = true });
    foreach (var type in module.Types.Concat(module.Types.SelectMany(t => t.NestedTypes)))
    {
        foreach (var method in type.Methods)
        {
            if (method.Parameters.Count != 8)
                continue;
            if (!string.Equals(method.Parameters[0].ParameterType.Name, "Int32", StringComparison.Ordinal))
                continue;
            if (!string.Equals(method.Parameters[4].ParameterType.Name, "Int32", StringComparison.Ordinal))
                continue;
            if (!string.Equals(method.Parameters[5].ParameterType.Name, "Int32", StringComparison.Ordinal))
                continue;
            if (!string.Equals(method.Parameters[6].ParameterType.Name, "Int32", StringComparison.Ordinal))
                continue;
            if (!string.Equals(method.Parameters[7].ParameterType.Name, "String", StringComparison.Ordinal))
                continue;
            var obf = method.CustomAttributes.FirstOrDefault(a => a.AttributeType.Name == "ObfuscatedNameAttribute");
            var obfName = obf?.ConstructorArguments.Count > 0 ? obf.ConstructorArguments[0].Value?.ToString() : null;
            var typeObf = type.CustomAttributes.FirstOrDefault(a => a.AttributeType.Name == "ObfuscatedNameAttribute");
            var typeObfName = typeObf?.ConstructorArguments.Count > 0 ? typeObf.ConstructorArguments[0].Value?.ToString() : null;
            var pars = string.Join(", ", method.Parameters.Select(p => p.ParameterType.FullName));
            Console.WriteLine(
                "type=" + type.FullName
                + (typeObfName != null ? " typeObf=" + typeObfName : "")
                + " method=" + method.Name
                + (obfName != null ? " obf=" + obfName : "")
                + " ret=" + method.ReturnType.FullName
                + " (" + pars + ")");
        }
    }
    return 0;
}

if (args.Length >= 2 && string.Equals(args[0], "--find-elang-hjs", StringComparison.OrdinalIgnoreCase))
{
    var path = Path.GetFullPath(args[1]);
    var module = ModuleDefinition.ReadModule(path, new ReaderParameters { InMemory = true });
    foreach (var type in module.Types.Concat(module.Types.SelectMany(t => t.NestedTypes)))
    {
        foreach (var method in type.Methods)
        {
            if (!method.IsStatic || method.Parameters.Count != 2)
                continue;
            var p0 = method.Parameters[0].ParameterType;
            if (!string.Equals(p0.Name, "ELang", StringComparison.Ordinal)
                && p0.FullName?.EndsWith(".ELang", StringComparison.Ordinal) != true)
                continue;
            var typeObf = ReadObfuscatedName(type);
            var obf = ReadObfuscatedName(method);
            var pars = string.Join(", ", method.Parameters.Select(p => p.ParameterType.FullName));
            Console.WriteLine(
                "type=" + type.FullName
                + (typeObf != null ? " typeObf=" + typeObf : "")
                + " method=" + method.Name
                + (obf != null ? " obf=" + obf : "")
                + " (" + pars + ") -> " + method.ReturnType.FullName);
        }
    }
    return 0;
}

if (args.Length >= 2 && string.Equals(args[0], "--obf-types", StringComparison.OrdinalIgnoreCase))
{
    var path = Path.GetFullPath(args[1]);
    var wanted = args.Skip(2).ToHashSet(StringComparer.Ordinal);
    var module = ModuleDefinition.ReadModule(path, new ReaderParameters { InMemory = true });
    foreach (var type in module.Types.Concat(module.Types.SelectMany(t => t.NestedTypes)))
    {
        foreach (var attr in type.CustomAttributes.Where(a => a.AttributeType.Name == "ObfuscatedNameAttribute"))
        {
            var obf = attr.ConstructorArguments.Count > 0 ? attr.ConstructorArguments[0].Value?.ToString() : null;
            if (obf == null || (wanted.Count > 0 && !wanted.Contains(obf)))
                continue;
            Console.WriteLine(obf + "\t" + type.FullName);
        }
    }
    return 0;
}

if (args.Length < 2)
{
    Console.Error.WriteLine("Usage: ProbeInteropType <Hex.dll> <TypeName>");
    Console.Error.WriteLine("       ProbeInteropType --obf-types <Hex.dll> [obfName ...]");
    return 1;
}

var assemblyPath = Path.GetFullPath(args[0]);
var typeName = args[1];
if (!File.Exists(assemblyPath))
{
    Console.Error.WriteLine("Missing assembly: " + assemblyPath);
    return 1;
}

var moduleDef = ModuleDefinition.ReadModule(assemblyPath, new ReaderParameters { InMemory = true });
var targetType = moduleDef.Types.FirstOrDefault(t => t.Name == typeName)
    ?? moduleDef.Types.SelectMany(t => t.NestedTypes).FirstOrDefault(t => t.Name == typeName);
if (targetType == null)
{
    Console.Error.WriteLine("Type not found: " + typeName);
    return 1;
}

Console.WriteLine("Type: " + targetType.FullName);
var mapOnly = args.Length <= 2 || !string.Equals(args[2], "--all", StringComparison.OrdinalIgnoreCase);
foreach (var method in targetType.Methods.OrderBy(m => m.Name))
{
    if (method.IsConstructor || method.Name.StartsWith("get_", StringComparison.Ordinal) || method.Name.StartsWith("set_", StringComparison.Ordinal))
        continue;
    var obf = method.CustomAttributes.FirstOrDefault(a => a.AttributeType.Name == "ObfuscatedNameAttribute");
    var obfName = obf?.ConstructorArguments.Count > 0 ? obf.ConstructorArguments[0].Value?.ToString() : null;
    var pars = string.Join(", ", method.Parameters.Select(p => p.ParameterType.Name));
    if (mapOnly && (method.Parameters.Count == 0 || method.Parameters[0].ParameterType.Name != "Map"))
        continue;
    Console.WriteLine(
        method.Name
        + "\tret=" + method.ReturnType.Name
        + "\t(" + pars + ")"
        + (obfName != null ? "\tobf=" + obfName : ""));
}

return 0;

static string? ReadObfuscatedName(ICustomAttributeProvider provider)
{
    foreach (var attribute in provider.CustomAttributes)
    {
        if (attribute.AttributeType.Name != "ObfuscatedNameAttribute")
            continue;
        if (attribute.ConstructorArguments.Count == 0)
            continue;
        return attribute.ConstructorArguments[0].Value as string;
    }

    return null;
}
