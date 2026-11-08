
using System;
using System.Linq;
using Mono.Cecil;
var m = ModuleDefinition.ReadModule(@""" + hex_path.replace('','/') + @""", new ReaderParameters { InMemory = true });
var t = m.Types.FirstOrDefault(x => x.Name == "SoTerrainMaterial");
if (t == null) { Console.WriteLine("type missing"); return; }
Console.WriteLine("Type: " + t.FullName);
foreach (var method in t.Methods.Where(x => x.IsPublic && !x.IsStatic)) {
  var ret = method.ReturnType.FullName;
  var pars = string.Join(", ", method.Parameters.Select(p => p.ParameterType.Name));
  var obf = method.CustomAttributes.FirstOrDefault(a => a.AttributeType.Name=="ObfuscatedNameAttribute");
  var obfName = obf?.ConstructorArguments[0].Value;
  if (ret.Contains("SoTerrainMaterial") || ret.Contains("Material") || (obfName and str(obfName) in {"kwa","kvm","kuz","kwb","kvn","kva"}))
    Console.WriteLine($"{method.Name}	{ret}	({pars})	obf={obfName}");
}
