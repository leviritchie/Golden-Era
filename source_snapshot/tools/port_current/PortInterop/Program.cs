// PortInterop: offline Il2CppInterop generation and indexing for the port-to-current-build pipeline.
//
//   generate --game-assembly <GameAssembly.dll> --metadata <global-metadata.dat> --unity-version <6000.0.66>
//            --unity-libs <BepInEx\unity-libs dir> --out <empty dir>
//       Mirrors BepInEx 6.0.0-be.755 Il2CppInteropManager: Cpp2IL dummy assemblies (AttributeInjector layer)
//       -> Il2CppInterop generator with the BepInEx deobfuscation regex. Writes <out>/interop/*.dll and
//       <out>/native_methods.tsv (Cpp2IL raw method names keyed by IL2CPP metadata token).
//
//   index --interop <interop dir> --out <index.tsv> [--native-methods <native_methods.tsv>]
//       Writes the port index (format "port_index.v2", documented in tools/port_current/README.md).
//
// The Python driver tools/port_current/build_index.py owns path policy (game roots are read-only,
// outputs must live outside them). This program only refuses an --out that already has content.
using System.Text.RegularExpressions;
using ArAssembly = AsmResolver.DotNet.AssemblyDefinition;
using Cpp2IL.Core;
using Cpp2IL.Core.Api;
using Cpp2IL.Core.OutputFormats;
using Cpp2IL.Core.ProcessingLayers;
using Il2CppInterop.Generator;
using Il2CppInterop.Generator.Runners;
using Il2CppInterop.Common;
using LibCpp2IL;
using Microsoft.Extensions.Logging;
using Mono.Cecil;
using TypeDefinition = Mono.Cecil.TypeDefinition;
using MethodDefinition = Mono.Cecil.MethodDefinition;
using Mono.Cecil.Cil;

static class Program
{
    const string DeobfRegex = "^[a-z]{2}$|^[a-z]{3}$|^[a-c][a-z]{3}$"; // BepInEx be.755 UnhollowerDeobfuscationRegex default

    static int Main(string[] argv)
    {
        if (argv.Length == 0) return Fail("usage: PortInterop generate|index --key value ...");
        var a = ParseArgs(argv.Skip(1).ToArray());
        try
        {
            return argv[0] switch
            {
                "generate" => Generate(Req(a, "game-assembly"), Req(a, "metadata"), Req(a, "unity-version"), Req(a, "unity-libs"), Req(a, "out")),
                "index" => Index(Req(a, "interop"), Req(a, "out"), a.GetValueOrDefault("native-methods")),
                "native-addresses" => NativeAddresses(Req(a, "game-assembly"), Req(a, "metadata"), Req(a, "unity-version"), Req(a, "out")),
                _ => Fail("unknown command " + argv[0]),
            };
        }
        catch (ArgumentException e) { return Fail(e.Message); }
    }

    static int Fail(string msg) { Console.Error.WriteLine("PortInterop: " + msg); return 2; }

    static Dictionary<string, string> ParseArgs(string[] a)
    {
        var d = new Dictionary<string, string>();
        for (int i = 0; i < a.Length; i++)
        {
            if (!a[i].StartsWith("--") || i + 1 >= a.Length) throw new ArgumentException("bad argument " + a[i]);
            d[a[i][2..]] = a[++i];
        }
        return d;
    }

    static string Req(Dictionary<string, string> a, string k) =>
        a.TryGetValue(k, out var v) && !string.IsNullOrWhiteSpace(v) ? v : throw new ArgumentException("missing --" + k);

    static void RequireEmptyOrMissing(string dir)
    {
        if (Directory.Exists(dir) && Directory.EnumerateFileSystemEntries(dir).Any())
            throw new ArgumentException("output directory is not empty: " + dir);
    }

