using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEngine;

// Read-only Unity-side proof for tools/validate_homm3_stock_controller_identity.py: the two stock donor controllers
// own the GUIDs their .meta files declare, no other project asset carries either GUID, and every manifest owned
// skinned override controller loads a non-null _Battle_Unit_Anim_ctrl_v2 base with its serialized override pairs.
// Writes one JSON report; throws (non-zero Unity exit) on any failure. Edits no asset.
public static class Homm3StockControllerIdentityAudit
{
    private const string Esquire = "Assets/CustomUnits/esquire/Reference/StockEsquireBattle.controller";
    private const string Crusader = "Assets/CustomUnits/homm3_lab/h3_crusader/Reference/StockEsquireBattle.controller";
    private const string BaseName = "_Battle_Unit_Anim_ctrl_v2";

    [Serializable] private class ManifestRow { public string unitSid; public string battlePrefabAsset; }
    [Serializable] private class Manifest { public ManifestRow[] units; }
    [Serializable] private class Donor { public string path; public string metaGuid; public string unityGuid; public string[] assetsWithGuid; }
    [Serializable] private class UnitResult
    {
        public string unitSid;
        public string controller;
        public string basePath;
        public int pairs;
        public int serializedOverrides;
        public int nonNullOverrides;
        public string error;
    }
    [Serializable] private class Report
    {
        public string schema = "homm3_stock_controller_identity_audit.v1";
        public string proof = "Unity Editor AssetDatabase readback; no asset edited";
        public Donor[] donors;
        public int checkedUnits;
        public int esquireCohort;
        public int crusaderCohort;
        public int failures;
        public UnitResult[] units;
    }

    private static readonly Regex GuidLine = new Regex(@"^guid:\s*([0-9a-f]{32})\s*$", RegexOptions.Multiline);
    private static readonly Regex OverrideWithGuid = new Regex(@"m_OverrideClip: \{fileID: -?\d+, guid: [0-9a-f]{32}");

