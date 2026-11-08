using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine;
using UnityEngine.SceneManagement;

public static class DisplayWaterDonorRuntimeProbe20260705
{
    private const BindingFlags All = BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
    private static readonly int[] DisplayWaterTileCodes = { 24, 25, 26, 27, 28 };
    private const int DisplayWaterDonorTileCode = 18;

    private static readonly string[] MaterialLookupFieldNames =
    {
        "field_Private_Dictionary_2_Int32_Int32_0",
        "_bseu_k__BackingField",
        "bseu",
        "bsge",
        "bsdu",
        "bscg",
    };

    public static string Run(string requestJson)
    {
        var action = ReadString(requestJson, "action") ?? "dump";
        var sb = new StringBuilder();
        try
        {
            if (string.Equals(action, "patchLookup", StringComparison.OrdinalIgnoreCase))
                PatchLookup(sb);
            else if (string.Equals(action, "dumpMapWaterLevels", StringComparison.OrdinalIgnoreCase))
                DumpMapWaterLevels(sb);
            else if (string.Equals(action, "paintWater", StringComparison.OrdinalIgnoreCase))
                PaintWater(sb, requestJson);
            else if (string.Equals(action, "findMap", StringComparison.OrdinalIgnoreCase))
                FindMapDiagnostics(sb);
            else
                Dump(sb);

            return "{\"ok\":true,\"action\":\"" + Escape(action) + "\",\"scene\":\"" + Escape(SceneManager.GetActiveScene().name ?? "") + "\",\"text\":\"" + Escape(sb.ToString()) + "\"}";
        }
        catch (Exception ex)
        {
            return Json("ok", false, "action", action, "exception", ex.GetType().Name, "message", ex.Message, "stack", ex.StackTrace ?? "");
        }
    }

    private static void Dump(StringBuilder sb)
    {
        var terrain = GetSoTerrainMaterialInstance();
        sb.Append("scene=").Append(SceneManager.GetActiveScene().name ?? "?");
        sb.Append("\nSoTerrainMaterial.instance=").Append(terrain == null ? "null" : DescribeObject(terrain));
        AppendBiomes(sb, terrain, "terrain.biomes");

        var catalog = FindSoTerrainMaterials();
        sb.Append("\ncatalogCount=").Append(catalog.Count);
        for (var i = 0; i < catalog.Count && i < 6; i++)
            AppendBiomes(sb, catalog[i], "catalog[" + i + "].biomes name=" + DescribeObject(catalog[i]));

        var renderers = FindTerrainRenderers();
        sb.Append("\nterrainRendererCount=").Append(renderers.Count);
        for (var i = 0; i < renderers.Count; i++)
            AppendRenderer(sb, renderers[i], i);
    }

    private static void DumpMapWaterLevels(StringBuilder sb)
    {
        var mapType = FindType("Map");
        var map = mapType == null ? null : FindActiveMap(mapType, sb);
        if (map == null)
        {
            sb.Append("map=null");
            return;
        }
        var mapData = GetMapData(map, sb);
        var tilesMap = mapData == null ? null : GetMember(mapData, "tilesMap_") ?? GetMember(mapData, "tilesMap");
        var levelsMap = mapData == null ? null : GetMember(mapData, "levelsMap_") ?? GetMember(mapData, "levelsMap");
        var waterMap = mapData == null ? null : GetMember(mapData, "waterMap_") ?? GetMember(mapData, "waterMap");
        sb.Append("tilesLen=").Append(ArrayLikeLength(tilesMap))
          .Append(" levelsLen=").Append(ArrayLikeLength(levelsMap))
          .Append(" waterLen=").Append(ArrayLikeLength(waterMap));
        var levelHist = new Dictionary<int, int>();
        var tileHist = new Dictionary<int, int>();
        var samples = new List<string>();
        var length = Math.Min(ArrayLikeLength(tilesMap), ArrayLikeLength(levelsMap));
        for (var i = 0; i < length; i++)
        {
            var tile = Convert.ToInt32(GetArrayItem(tilesMap, i) ?? -1);
            if (tile != 18 && (tile < 24 || tile > 28))
                continue;
            var level = Convert.ToInt32(GetArrayItem(levelsMap, i) ?? -99);
            tileHist[tile] = tileHist.GetValueOrDefault(tile) + 1;
            levelHist[level] = levelHist.GetValueOrDefault(level) + 1;
            if (samples.Count < 8)
            {
                var water = waterMap == null ? -99 : Convert.ToInt32(GetArrayItem(waterMap, i) ?? -99);
                samples.Add("n" + i + ":tile" + tile + "/level" + level + "/water" + water);
            }
        }
        sb.Append(" displayWaterTileHistogram=").Append(string.Join(",", tileHist.Select(kv => kv.Key + "=" + kv.Value)));
        sb.Append(" displayWaterLevelHistogram=").Append(string.Join(",", levelHist.Select(kv => kv.Key + "=" + kv.Value)));
        sb.Append(" samples=").Append(string.Join(" ", samples));
    }