    // ---------------------------------------------------------------- generate
    static int Generate(string ga, string md, string ver, string libs, string outDir)
    {
        foreach (var f in new[] { ga, md }) if (!File.Exists(f)) throw new ArgumentException("missing input " + f);
        if (!Directory.Exists(libs)) throw new ArgumentException("missing unity libs dir " + libs);
        RequireEmptyOrMissing(outDir);
        Directory.CreateDirectory(outDir);
        var interopDir = Path.Combine(outDir, "interop");

        Cpp2IL.Core.Logging.Logger.InfoLog += (s, src) => Console.Write("[cpp2il] " + s);
        Cpp2IL.Core.Logging.Logger.WarningLog += (s, src) => Console.Write("[cpp2il warn] " + s);
        Cpp2IL.Core.Logging.Logger.ErrorLog += (s, src) => Console.Write("[cpp2il err] " + s);
        Cpp2IlApi.Init();
        Cpp2IlApi.ConfigureLib(false);
        Cpp2IlApi.InitializeLibCpp2Il(ga, md, AssetRipper.Primitives.UnityVersion.Parse(ver), false);
        var layers = new List<Cpp2IlProcessingLayer> { new AttributeInjectorProcessingLayer() };
        foreach (var l in layers) l.PreProcess(Cpp2IlApi.CurrentAppContext, layers);
        foreach (var l in layers) l.Process(Cpp2IlApi.CurrentAppContext);
        var asms = new AsmResolverDllOutputFormatDefault().BuildAssemblies(Cpp2IlApi.CurrentAppContext);
        LibCpp2IlMain.Reset();
        Cpp2IlApi.CurrentAppContext = null;
        Console.WriteLine("cpp2il assemblies: " + asms.Count);

        WriteNativeMethods(asms, Path.Combine(outDir, "native_methods.tsv"));

        Directory.CreateDirectory(interopDir);
        var opts = new GeneratorOptions
        {
            GameAssemblyPath = ga,
            Source = asms,
            OutputDir = interopDir,
            UnityBaseLibsDir = libs,
            ObfuscatedNamesRegex = new Regex(DeobfRegex),
        };
        opts.AdditionalAssembliesBlacklist.Add("Mono.Security");
        Il2CppInteropGenerator.Create(opts).AddLogger(new ConsoleLogger()).AddInteropAssemblyGenerator().Run();
        Console.WriteLine("done");
        return 0;
    }

