// Verifies that every type/member reference the built OfflineUnlockMod.dll makes into the game's IL2CPP
// interop assemblies resolves against the LIVE interop (<Golden Era>/BepInEx/interop), not just against the
// assemblies the build compiled with. A reference that does not resolve throws MissingMethodException /
// MissingFieldException / TypeLoadException at runtime the first time its method is JIT-compiled.
//
// Three tiers:
//   direct : a TypeRef/MemberRef in the plugin into a live interop assembly that does not resolve there.
//   body   : a live interop method the plugin calls whose own IL references a member that does not resolve
//            (e.g. an interop wrapper whose body needs a ReadOnlySpan member missing from Il2Cppmscorlib).
//   stripped : a live interop method the plugin calls that the game build stripped; it resolves, but its body
//            only throws NotSupportedException("Method unstripping failed") (e.g. GUILayout.Space).
//
// Pre-existing findings live in an allow-list file (one key per line, '#' comments). New findings fail.
// Usage:
//   VerifyPluginLiveInteropRefs --plugin <dll> --interop <dir> [--search <dir>]... --allowlist <file>
//                               [--write-allowlist]
using Mono.Cecil;
using Mono.Cecil.Cil;

if (args.Length == 3 && args[0] == "--list-members")
{
    // Diagnostic: --list-members <interop assembly path> <type name>
    var probe = ModuleDefinition.ReadModule(args[1], new ReaderParameters { InMemory = true });
    foreach (var t in probe.GetTypes().Where(t => t.Name == args[2]))
    {
        Console.WriteLine(t.FullName);
        foreach (var p in t.Properties) Console.WriteLine("  prop " + p.PropertyType.Name + " " + p.Name);
    }
    return 0;
}

string? pluginPath = null, interopDir = null, allowlistPath = null;
var searchDirs = new List<string>();
var writeAllowlist = false;
for (var i = 0; i < args.Length; i++)
{
    switch (args[i])
    {
        case "--plugin": pluginPath = args[++i]; break;
        case "--interop": interopDir = args[++i]; break;
        case "--search": searchDirs.Add(args[++i]); break;
        case "--allowlist": allowlistPath = args[++i]; break;
        case "--write-allowlist": writeAllowlist = true; break;
        default:
            Console.Error.WriteLine("FAIL: unknown argument " + args[i]);
            return 2;
    }
}

if (pluginPath == null || interopDir == null || allowlistPath == null)
{
    Console.Error.WriteLine("FAIL: --plugin, --interop and --allowlist are required.");
    return 2;
}
if (!File.Exists(pluginPath)) { Console.Error.WriteLine("FAIL: plugin not found: " + pluginPath); return 2; }
if (!Directory.Exists(interopDir)) { Console.Error.WriteLine("FAIL: live interop dir not found: " + interopDir); return 2; }

var liveAssemblies = new HashSet<string>(
    Directory.GetFiles(interopDir, "*.dll").Select(p => Path.GetFileNameWithoutExtension(p)!),
    StringComparer.OrdinalIgnoreCase);
if (liveAssemblies.Count == 0) { Console.Error.WriteLine("FAIL: no assemblies in " + interopDir); return 2; }

var resolver = new DefaultAssemblyResolver();
foreach (var d in resolver.GetSearchDirectories().ToArray())
    resolver.RemoveSearchDirectory(d);
// Live interop wins over everything else: that is what the game loads.
resolver.AddSearchDirectory(interopDir);
foreach (var d in searchDirs.Where(Directory.Exists))
    resolver.AddSearchDirectory(d);

var module = ModuleDefinition.ReadModule(pluginPath, new ReaderParameters { AssemblyResolver = resolver, InMemory = true });

string? ScopeAssembly(TypeReference? t)
{
    while (t != null)
    {
        if (t is TypeSpecification spec) { t = spec.ElementType; continue; }
        if (t.DeclaringType != null && t.Scope is not AssemblyNameReference) { t = t.DeclaringType; continue; }
        return t.Scope switch
        {
            AssemblyNameReference a => a.Name,
            ModuleDefinition m => m.Assembly?.Name?.Name,
            _ => null,
        };
    }
    return null;
}

bool IsLive(TypeReference? t)
{
    var asm = ScopeAssembly(t);
    return asm != null && liveAssemblies.Contains(asm);
}

IMemberDefinition? TryResolve(MemberReference r)
{
    try
    {
        return r switch
        {
            MethodReference m => m.Resolve(),
            FieldReference f => f.Resolve(),
            TypeReference t => t.Resolve(),
            _ => null,
        };
    }
    catch (AssemblyResolutionException)
    {
        return null;
    }
}

string Key(string tier, MemberReference r) => tier + "\t[" + (ScopeAssembly(r as TypeReference ?? r.DeclaringType) ?? "?") + "] " + r.FullName;