    // Writes MapData.waterMap bytes for every display-water tile (24-28) through the game's own
    // water setter Map.ohl(node, waterId), which also marks the touched chunk dirty with
    // RebuildFlags.Mesh so the native water mesh system (bws chunks) rebuilds. waterId=18 is the
    // vanilla "water water" ocean overlay; waterId=0 reverts the paint.
    private static void PaintWater(StringBuilder sb, string requestJson)
    {
        var waterIdText = ReadString(requestJson, "waterId");
        if (string.IsNullOrEmpty(waterIdText) || !int.TryParse(waterIdText, out var waterId) || waterId < 0 || waterId > 255)
            throw new InvalidOperationException("paintWater requires a waterId string field in [0,255].");

        var mapType = FindType("Map");
        var map = mapType == null ? null : FindActiveMap(mapType, sb);
        if (map == null)
            throw new InvalidOperationException("No live Map instance was found via MonoBehaviour Map-field scan.");

        var mapData = GetMapData(map, sb);
        var tilesMap = mapData == null ? null : GetMember(mapData, "tilesMap_") ?? GetMember(mapData, "tilesMap");
        var waterMap = mapData == null ? null : GetMember(mapData, "waterMap_") ?? GetMember(mapData, "waterMap");
        if (tilesMap == null || waterMap == null)
            throw new InvalidOperationException("Live MapData did not expose tilesMap/waterMap members.");

        var length = Math.Min(ArrayLikeLength(tilesMap), ArrayLikeLength(waterMap));
        var testNode = -1;
        for (var i = 0; i < length; i++)
        {
            var tile = Convert.ToInt32(GetArrayItem(tilesMap, i) ?? -1);
            if (tile >= 24 && tile <= 28)
            {
                testNode = i;
                break;
            }
        }
        if (testNode < 0)
            throw new InvalidOperationException("No display-water tile (24-28) exists on the live map to paint.");

        var setter = IdentifyWaterSetter(map, mapData, waterMap, testNode, sb);
        var painted = 0;
        for (var i = 0; i < length; i++)
        {
            var tile = Convert.ToInt32(GetArrayItem(tilesMap, i) ?? -1);
            if (tile < 24 || tile > 28)
                continue;
            setter.Invoke(map, new object[] { i, (byte)waterId });
            painted++;
        }

        var verifyHist = new Dictionary<int, int>();
        for (var i = 0; i < length; i++)
        {
            var tile = Convert.ToInt32(GetArrayItem(tilesMap, i) ?? -1);
            if (tile < 24 || tile > 28)
                continue;
            var value = Convert.ToInt32(GetArrayItem(waterMap, i) ?? -1);
            verifyHist[value] = verifyHist.GetValueOrDefault(value) + 1;
        }

        sb.Append("setter=").Append(setter.Name)
          .Append(" waterId=").Append(waterId)
          .Append(" paintedCells=").Append(painted)
          .Append(" readbackWaterHistogram=").Append(string.Join(",", verifyHist.OrderBy(kv => kv.Key).Select(kv => kv.Key + "=" + kv.Value)));
    }