    // ---------------------------------------------------------------- native-addresses
    // Native code evidence for the symbol remap's ambiguous member gaps (symbol_remap/native_body.py):
    //   header  #native_addresses.v1  gameAssemblySha256=..  metadataSha256=..
    //   MA  assembly  declaringType  name  token  0xVA     one row per method definition with a native body
    //   MD  index  declaringType  name                       methodDefs index (metadata-usage kind 3)
    //   SL  index  literal                                   string literal index (metadata-usage kind 5)
    //   TY  index  type                                      binary type index (metadata-usage kinds 1/2)
    // Unity 6 metadata-usage globals are initialised lazily at runtime; in the file each holds an encoded
    // token ((kind << 29 | index) << 1 | 1), which native_body.py decodes against these tables.
    // Reads GameAssembly.dll + global-metadata.dat only; writes one TSV outside the game roots.
    static int NativeAddresses(string ga, string md, string ver, string outPath)
    {
        foreach (var f in new[] { ga, md }) if (!File.Exists(f)) throw new ArgumentException("missing input " + f);
        if (File.Exists(outPath)) throw new ArgumentException("output exists: " + outPath);
        Cpp2IlApi.Init();
        Cpp2IlApi.ConfigureLib(false);
        Cpp2IlApi.InitializeLibCpp2Il(ga, md, AssetRipper.Primitives.UnityVersion.Parse(ver), false);
        using var w = new StreamWriter(outPath);
        static string Sha(string p) { using var s = File.OpenRead(p); using var h = System.Security.Cryptography.SHA256.Create(); return Convert.ToHexString(h.ComputeHash(s)); }
        w.WriteLine($"#native_addresses.v1\tgameAssemblySha256={Sha(ga)}\tmetadataSha256={Sha(md)}");
        var defs = LibCpp2IlMain.TheMetadata!.methodDefs;
        int n = 0;
        foreach (var m in defs)
        {
            ulong ptr;
            try { ptr = m.MethodPointer; } catch { continue; }
            if (ptr == 0) continue;
            var t = m.DeclaringType;
            w.WriteLine($"MA\t{t?.DeclaringAssembly?.Name}\t{Clean(t?.FullName)}\t{Clean(m.Name)}\t{Member(m, "token")}\t0x{ptr:X}");
            n++;
        }
        for (var i = 0; i < defs.Length; i++)
            w.WriteLine($"MD\t{i}\t{Clean(defs[i].DeclaringType?.FullName)}\t{Clean(defs[i].Name)}");
        var lits = LibCpp2IlMain.TheMetadata.stringLiterals;
        for (var i = 0; i < lits.Length; i++)
        {
            string s;
            try { s = LibCpp2IlMain.TheMetadata.GetStringLiteralFromIndex((uint)i); } catch (Exception e) { s = "!" + e.GetType().Name; }
            w.WriteLine($"SL\t{i}\t{Clean(s).Replace('\r', ' ')}");
        }
        if (Member(LibCpp2IlMain.Binary!, "AllTypes") is not System.Collections.IList types)
            throw new InvalidOperationException("LibCpp2IL binary exposes no type list");
        for (var i = 0; i < types.Count; i++)
        {
            string s;
            try { s = LibCpp2ILUtils.GetTypeReflectionData((LibCpp2IL.BinaryStructures.Il2CppType)types[i])?.ToString(); }
            catch (Exception e) { s = "!" + e.GetType().Name; }
            w.WriteLine($"TY\t{i}\t{Clean(s)}");
        }
        Console.WriteLine($"native-addresses: {n} method bodies, {defs.Length} method defs, {lits.Length} literals, {types.Count} types -> {outPath}");
        return 0;
    }

    // Field or property by name (case-insensitive, any visibility): LibCpp2IL keeps these internal.
    static object Member(object o, string name, Type t = null)
    {
        t ??= o?.GetType();
        const System.Reflection.BindingFlags F = System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic
            | System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.IgnoreCase;
        for (var c = t; c != null; c = c.BaseType)
        {
            var f = c.GetField(name, F);
            if (f != null) return f.GetValue(o);
            var p = c.GetProperty(name, F);
            if (p != null) return p.GetValue(o);
        }
        return null;
    }

    // Raw (native) method names from the Cpp2IL dummy assemblies, keyed by (assembly, token). The interop
    // wrappers bind methods with IL2CPP.GetIl2CppMethodByToken, so this is the only place the native
    // method name survives.
    static void WriteNativeMethods(List<ArAssembly> asms, string path)
    {
        using var w = new StreamWriter(path);
        w.WriteLine("#native_methods.v1\tassembly\tdeclaringType\tname\ttoken");
        int n = 0;
        foreach (var asm in asms)
        {
            var asmName = asm.Name?.ToString() ?? "";
            if (!IsIndexed(asmName)) continue;
            foreach (var t in asm.ManifestModule.GetAllTypes())
                foreach (var m in t.Methods)
                {
                    var tok = TokenOf(m.CustomAttributes);
                    if (tok == null) continue;
                    w.WriteLine($"NM\t{asmName}\t{t.FullName}\t{m.Name}\t{tok}");
                    n++;
                }
        }
        if (n == 0) throw new InvalidOperationException("Cpp2IL output carried no [Token] attributes; native method names unavailable");
    }

