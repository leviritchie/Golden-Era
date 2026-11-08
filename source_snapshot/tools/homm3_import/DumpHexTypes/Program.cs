using System.Reflection;
using Hex;
using Hex.Session.Battle;

static void DumpType(string label, Type t)
{
	Console.WriteLine("==== " + label + " ====");
	if (t == null)
	{
		Console.WriteLine("(null type)");
		return;
	}
	Console.WriteLine("FullName: " + t.FullName);
	Console.WriteLine("Base: " + t.BaseType?.FullName);
	foreach (var p in t.GetProperties(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
		Console.WriteLine("  prop " + p.PropertyType.Name + " " + p.Name);

	foreach (var m in t.GetMethods(BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
	{
		if (m.IsSpecialName)
			continue;
		var ps = string.Join(", ", m.GetParameters().Select(x => x.ParameterType.Name + " " + x.Name));
		var st = m.IsStatic ? "static " : "";
		Console.WriteLine("  meth " + st + m.ReturnType.Name + " " + m.Name + "(" + ps + ")");
	}
}

DumpType("clb", typeof(clb));
DumpType("BhUnitWindowPreview", typeof(BhUnitWindowPreview));
DumpType("BhUnitPreviews", typeof(BhUnitPreviews));

var bhUnitPreviewType = typeof(BhUnitWindowPreview).GetProperty("cgel", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance)?.PropertyType;
DumpType("BhUnitPreview (from BhUnitWindowPreview.cgel)", bhUnitPreviewType);

var camCtrlType = typeof(BhUnitWindowPreview).GetProperty("cgeq", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance)?.PropertyType;
DumpType("UnitPreviewCameraControl (from cgeq)", camCtrlType);

var rotType = typeof(BhUnitWindowPreview).GetProperty("cgep", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance)?.PropertyType;
DumpType("UnitPreviewRotation (from cgep)", rotType);

Console.WriteLine("==== BhUnitPreviews methods returning clb ====");
foreach (var m in typeof(BhUnitPreviews).GetMethods(BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic))
{
	if (m.ReturnType == typeof(clb))
		Console.WriteLine(m.ReturnType.Name + " " + m.Name + "(" + string.Join(", ", m.GetParameters().Select(p => p.ParameterType.Name)) + ")");
}

// ---- Adventure / hero army strip (bottom bar unit portraits): name discovery ----
static bool ArmyUiNameHit(string full)
{
	if (string.IsNullOrEmpty(full))
		return false;
	if (!full.StartsWith("Hex.UI", StringComparison.Ordinal))
		return false;
	var s = full.AsSpan();
	static bool Has(ReadOnlySpan<char> a, string b) => a.IndexOf(b, StringComparison.OrdinalIgnoreCase) >= 0;
	return Has(s, "Army")
	       || Has(s, "Troop")
	       || Has(s, "Stack")
	       || Has(s, "Slot")
	       || Has(s, "Bar")
	       || Has(s, "Tray")
	       || Has(s, "Portrait")
	       || Has(s, "Icon")
	       || Has(s, "Badge")
	       || Has(s, "Creature")
	       || Has(s, "Garrison")
	       || Has(s, "HeroPanel")
	       || Has(s, "Adventure")
	       || Has(s, "MapHud")
	       || Has(s, "Hud");
}

Console.WriteLine();
Console.WriteLine("==== Hex.UI types whose FullName suggests army / stacks / HUD (heuristic) ====");
var hexAsm = typeof(clb).Assembly;
Type[] all;
try
{
	all = hexAsm.GetTypes();
}
catch (ReflectionTypeLoadException ex)
{
	all = ex.Types.Where(t => t != null).ToArray()!;
	Console.WriteLine("(partial load: " + ex.LoaderExceptions?.Length + " loader errors)");
}

var hits = all.Where(t => ArmyUiNameHit(t.FullName ?? "")).OrderBy(t => t.FullName, StringComparer.Ordinal).ToList();
Console.WriteLine("Count: " + hits.Count);
foreach (var t in hits)
{
	var props = t.GetProperties(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
		.Where(p => p.Name.IndexOf("portrait", StringComparison.OrdinalIgnoreCase) >= 0
		            || p.Name.IndexOf("icon", StringComparison.OrdinalIgnoreCase) >= 0
		            || p.Name.IndexOf("image", StringComparison.OrdinalIgnoreCase) >= 0
		            || p.Name.IndexOf("sprite", StringComparison.OrdinalIgnoreCase) >= 0
		            || p.Name.IndexOf("army", StringComparison.OrdinalIgnoreCase) >= 0
		            || p.Name.IndexOf("stack", StringComparison.OrdinalIgnoreCase) >= 0
		            || p.Name.IndexOf("slot", StringComparison.OrdinalIgnoreCase) >= 0)
		.Take(24)
		.Select(p => p.PropertyType.Name + " " + p.Name);
	var propStr = string.Join("; ", props);
	Console.WriteLine("- " + t.FullName + (string.IsNullOrEmpty(propStr) ? "" : " | props: " + propStr));
}

Console.WriteLine();
Console.WriteLine("==== Broader: Hex.* types with Hero + (Army|Stack|Slot|Bar|Troop|Tray|Creature) in name ====");
var heroArmy = all
	.Where(t =>
	{
		var f = t.FullName ?? "";
		if (f.IndexOf("Hero", StringComparison.OrdinalIgnoreCase) < 0)
			return false;
		return f.IndexOf("Army", StringComparison.OrdinalIgnoreCase) >= 0
		       || f.IndexOf("Stack", StringComparison.OrdinalIgnoreCase) >= 0
		       || f.IndexOf("Slot", StringComparison.OrdinalIgnoreCase) >= 0
		       || f.IndexOf("Bar", StringComparison.OrdinalIgnoreCase) >= 0
		       || f.IndexOf("Troop", StringComparison.OrdinalIgnoreCase) >= 0
		       || f.IndexOf("Tray", StringComparison.OrdinalIgnoreCase) >= 0
		       || f.IndexOf("Creature", StringComparison.OrdinalIgnoreCase) >= 0
		       || f.IndexOf("Unit", StringComparison.OrdinalIgnoreCase) >= 0;
	})
	.OrderBy(t => t.FullName, StringComparer.Ordinal)
	.ToList();
Console.WriteLine("Count: " + heroArmy.Count);
foreach (var t in heroArmy)
	Console.WriteLine("- " + t.FullName);

Console.WriteLine();
Console.WriteLine("==== Types named Bh*Stack* or Bh*Army* (any namespace) ====");
foreach (var t in all.Where(t =>
	         {
		         var n = t.Name ?? "";
		         return n.StartsWith("Bh", StringComparison.Ordinal)
		                && (n.IndexOf("Stack", StringComparison.OrdinalIgnoreCase) >= 0
		                    || n.IndexOf("Army", StringComparison.OrdinalIgnoreCase) >= 0);
	         })
	         .OrderBy(t => t.FullName, StringComparer.Ordinal))
	Console.WriteLine("- " + t.FullName);

static void DumpTypeShort(Type t, int maxProps = 40)
{
	if (t == null)
		return;
	Console.WriteLine("==== " + t.FullName + " ====");
	var props = t.GetProperties(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
		.Where(p => !p.Name.StartsWith("m_", StringComparison.Ordinal) && p.Name != "Pointer" && p.Name != "ObjectClass")
		.Take(maxProps);
	foreach (var p in props)
		Console.WriteLine("  prop " + p.PropertyType.Name + " " + p.Name);
}

Console.WriteLine();
Console.WriteLine("==== Focus dump: likely adventure / profile unit strip ====");
DumpTypeShort(typeof(Hex.Session.UI.HeroProfile.BhHeroSlotView));
DumpTypeShort(typeof(Hex.Session.UI.HeroProfile.BhHeroSlotViews));
DumpTypeShort(typeof(Hex.UI.BhHeroPortraitSwapView));
DumpTypeShort(typeof(Hex.Session.UI.BhTavernHeroUnitView));
DumpTypeShort(typeof(Hex.UI.BattleUIController));

Console.WriteLine();
Console.WriteLine("==== BhInventoryItemView + BhHeroDataView (unit portrait wiring) ====");
var invItem = all.FirstOrDefault(t => t.FullName == "Hex.Session.UI.HeroProfile.BhInventoryItemView")
              ?? all.FirstOrDefault(t => (t.FullName ?? "").EndsWith("BhInventoryItemView", StringComparison.Ordinal));
if (invItem != null)
	DumpTypeShort(invItem, 60);
else
	Console.WriteLine("(BhInventoryItemView not found)");

var dataView = all.FirstOrDefault(t => t.FullName == "Hex.Session.UI.HeroProfile.BhHeroDataView")
               ?? all.FirstOrDefault(t => (t.FullName ?? "").EndsWith("BhHeroDataView", StringComparison.Ordinal));
if (dataView != null)
	DumpTypeShort(dataView, 60);
else
	Console.WriteLine("(BhHeroDataView not found)");

static void DumpMethods(Type t, int max = 35)
{
	if (t == null)
		return;
	Console.WriteLine("==== methods " + t.FullName + " (declared, trimmed) ====");
	var methods = t.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly)
		.Where(m => !m.IsSpecialName && !m.Name.StartsWith("add_", StringComparison.Ordinal) && !m.Name.StartsWith("remove_", StringComparison.Ordinal))
		.Take(max);
	foreach (var m in methods)
	{
		var ps = string.Join(", ", m.GetParameters().Select(p => p.ParameterType.Name + " " + p.Name));
		Console.WriteLine("  " + m.ReturnType.Name + " " + m.Name + "(" + ps + ")");
	}
}

var slotViewT = typeof(Hex.Session.UI.HeroProfile.BhHeroSlotView);
DumpMethods(slotViewT, 45);
var invT = typeof(Hex.Session.UI.HeroProfile.BhInventoryItemView);
DumpMethods(invT, 45);

Console.WriteLine();
Console.WriteLine("==== Types named exactly Item (any namespace) ====");
foreach (var t in all.Where(t => t.Name == "Item").OrderBy(t => t.FullName, StringComparer.Ordinal))
	Console.WriteLine("- " + t.FullName);

var logicItem = all.FirstOrDefault(t => t.FullName == "Hex.Session.Logic.Item");
if (logicItem != null)
{
	Console.WriteLine();
	Console.WriteLine("==== Hex.Session.Logic.Item (inventory / squad stack) ====");
	DumpTypeShort(logicItem, 45);
}