    // Empirically identifies the waterMap setter (decomp Map.ohl) among the interop's
    // void(int, byte) candidates by writing a sentinel to one display-water test cell and
    // reading waterMap back. Candidates that mutate other byte arrays are restored via the
    // same candidate with the original value before moving on.
    private static MethodInfo IdentifyWaterSetter(object map, object mapData, object waterMap, int testNode, StringBuilder sb)
    {
        var byteArrayMemberNames = new[] { "tilesMap", "levelsMap", "waterMap", "roadsMap", "decorationsMap", "cliffsMap" };
        var byteArrays = new List<(string Name, object Array)>();
        foreach (var name in byteArrayMemberNames)
        {
            var value = GetMember(mapData, name + "_") ?? GetMember(mapData, name);
            if (value != null && ArrayLikeLength(value) > testNode)
                byteArrays.Add((name, value));
        }

        var candidates = map.GetType().GetMethods(All)
            .Where(method => method.ReturnType == typeof(void))
            .Where(method =>
            {
                var parameters = method.GetParameters();
                return parameters.Length == 2
                       && parameters[0].ParameterType == typeof(int)
                       && parameters[1].ParameterType == typeof(byte);
            })
            .ToList();
        if (candidates.Count == 0)
            throw new InvalidOperationException("No void(int, byte) methods exist on the live Map type.");

        const byte sentinel = 18;
        foreach (var candidate in candidates)
        {
            var before = byteArrays.Select(entry => Convert.ToInt32(GetArrayItem(entry.Array, testNode) ?? -1)).ToArray();
            var waterBefore = Convert.ToInt32(GetArrayItem(waterMap, testNode) ?? -1);
            try
            {
                candidate.Invoke(map, new object[] { testNode, sentinel });
            }
            catch
            {
                continue;
            }
            var waterAfter = Convert.ToInt32(GetArrayItem(waterMap, testNode) ?? -1);
            if (waterAfter == sentinel && waterBefore != sentinel)
            {
                sb.Append("identifiedSetter=").Append(candidate.Name).Append(' ');
                candidate.Invoke(map, new object[] { testNode, (byte)waterBefore });
                return candidate;
            }
            for (var i = 0; i < byteArrays.Count; i++)
            {
                var after = Convert.ToInt32(GetArrayItem(byteArrays[i].Array, testNode) ?? -1);
                if (after != before[i])
                {
                    candidate.Invoke(map, new object[] { testNode, (byte)before[i] });
                    sb.Append("rejectedSetter=").Append(candidate.Name).Append("(wrote ").Append(byteArrays[i].Name).Append(") ");
                }
            }
        }
        throw new InvalidOperationException(
            "No void(int, byte) Map method wrote waterMap at test node "
            + testNode
            + "; candidates were ["
            + string.Join(", ", candidates.Select(candidate => candidate.Name))
            + "].");
    }

    private static void PatchLookup(StringBuilder sb)
    {
        var renderers = FindTerrainRenderers();
        if (renderers.Count == 0)
            throw new InvalidOperationException("No terrain renderer instances were found.");

        var patched = 0;
        for (var i = 0; i < renderers.Count; i++)
        {
            var renderer = renderers[i];
            var lookup = FindMaterialLookup(renderer);
            if (lookup == null)
            {
                sb.Append("renderer[").Append(i).Append("] lookup=missing;");
                continue;
            }

            if (!lookup.TryGetValue(DisplayWaterDonorTileCode, out var donorSlot))
            {
                sb.Append("renderer[").Append(i).Append("] donor18=missing;");
                continue;
            }

            foreach (var tileCode in DisplayWaterTileCodes)
            {
                if (lookup.TryGetValue(tileCode, out var existing) && existing == donorSlot)
                    continue;
                WriteLookupEntry(renderer, lookup, tileCode, donorSlot);
                patched++;
            }

            sb.Append("renderer[").Append(i).Append("] donor18->").Append(donorSlot).Append(" patchedAliasCount=").Append(DisplayWaterTileCodes.Length).Append(";");
            AppendLookup(sb, lookup, "renderer[" + i + "].lookup");
        }

        sb.Append("\npatchedEntries=").Append(patched);
        TryInvokeRendererUpload(renderers[0], sb);
    }