var findings = new SortedSet<string>(StringComparer.Ordinal);
var users = new Dictionary<string, SortedSet<string>>(StringComparer.Ordinal);

void Note(string key, string? user)
{
    findings.Add(key);
    if (user == null) return;
    if (!users.TryGetValue(key, out var set)) users[key] = set = new SortedSet<string>(StringComparer.Ordinal);
    if (set.Count < 3) set.Add(user);
}

// Map each plugin method's references back to the method using them, for diagnostics.
var referencedBy = new Dictionary<MemberReference, string>();
foreach (var type in module.GetTypes())
{
    foreach (var method in type.Methods)
    {
        if (!method.HasBody) continue;
        foreach (var ins in method.Body.Instructions)
        {
            if (ins.Operand is MemberReference mr && !referencedBy.ContainsKey(mr))
                referencedBy[mr] = type.FullName + "::" + method.Name;
        }
    }
}

string? UserOf(MemberReference r) => referencedBy.TryGetValue(r, out var u) ? u : null;

foreach (var tr in module.GetTypeReferences())
{
    if (!IsLive(tr)) continue;
    if (TryResolve(tr) == null) Note(Key("direct-type", tr), UserOf(tr));
}

var bodyChecked = new HashSet<string>(StringComparer.Ordinal);
var directMembers = 0;
foreach (var mr in module.GetMemberReferences())
{
    if (!IsLive(mr.DeclaringType)) continue;
    directMembers++;
    var def = TryResolve(mr);
    if (def == null)
    {
        Note(Key("direct-member", mr), UserOf(mr));
        continue;
    }

    if (def is not MethodDefinition md || !md.HasBody) continue;
    if (!bodyChecked.Add(md.FullName)) continue;
    // A method the game build stripped resolves fine, but its interop body only throws
    // NotSupportedException("Method unstripping failed") at call time (GUILayout.Space, 2026-10-05).
    if (md.Body.Instructions.Any(i => i.OpCode.Code == Code.Ldstr && i.Operand as string == "Method unstripping failed"))
        Note(Key("stripped", mr), UserOf(mr));
    foreach (var ins in md.Body.Instructions)
    {
        if (ins.Operand is not MemberReference inner) continue;
        // Open generic parameters (T, TKey) are not resolvable references; skip them.
        if (inner is TypeReference openType && openType.GetElementType() is GenericParameter) continue;
        var innerType = inner as TypeReference ?? inner.DeclaringType;
        if (!IsLive(innerType)) continue;
        if (TryResolve(inner) == null)
            Note("body\t" + md.FullName + " -> [" + ScopeAssembly(innerType) + "] " + inner.FullName, UserOf(mr));
    }
}

var allow = new HashSet<string>(StringComparer.Ordinal);
if (File.Exists(allowlistPath))
{
    foreach (var line in File.ReadAllLines(allowlistPath))
    {
        if (string.IsNullOrWhiteSpace(line) || line.StartsWith('#')) continue;
        allow.Add(line.TrimEnd());
    }
}

if (writeAllowlist)
{
    var header = new[]
    {
        "# Pre-existing OfflineUnlockMod references that do not resolve against the LIVE Golden Era interop.",
        "# Generated by tools/verify_plugin_live_interop_refs --write-allowlist. Each line is a reference the",
        "# plugin already carried when the gate was introduced; it throws at runtime if its method ever JITs.",
        "# Remove lines as they are fixed. Never add a line to make a new reference pass: fix the reference.",
    };
    File.WriteAllLines(allowlistPath, header.Concat(findings));
    Console.WriteLine("Wrote " + findings.Count + " allow-listed finding(s) to " + allowlistPath);
    return 0;
}

var fresh = findings.Where(f => !allow.Contains(f)).ToList();
var stale = allow.Where(a => !findings.Contains(a)).ToList();
Console.WriteLine("Live interop reference check: " + directMembers + " member ref(s) into " + liveAssemblies.Count
                  + " live interop assemblies; findings=" + findings.Count + " allow-listed=" + (findings.Count - fresh.Count)
                  + " new=" + fresh.Count + " fixed-but-still-listed=" + stale.Count + ".");
foreach (var s in stale)
    Console.WriteLine("NOTE: allow-listed reference now resolves (remove it from the list): " + s.Replace('\t', ' '));
if (fresh.Count == 0)
{
    Console.WriteLine("OK: no new unresolved references into the live interop.");
    return 0;
}

foreach (var f in fresh)
{
    Console.Error.WriteLine("FAIL: unresolved against live interop: " + f.Replace('\t', ' ')
                            + (users.TryGetValue(f, out var u) ? "  (used by " + string.Join(", ", u) + ")" : ""));
}
Console.Error.WriteLine("FAIL: " + fresh.Count + " new reference(s) the live game cannot bind. Resolve them through GameSymbols / reflection over live interop instead of a direct compile-time reference.");
return 1;