    static string TokenOf(IList<AsmResolver.DotNet.CustomAttribute> attrs)
    {
        foreach (var ca in attrs)
        {
            if (ca.Constructor?.DeclaringType?.Name?.ToString() != "TokenAttribute") continue;
            foreach (var na in ca.Signature?.NamedArguments ?? new List<AsmResolver.DotNet.Signatures.CustomAttributeNamedArgument>())
                if (na.MemberName?.ToString() == "Token") return Convert.ToInt32(na.Argument.Element?.ToString(), 16).ToString();
        }
        return null;
    }

    // Same scope as the calibrated scratch index: every Hex* assembly plus Assembly-CSharp.
    static bool IsIndexed(string asmName) => asmName.StartsWith("Hex") || asmName == "Assembly-CSharp";

    // ---------------------------------------------------------------- index
    static int Index(string dir, string outPath, string nativeMethodsPath)
    {
        if (!Directory.Exists(dir)) throw new ArgumentException("missing interop dir " + dir);
        if (File.Exists(outPath)) throw new ArgumentException("output exists: " + outPath);
        var nativeMethods = new Dictionary<(string, int), string>();
        if (nativeMethodsPath != null)
        {
            foreach (var line in File.ReadLines(nativeMethodsPath))
            {
                if (line.StartsWith("#")) continue;
                var p = line.Split('\t');
                nativeMethods[(p[1], int.Parse(p[4]))] = p[2] + "::" + p[3];
            }
        }
        var tmp = outPath + ".partial";
        using (var w = new StreamWriter(tmp))
        {
            w.WriteLine("#port_index.v2");
            foreach (var f in Directory.GetFiles(dir, "*.dll").OrderBy(x => x, StringComparer.Ordinal))
            {
                var asmName = Path.GetFileNameWithoutExtension(f);
                if (!IsIndexed(asmName)) continue;
                var mod = ModuleDefinition.ReadModule(f);
                int typeOrd = 0;
                foreach (var t in mod.GetTypes()) IndexType(w, asmName, t, typeOrd++, nativeMethods);
            }
        }
        File.Move(tmp, outPath);
        return 0;
    }

    static string Clean(string s) => (s ?? "").Replace('\t', ' ').Replace('\n', ' ');

    static string ObfAttr(Mono.Cecil.ICustomAttributeProvider p)
    {
        foreach (var a in p.CustomAttributes)
            if (a.AttributeType.Name == "ObfuscatedNameAttribute" && a.ConstructorArguments.Count > 0) return a.ConstructorArguments[0].Value?.ToString() ?? "";
        return "";
    }

    static string TypeKind(TypeDefinition t) =>
        t.IsEnum ? "enum" : t.IsInterface ? "interface" : t.IsValueType ? "struct" : "class";