    private static void TryInvokeRendererUpload(object renderer, StringBuilder sb)
    {
        if (renderer == null)
            return;
        var type = renderer.GetType();
        MethodInfo upload = null;
        foreach (var method in type.GetMethods(All))
        {
            if (!string.Equals(method.Name, "Method_Private_Void_Map_0", StringComparison.Ordinal))
                continue;
            var parameters = method.GetParameters();
            if (parameters.Length == 1)
            {
                upload = method;
                break;
            }
        }
        if (upload == null)
        {
            sb.Append("\nupload=missing");
            return;
        }

        var map = FindActiveMap(upload.GetParameters()[0].ParameterType);
        if (map == null)
        {
            sb.Append("\nupload=skipped-no-map");
            return;
        }

        upload.Invoke(renderer, new[] { map });
        sb.Append("\nupload=").Append(upload.Name).Append(" invoked");
    }

    private static object FindActiveMap(Type mapType)
    {
        return FindActiveMap(mapType, null);
    }

    private static void FindMapDiagnostics(StringBuilder sb)
    {
        var mapTypes = new List<Type>();
        foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
        {
            Type[] types;
            try { types = assembly.GetTypes(); }
            catch { continue; }
            foreach (var candidate in types)
            {
                if (string.Equals(candidate.Name, "Map", StringComparison.Ordinal))
                    mapTypes.Add(candidate);
            }
        }
        sb.Append("mapTypes=").Append(string.Join(";", mapTypes.Select(type => (type.FullName ?? type.Name) + "@" + type.Assembly.GetName().Name)));

        var behaviours = Resources.FindObjectsOfTypeAll<MonoBehaviour>();
        sb.Append(" behaviourCount=").Append(behaviours.Length);
        var holderTypes = new HashSet<string>();
        foreach (var mapType in mapTypes)
        {
            foreach (var behaviour in behaviours)
            {
                if (!behaviour)
                    continue;
                var type = behaviour.GetType();
                foreach (var field in type.GetFields(All))
                {
                    if (mapType.IsAssignableFrom(field.FieldType))
                        holderTypes.Add(type.FullName + "." + field.Name + ":field");
                }
                foreach (var property in type.GetProperties(All))
                {
                    if (property.GetIndexParameters().Length == 0 && mapType.IsAssignableFrom(property.PropertyType))
                        holderTypes.Add(type.FullName + "." + property.Name + ":prop");
                }
            }
        }
        sb.Append(" holders=").Append(string.Join(";", holderTypes.Take(40)));

        var terrainNamed = behaviours
            .Where(behaviour => behaviour && (behaviour.GetType().FullName ?? "").IndexOf("Terrain", StringComparison.OrdinalIgnoreCase) >= 0)
            .Select(behaviour => behaviour.GetType().FullName)
            .Distinct()
            .Take(20)
            .ToList();
        sb.Append(" terrainBehaviourTypes=").Append(string.Join(";", terrainNamed));
    }

