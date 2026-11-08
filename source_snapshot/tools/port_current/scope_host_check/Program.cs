using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text.RegularExpressions;

// One-off: recompute GameSymbolScope.Hash (the plugin's own code) over each golden value the plugin
// really holds, and compare with the hash baked into GameSymbolsCurrent.g.cs by the Python generator.
var dll = args[0]; var gcs = args[1]; var bepCore = args[2];
AppDomain.CurrentDomain.AssemblyResolve += (_, e) =>
{
    var p = Path.Combine(bepCore, new AssemblyName(e.Name).Name + ".dll");
    return File.Exists(p) ? Assembly.LoadFrom(p) : null;
};
var interopDir = args.Length > 4 ? args[4] : null;
AppDomain.CurrentDomain.AssemblyResolve += (_, e) =>
{
    if (interopDir == null) return null;
    var p = Path.Combine(interopDir, new AssemblyName(e.Name).Name + ".dll");
    return File.Exists(p) ? Assembly.LoadFrom(p) : null;
};
if (args.Length > 3)
{
    // Simulated current build: GameBuild hashes <mirror>/GameAssembly.dll (read only), and the live
    // interop is loaded so GameSymbolScope.VerifyType checks the real live types' shapes.
    var bep = Assembly.LoadFrom(Path.Combine(bepCore, "BepInEx.Core.dll"));
    var paths = bep.GetType("BepInEx.Paths", true);
    paths.GetProperty("GameRootPath").GetSetMethod(true).Invoke(null, new object[] { args[3] });
    if (interopDir != null)
        foreach (var f in Directory.GetFiles(interopDir, "*.dll"))
            try { Assembly.LoadFrom(f); } catch (Exception ex) { Console.WriteLine("interop load " + Path.GetFileName(f) + ": " + ex.GetType().Name); }
}
var asm = Assembly.LoadFrom(dll);
var gs = asm.GetType("OfflineUnlockMod.GameSymbols", true);
var scope = asm.GetType("OfflineUnlockMod.GameSymbolScope", true);
var hash = scope.GetMethod("Hash", BindingFlags.Static | BindingFlags.NonPublic);
var rewrite = scope.GetProperty("RewriteForCurrentBuild", BindingFlags.Static | BindingFlags.NonPublic);
Console.WriteLine("RewriteForCurrentBuild=" + rewrite.GetValue(null));
var rx = new Regex(@"GameSymbolScope\.(\w+)\(""([^""]+)"", [\w.]+, 0x([0-9A-F]{8})u");
int ok = 0, bad = 0, skipped = 0;
foreach (var line in File.ReadLines(gcs))
{
    var m = rx.Match(line);
    if (!m.Success || args.Length > 3) continue;
    var kind = m.Groups[1].Value; var symbol = m.Groups[2].Value; var want = Convert.ToUInt32(m.Groups[3].Value, 16);
    var parts = symbol.Split('.');
    Type t = gs;
    for (var i = 0; i < parts.Length - 1 && t != null; i++) t = t.GetNestedType(parts[i], BindingFlags.NonPublic | BindingFlags.Public);
    var f = t?.GetField(parts[^1], BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public);
    if (f == null) { Console.WriteLine("NOFIELD " + symbol); bad++; continue; }
    var v = f.GetValue(null);
    string[] flat;
    string[] Hints(object ms) => (string[])ms.GetType().GetField("NameHints", BindingFlags.Instance | BindingFlags.NonPublic).GetValue(ms);
    string[] FieldPair(object fs) => new[] { (string)fs.GetType().GetField("NativeFieldInfoName", BindingFlags.Instance | BindingFlags.NonPublic).GetValue(fs), (string)fs.GetType().GetField("FieldName", BindingFlags.Instance | BindingFlags.NonPublic).GetValue(fs) };
    switch (kind.Replace("Refuse", ""))
    {
        case "Types": case "Members": case "": flat = (string[])v; break;
        case "Type": case "Member": case "One": flat = new[] { (string)v }; break;   // scalar `static readonly string`
        case "Method": case "MethodSplit": flat = Hints(v); break;   // MethodSplit: golden side is still the golden hints
        case "Field": flat = FieldPair(v); break;
        case "Methods": flat = ((Array)v).Cast<object>().SelectMany(Hints).ToArray(); break;
        case "Fields": flat = ((Array)v).Cast<object>().SelectMany(FieldPair).ToArray(); break;
        case "NamedCounts": flat = ((Array)v).Cast<object>().Select(o => (string)o.GetType().GetField("Item1").GetValue(o)).ToArray(); break;
        default: Console.WriteLine("SKIP kind " + kind + " " + symbol); skipped++; continue;
    }
    var got = (uint)hash.Invoke(null, new object[] { flat });
    if (got == want) ok++; else { bad++; Console.WriteLine($"MISMATCH {kind} {symbol} py={want:X8} cs={got:X8}"); }
}
Console.WriteLine($"ok={ok} mismatch={bad} skipped={skipped}");
if (args.Length > 3)
{
    foreach (var nt in gs.GetNestedTypes(BindingFlags.NonPublic | BindingFlags.Public))
        System.Runtime.CompilerServices.RuntimeHelpers.RunClassConstructor(nt.TypeHandle);
    var lit = new Regex(@"new string\[\] \{ ([^}]*) \}, new string\[\] \{ ([^}]*) \}");
    foreach (var line in File.ReadLines(gcs))
    {
        var m = rx.Match(line);
        if (!m.Success || m.Groups[1].Value != "Types") continue;
        var lm = lit.Match(line);
        var gen = Regex.Matches(lm.Groups[1].Value, @"null|""([^""]*)""").Select(x => x.Value == "null" ? null : x.Groups[1].Value).ToArray();
        var chk = Regex.Matches(lm.Groups[2].Value, @"null|""([^""]*)""").Select(x => x.Value == "null" ? null : x.Groups[1].Value).ToArray();
        var parts = m.Groups[2].Value.Split('.');
        Type t = gs;
        for (var i = 0; i < parts.Length - 1; i++) t = t.GetNestedType(parts[i], BindingFlags.NonPublic | BindingFlags.Public);
        var now = (string[])t.GetField(parts[^1], BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public).GetValue(null);
        for (var i = 0; i < gen.Length; i++)
            if (gen[i] != null && now[i].StartsWith("!unresolved"))
                Console.WriteLine($"VERIFY-FAIL {m.Groups[2].Value}[{i}] {gen[i]} check={(i < chk.Length ? chk[i] : null)}");
    }
    Console.WriteLine(scope.GetMethod("Describe", BindingFlags.Static | BindingFlags.NonPublic).Invoke(null, null));
    var verified = scope.GetField("VerifiedTypes", BindingFlags.Static | BindingFlags.NonPublic)?.GetValue(null);
    if (verified is System.Collections.ICollection c) Console.WriteLine("verified type literals: " + c.Count);
    // Every scoped (non-sentinel) type literal must name a loaded live type; count sentinels vs live per kind.
    int live = 0, sent = 0;
    foreach (var line in File.ReadLines(gcs))
    {
        var m = rx.Match(line);
        if (!m.Success || m.Groups[1].Value != "Types") continue;
        var parts = m.Groups[2].Value.Split('.');
        Type t = gs;
        for (var i = 0; i < parts.Length - 1; i++) t = t.GetNestedType(parts[i], BindingFlags.NonPublic | BindingFlags.Public);
        foreach (var s in (string[])t.GetField(parts[^1], BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public).GetValue(null))
            if (s.StartsWith("!unresolved")) sent++; else live++;
    }
    Console.WriteLine($"Types() positions after rewrite: live={live} sentinel={sent}");
}
return bad == 0 ? 0 : 1;