    public static void RunFromCommandLine()
    {
        string manifestPath = Arg("-identityManifest");
        string reportPath = Arg("-identityReport");
        if (string.IsNullOrEmpty(manifestPath) || string.IsNullOrEmpty(reportPath) || !File.Exists(manifestPath))
            throw new InvalidOperationException("identity audit needs -identityManifest <file> and -identityReport <file>");

        if (Arg("-identityReimportDonors") == "true")
        {
            // After a .meta GUID repair: make the AssetDatabase re-read both donor .meta files.
            foreach (var donor in new[] { Esquire, Crusader })
                AssetDatabase.ImportAsset(donor, ImportAssetOptions.ForceUpdate | ImportAssetOptions.ForceSynchronousImport);
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
        }
        var allPaths = AssetDatabase.GetAllAssetPaths();
        var donors = new[] { Esquire, Crusader }.Select(path =>
        {
            string metaGuid = MetaGuid(path);
            return new Donor
            {
                path = path,
                metaGuid = metaGuid,
                unityGuid = AssetDatabase.AssetPathToGUID(path),
                assetsWithGuid = string.IsNullOrEmpty(metaGuid) ? new string[0]
                    : allPaths.Where(p => AssetDatabase.AssetPathToGUID(p) == metaGuid).ToArray(),
            };
        }).ToArray();
        var errors = new List<string>();
        foreach (var d in donors)
        {
            if (string.IsNullOrEmpty(d.metaGuid) || d.unityGuid != d.metaGuid)
                errors.Add("donor " + d.path + " meta guid " + d.metaGuid + " != Unity guid " + d.unityGuid);
            if (d.assetsWithGuid.Length != 1 || d.assetsWithGuid[0] != d.path)
                errors.Add("donor guid " + d.metaGuid + " is owned by [" + string.Join(", ", d.assetsWithGuid) + "]");
            if (AssetDatabase.GUIDToAssetPath(d.metaGuid) != d.path)
                errors.Add("GUIDToAssetPath(" + d.metaGuid + ") = '" + AssetDatabase.GUIDToAssetPath(d.metaGuid) + "' not " + d.path);
            var c = AssetDatabase.LoadAssetAtPath<RuntimeAnimatorController>(d.path);
            if (c == null || c.name != BaseName)
                errors.Add("donor " + d.path + " does not load as " + BaseName);
        }
        if (donors[0].metaGuid == donors[1].metaGuid)
            errors.Add("both donors declare " + donors[0].metaGuid);

        var manifest = JsonUtility.FromJson<Manifest>(File.ReadAllText(manifestPath));
        var results = new List<UnitResult>();
        int esq = 0, cru = 0;
        foreach (var row in manifest.units ?? new ManifestRow[0])
        {
            if (row == null || string.IsNullOrEmpty(row.battlePrefabAsset) || !row.battlePrefabAsset.EndsWith("owned_skinned.prefab"))
                continue;
            string root = row.battlePrefabAsset.Substring(0, row.battlePrefabAsset.LastIndexOf('/'));
            string aocPath = new[] { root + "/owned_skinned.overrideController", root + "/crusader_owned_skinned.overrideController" }
                .FirstOrDefault(p => File.Exists(Abs(p)));
            if (aocPath == null)
                continue;
            var r = new UnitResult { unitSid = row.unitSid, controller = aocPath };
            r.serializedOverrides = OverrideWithGuid.Matches(File.ReadAllText(Abs(aocPath))).Count;
            var aoc = AssetDatabase.LoadAssetAtPath<AnimatorOverrideController>(aocPath);
            var baseController = aoc == null ? null : aoc.runtimeAnimatorController;
            r.basePath = baseController == null ? null : AssetDatabase.GetAssetPath(baseController);
            if (aoc == null)
                r.error = "override controller does not load";
            else if (baseController == null || baseController.name != BaseName)
                r.error = "null or wrong base: " + (baseController == null ? "<null>" : baseController.name);
            else if (r.basePath != Esquire && r.basePath != Crusader)
                r.error = "base resolves outside the stock donors: " + r.basePath;
            else
            {
                var pairs = new List<KeyValuePair<AnimationClip, AnimationClip>>();
                aoc.GetOverrides(pairs);
                r.pairs = pairs.Count;
                r.nonNullOverrides = pairs.Count(p => p.Value != null);
                if (pairs.Count == 0 || pairs.Any(p => p.Key == null))
                    r.error = "no override pairs or a null stock key";
                else if (r.nonNullOverrides != r.serializedOverrides)
                    r.error = "loaded " + r.nonNullOverrides + " overrides, serialized " + r.serializedOverrides;
                else if (r.basePath == Esquire) esq++;
                else cru++;
            }
            results.Add(r);
        }
        var report = new Report
        {
            donors = donors,
            checkedUnits = results.Count,
            esquireCohort = esq,
            crusaderCohort = cru,
            failures = results.Count(r => r.error != null) + errors.Count,
            units = results.ToArray(),
        };
        File.WriteAllText(reportPath, JsonUtility.ToJson(report, true) + "\n");
        foreach (var e in errors)
            Debug.LogError("HOMM3_STOCK_IDENTITY " + e);
        foreach (var r in results.Where(r => r.error != null).Take(20))
            Debug.LogError("HOMM3_STOCK_IDENTITY " + r.unitSid + ": " + r.error);
        if (report.failures > 0 || results.Count == 0)
            throw new InvalidOperationException("stock controller identity audit failed: " + report.failures + " failure(s); see " + reportPath);
        Debug.Log("HOMM3_STOCK_IDENTITY_OK units=" + results.Count + " esquire=" + esq + " crusader=" + cru);
    }

    private static string MetaGuid(string assetPath)
    {
        string meta = Abs(assetPath) + ".meta";
        if (!File.Exists(meta))
            return null;
        var m = GuidLine.Match(File.ReadAllText(meta));
        return m.Success ? m.Groups[1].Value : null;
    }

    private static string Abs(string assetPath)
    {
        return Path.Combine(Directory.GetParent(Application.dataPath).FullName, assetPath.Replace('/', Path.DirectorySeparatorChar));
    }

    private static string Arg(string name)
    {
        var args = Environment.GetCommandLineArgs();
        for (int i = 0; i < args.Length - 1; i++)
            if (args[i] == name)
                return args[i + 1];
        return null;
    }
}