    // Audited path (GameSymbols.HomecomingLayerViewToggle, live-probe validated 2026-07-04):
    // Hex.BhWorldCamera singleton via Method_Public_Static_get_BhWorldCamera_PDM_0, then the
    // current Map via instance Method_Public_Map_0.
    private static object FindActiveMap(Type mapType, StringBuilder sb)
    {
        var cameraType = FindType("BhWorldCamera");
        if (cameraType == null)
        {
            sb?.Append("worldCameraType=missing ");
            return null;
        }
        var singletonGetter = cameraType.GetMethod("Method_Public_Static_get_BhWorldCamera_PDM_0", All, null, Type.EmptyTypes, null);
        if (singletonGetter == null)
        {
            sb?.Append("worldCameraSingletonGetter=missing ");
            return null;
        }
        var camera = singletonGetter.Invoke(null, null);
        if (camera == null)
        {
            sb?.Append("worldCamera=null ");
            return null;
        }
        var currentMapGetter = cameraType.GetMethod("Method_Public_Map_0", All, null, Type.EmptyTypes, null);
        if (currentMapGetter == null)
        {
            sb?.Append("worldCameraCurrentMapGetter=missing ");
            return null;
        }
        var map = currentMapGetter.Invoke(camera, null);
        if (map == null)
        {
            sb?.Append("worldCameraCurrentMap=null ");
            return null;
        }
        if (mapType != null && !mapType.IsInstanceOfType(map))
            sb?.Append("mapTypeMismatch=").Append(map.GetType().FullName ?? "?").Append(' ');
        sb?.Append("mapHolder=BhWorldCamera.Method_Public_Map_0 ");
        return map;
    }

    // Audited getter (GameSymbols.HomecomingLayerViewToggle.MapData): Map.Method_Public_get_MapData_0.
    private static object GetMapData(object map, StringBuilder sb)
    {
        if (map == null)
            return null;
        var direct = GetMember(map, "mapData_") ?? GetMember(map, "mapData");
        if (direct != null)
            return direct;
        var getter = map.GetType().GetMethod("Method_Public_get_MapData_0", All, null, Type.EmptyTypes, null);
        if (getter == null)
        {
            sb?.Append("mapDataGetter=missing ");
            return null;
        }
        return getter.Invoke(map, null);
    }

    private static object GetSoTerrainMaterialInstance()
    {
        var type = FindType("SoTerrainMaterial");
        if (type == null)
            return null;
        var property = type.GetProperty("instance", All);
        return property?.GetValue(null, null);
    }

    private static List<object> FindSoTerrainMaterials()
    {
        var type = FindType("SoTerrainMaterial");
        if (type == null)
            return new List<object>();
        var method = typeof(Resources).GetMethod("FindObjectsOfTypeAll", All, null, new[] { typeof(Type) }, null);
        if (method == null)
            return new List<object>();
        var array = method.Invoke(null, new object[] { type }) as Array;
        if (array == null)
            return new List<object>();
        var results = new List<object>();
        foreach (var item in array)
        {
            if (item != null)
                results.Add(item);
        }
        return results;
    }

    private static Type FindType(string simpleName)
    {
        foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
        {
            Type type = null;
            try { type = assembly.GetType(simpleName, false); }
            catch { }
            if (type != null)
                return type;
            try
            {
                type = assembly.GetTypes().FirstOrDefault(candidate => string.Equals(candidate.Name, simpleName, StringComparison.Ordinal));
            }
            catch { }
            if (type != null)
                return type;
        }
        return null;
    }

    private static List<object> FindTerrainRenderers()
    {
        var results = new List<object>();
        foreach (var behaviour in Resources.FindObjectsOfTypeAll<MonoBehaviour>())
        {
            if (!behaviour)
                continue;
            if (GetMember(behaviour, "field_Private_Il2CppReferenceArray_1_Il2CppStructArray_1_Color_0") == null)
                continue;
            if (FindMaterialLookup(behaviour) == null)
                continue;
            results.Add(behaviour);
        }
        return results;
    }

    private static Dictionary<int, int> FindMaterialLookup(object renderer)
    {
        if (renderer == null)
            return null;
        var type = renderer.GetType();
        foreach (var name in MaterialLookupFieldNames)
        {
            var field = type.GetField(name, All);
            if (field == null)
                continue;
            var dict = AsMutableIntIntDictionary(field.GetValue(renderer));
            if (dict != null)
                return dict;
        }
        return null;
    }