    static void IndexType(StreamWriter w, string asmName, TypeDefinition t, int typeOrd, Dictionary<(string, int), string> nativeMethods)
    {
        // Native identity and member bindings come from the wrapper's static constructor.
        string nativeClass = "";
        var fieldNative = new Dictionary<string, string>(); // NativeFieldInfoPtr_* -> native field name
        var methodToken = new Dictionary<string, int>();    // NativeMethodInfoPtr_* -> metadata token
        var cctor = t.Methods.FirstOrDefault(m => m.Name == ".cctor" && m.HasBody);
        if (cctor != null)
        {
            var ins = cctor.Body.Instructions;
            for (int i = 0; i < ins.Count; i++)
            {
                if (ins[i].OpCode != OpCodes.Call || ins[i].Operand is not MethodReference mr || mr.DeclaringType.Name != "IL2CPP") continue;
                if (mr.Name == "GetIl2CppClass" && i >= 3)
                    nativeClass = $"{ins[i - 3].Operand}|{ins[i - 2].Operand}|{ins[i - 1].Operand}";
                else if (mr.Name == "GetIl2CppNestedType" && i >= 1)
                    nativeClass = "+|" + ins[i - 1].Operand;
                else if (mr.Name == "GetIl2CppField" && i >= 1 && i + 1 < ins.Count && ins[i + 1].Operand is FieldReference fr1)
                    fieldNative[fr1.Name] = ins[i - 1].Operand as string ?? "";
                else if (mr.Name == "GetIl2CppMethodByToken" && i >= 1 && i + 1 < ins.Count && ins[i + 1].Operand is FieldReference fr2 && ins[i - 1].Operand is int tok)
                    methodToken[fr2.Name] = tok;
            }
        }
        var bt = t.BaseType?.FullName ?? "";
        var ifaces = string.Join(";", t.Interfaces.Select(i => i.InterfaceType.FullName));
        w.WriteLine(string.Join("\t", "T", asmName, t.FullName, t.Name, ObfAttr(t), Clean(nativeClass), typeOrd, Clean(bt), TypeKind(t),
            (t.IsAbstract ? "a" : "") + (t.IsSealed ? "s" : "") + (t.IsNested ? "n" : ""), t.GenericParameters.Count,
            t.Fields.Count, t.Methods.Count, Clean(ifaces)));

        int ord = 0;
        foreach (var m in t.Methods)
        {
            string native = "";
            string ptr = FirstLoadedField(m, "NativeMethodInfoPtr_") ?? FirstLoadedField(m, "NativeFieldInfoPtr_");
            if (ptr != null && ptr.StartsWith("NativeMethodInfoPtr_") && methodToken.TryGetValue(ptr, out var tok))
                native = "tok:" + tok + (nativeMethods.TryGetValue((asmName, tok), out var nn) ? ":" + nn.Split("::").Last() : "");
            else if (ptr != null && ptr.StartsWith("NativeFieldInfoPtr_") && fieldNative.TryGetValue(ptr, out var fn))
                native = "fld:" + fn;
            var sig = Clean(m.ReturnType.FullName) + "(" + Clean(string.Join(",", m.Parameters.Select(p => p.ParameterType.FullName))) + ")";
            w.WriteLine(string.Join("\t", "M", asmName, t.FullName, m.Name, native, ord++, m.IsStatic ? "s" : "", sig, ObfAttr(m)));
        }
        ord = 0;
        foreach (var f in t.Fields)
        {
            string native = fieldNative.TryGetValue(f.Name, out var fn) ? "fld:" + fn : methodToken.TryGetValue(f.Name, out var tk) ? "tok:" + tk : "";
            w.WriteLine(string.Join("\t", "F", asmName, t.FullName, f.Name, native, ord++, f.IsStatic ? "s" : "", Clean(f.FieldType.FullName), ObfAttr(f)));
        }
        ord = 0;
        foreach (var p in t.Properties)
        {
            string native = "";
            var getter = p.GetMethod ?? p.SetMethod;
            var ptr = getter == null ? null : FirstLoadedField(getter, "NativeFieldInfoPtr_");
            if (ptr != null && fieldNative.TryGetValue(ptr, out var fn)) native = "fld:" + fn;
            bool isStatic = getter != null && getter.IsStatic;
            w.WriteLine(string.Join("\t", "P", asmName, t.FullName, p.Name, native, ord++, isStatic ? "s" : "", Clean(p.PropertyType.FullName), ObfAttr(p)));
        }
    }

    static string FirstLoadedField(MethodDefinition m, string prefix)
    {
        if (!m.HasBody) return null;
        foreach (var i in m.Body.Instructions)
            if ((i.OpCode == OpCodes.Ldsfld || i.OpCode == OpCodes.Ldsflda) && i.Operand is FieldReference fr && fr.Name.StartsWith(prefix))
                return fr.Name;
        return null;
    }
}

class ConsoleLogger : ILogger
{
    public IDisposable BeginScope<TState>(TState state) => null;
    public bool IsEnabled(LogLevel logLevel) => logLevel >= LogLevel.Information;
    public void Log<TState>(LogLevel l, EventId e, TState s, Exception ex, Func<TState, Exception, string> f)
    { if (IsEnabled(l)) Console.WriteLine("[interop " + l + "] " + f(s, ex)); }
}