    private static Dictionary<int, int> AsMutableIntIntDictionary(object value)
    {
        if (value == null)
            return null;
        if (value is IDictionary<int, int> direct)
            return direct as Dictionary<int, int> ?? new Dictionary<int, int>(direct);
        if (value is not IEnumerable enumerable)
            return null;

        var dict = new Dictionary<int, int>();
        foreach (var entry in enumerable)
        {
            var entryType = entry.GetType();
            var keyObj = entryType.GetProperty("Key")?.GetValue(entry, null);
            var valObj = entryType.GetProperty("Value")?.GetValue(entry, null);
            if (keyObj == null || valObj == null)
                continue;
            if (!TryConvertInt(keyObj, out var key) || !TryConvertInt(valObj, out var val))
                continue;
            dict[key] = val;
        }
        if (dict.Count == 0)
            return null;
        return dict;
    }

    private static bool TryConvertInt(object value, out int result)
    {
        result = 0;
        if (value is int i)
        {
            result = i;
            return true;
        }
        try
        {
            result = Convert.ToInt32(value, System.Globalization.CultureInfo.InvariantCulture);
            return true;
        }
        catch
        {
            return false;
        }
    }

    private static void WriteLookupEntry(object renderer, Dictionary<int, int> lookup, int tileCode, int slot)
    {
        lookup[tileCode] = slot;
        var type = renderer.GetType();
        foreach (var name in MaterialLookupFieldNames)
        {
            var field = type.GetField(name, All);
            if (field == null)
                continue;
            var raw = field.GetValue(renderer);
            if (raw == null)
                continue;
            var setItem = raw.GetType().GetMethod("set_Item", All);
            setItem?.Invoke(raw, new object[] { tileCode, slot });
            return;
        }
    }

    private static void AppendRenderer(StringBuilder sb, object renderer, int index)
    {
        var type = renderer.GetType();
        sb.Append("\nrenderer[").Append(index).Append("] type=").Append(type.FullName ?? type.Name);
        var lookup = FindMaterialLookup(renderer);
        if (lookup == null)
        {
            sb.Append(" lookup=missing");
            return;
        }
        AppendLookup(sb, lookup, "lookup");
        AppendColorLayerSample(sb, renderer, lookup);
    }

    private static void AppendColorLayerSample(StringBuilder sb, object renderer, Dictionary<int, int> lookup)
    {
        var layers = GetMember(renderer, "field_Private_Il2CppReferenceArray_1_Il2CppStructArray_1_Color_0") as Il2CppReferenceArray<Il2CppStructArray<Color>>;
        if (layers == null)
            return;
        sb.Append("\n colorLayers=").Append(layers.Length);
        foreach (var tileCode in new[] { DisplayWaterDonorTileCode, 24, 25 })
        {
            if (!lookup.TryGetValue(tileCode, out var slot) || slot < 0 || slot >= layers.Length || layers[slot] == null)
            {
                sb.Append(" tile").Append(tileCode).Append("=n/a");
                continue;
            }
            var layer = layers[slot];
            sb.Append(" tile").Append(tileCode).Append("->slot").Append(slot)
              .Append(" sample=").Append(ColorSummary(layer[0])).Append("/").Append(ColorSummary(layer[layer.Length / 2]));
        }
    }

    private static void AppendBiomes(StringBuilder sb, object terrain, string label)
    {
        if (terrain == null)
        {
            sb.Append("\n").Append(label).Append(" terrain=null");
            return;
        }
        var biomes = GetMember(terrain, "biomes");
        var length = ArrayLikeLength(biomes);
        sb.Append("\n").Append(label).Append(" count=").Append(length);
        if (length <= 0)
            return;
        for (var i = 0; i < length; i++)
        {
            var biome = GetArrayItem(biomes, i);
            if (biome == null)
                continue;
            var tileCode = Convert.ToInt32(GetMember(biome, "tileCode") ?? -1);
            var name = Convert.ToString(GetMember(biome, "name") ?? "?");
            if (tileCode == DisplayWaterDonorTileCode
                || Array.IndexOf(DisplayWaterTileCodes, tileCode) >= 0
                || tileCode <= 28)
            {
                sb.Append("\n  [").Append(i).Append("] tile=").Append(tileCode).Append(" name=").Append(name);
            }
        }
    }

    private static void AppendLookup(StringBuilder sb, Dictionary<int, int> lookup, string label)
    {
        sb.Append("\n").Append(label).Append(" count=").Append(lookup.Count);
        foreach (var kv in lookup.OrderBy(k => k.Key))
        {
            if (kv.Key == DisplayWaterDonorTileCode || Array.IndexOf(DisplayWaterTileCodes, kv.Key) >= 0 || kv.Key <= 22)
                sb.Append(" ").Append(kv.Key).Append("->").Append(kv.Value);
        }
    }

    private static int ArrayLikeLength(object arrayLike)
    {
        if (arrayLike == null)
            return 0;
        if (arrayLike is Array array)
            return array.Length;
        var lengthProperty = arrayLike.GetType().GetProperty("Length", All) ?? arrayLike.GetType().GetProperty("Count", All);
        if (lengthProperty == null)
            return 0;
        return Convert.ToInt32(lengthProperty.GetValue(arrayLike, null));
    }

    private static object GetArrayItem(object arrayLike, int index)
    {
        if (arrayLike is Array array)
            return array.GetValue(index);
        var indexer = arrayLike.GetType().GetProperty("Item", All);
        return indexer?.GetValue(arrayLike, new object[] { index });
    }

    private static object GetMember(object obj, string name)
    {
        if (obj == null)
            return null;
        var type = obj.GetType();
        var prop = type.GetProperty(name, All);
        if (prop != null && prop.GetIndexParameters().Length == 0)
            return prop.GetValue(obj, null);
        var field = type.GetField(name, All);
        return field?.GetValue(obj);
    }

    private static string DescribeObject(object obj)
    {
        if (obj == null)
            return "null";
        var name = GetMember(obj, "name") as string;
        return string.IsNullOrEmpty(name) ? obj.GetType().Name : name;
    }

    private static string ColorSummary(Color color)
    {
        return ((int)Math.Round(color.r * 255f)) + "," + ((int)Math.Round(color.g * 255f)) + "," + ((int)Math.Round(color.b * 255f)) + "," + ((int)Math.Round(color.a * 255f));
    }

    private static string ReadString(string json, string key)
    {
        if (string.IsNullOrEmpty(json) || string.IsNullOrEmpty(key))
            return null;
        var match = Regex.Match(json, "\\\"" + Regex.Escape(key) + "\\\"\\s*:\\s*\\\"(?<v>(?:\\\\.|[^\\\"])*)\\\"");
        if (!match.Success)
            return null;
        return match.Groups["v"].Value.Replace("\\\"", "\"").Replace("\\\\", "\\");
    }

    private static string Json(params object[] pairs)
    {
        var sb = new StringBuilder("{");
        for (var i = 0; i + 1 < pairs.Length; i += 2)
        {
            if (i > 0)
                sb.Append(',');
            sb.Append('"').Append(Escape(Convert.ToString(pairs[i]))).Append("\":");
            var value = pairs[i + 1];
            if (value is bool b)
                sb.Append(b ? "true" : "false");
            else
                sb.Append('"').Append(Escape(Convert.ToString(value) ?? "")).Append('"');
        }
        sb.Append('}');
        return sb.ToString();
    }

    private static string Escape(string value)
    {
        if (value == null)
            return "";
        return value.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", "\\r").Replace("\n", "\\n");
    }
}
