using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using UnityEditor;
using UnityEngine;

// Regression-only override remap for older owned skinned units (tools/homm3_import/remap_owned_attack_slots.py).
// It rewrites only the stock slots 14.Attack / 15.Skill_1 of each unit's existing override controller to the clip
// the candidate Core view requires (planned in Python from the view, never from which clips exist). It never runs
// LabBuild, imports a master GLB, or edits a prefab, clip, mesh or texture: every other file under the unit's
// OwnedSkinned root is hash-pinned before and after. All units are validated before the first edit.
// ProbeFromCommandLine reads the rebuilt bundles back: the AOC loads a non-null stock base and every override pair
// equals the remap report. Generated-asset proof only.
public static class Homm3OwnedSkinnedAttackSlotRemap
{
    // Unity queue shim (tools/unity_queue, docs/unity_queue_runner.md): under UnityQueueDispatcher a job reads its
    // own arguments and records its exit code instead of quitting the shared batch; a direct launch reads the command
    // line and exits as before. The dispatcher refuses a class without this pair.
    static string[] UnityQueueArgs() => AppDomain.CurrentDomain.GetData("UnityQueue.JobArgs") as string[] ?? Environment.GetCommandLineArgs();
    static void UnityQueueExit(int code)
    {
        if (AppDomain.CurrentDomain.GetData("UnityQueue.JobArgs") == null) { EditorApplication.Exit(code); return; }
        if (!(AppDomain.CurrentDomain.GetData("UnityQueue.ExitCode") is int prev && prev != 0)) AppDomain.CurrentDomain.SetData("UnityQueue.ExitCode", code);
    }

    [Serializable] private class AssetHash { public string path; public string sha256; }
    [Serializable] private class SlotDecision { public string slot; public string clip; }
    [Serializable] private class UnitPlan
    {
        public string labSid;
        public string sourcePrefabAsset;
        public string sourceControllerAsset;
        public AssetHash[] inputAssets;
        public SlotDecision[] desired;
    }
    [Serializable] private class BatchPlan
    {
        public string schema;
        public string cohort;
        public string coreSha256;
        public string projectPath;
        public UnitPlan[] units;
    }
    [Serializable] private class Pair { public string slot; public string clip; }
    [Serializable] private class UnitReport
    {
        public string labSid;
        public string controller;
        public string basePath;
        public string controllerSha256Before;
        public string controllerSha256After;
        public bool changed;
        public int unchangedSourceFiles;
        public int unchangedOtherOverrides;
        public Pair[] before;
        public Pair[] after;
    }
    [Serializable] private class BatchReport
    {
        public string schema = "homm3_owned_attack_slot_remap_report.v1";
        public string proof = "Unity Editor in-place override remap; no bundle, install, or runtime proof";
        public string cohort;
        public string coreSha256;
        public UnitReport[] units;
    }
    [Serializable] private class ProbeUnit { public string labSid; public string bundlePath; public string prefabAssetPath; public Pair[] expected; }
    [Serializable] private class ProbeSpec { public string schema; public ProbeUnit[] units; }
    [Serializable] private class ProbeResult
    {
        public string labSid;
        public bool ok;
        public string basePath;
        public int pairs;
        public int skinnedRenderers;
        public string attack;
        public string skill1;
        public string error;
    }
    [Serializable] private class ProbeReport
    {
        public string schema = "homm3_owned_attack_slot_remap_probe.v1";
        public string proof = "generated-asset-only (editor-loaded bundle)";
        public ProbeResult[] units;
    }

    private const string BaseName = "_Battle_Unit_Anim_ctrl_v2";
    private static readonly string[] MutableSlots = { "14.Attack", "15.Skill_1" };
    private static readonly string[] AllowedClips = { "Unit_AttackFront", "Unit_ShootFront" };

    public static void RunFromCommandLine()
    {
        string planPath = Arg("-attackSlotRemapPlan");
        string planSha = Arg("-attackSlotRemapPlanSha256");
        string reportPath = Arg("-attackSlotRemapReport");
        if (string.IsNullOrEmpty(planPath) || !File.Exists(planPath) || string.IsNullOrEmpty(planSha)
            || FileHash(planPath) != planSha || string.IsNullOrEmpty(reportPath) || File.Exists(reportPath))
            throw new InvalidOperationException("attack-slot remap needs a verified plan, its SHA-256, and a new report path");
        var plan = JsonUtility.FromJson<BatchPlan>(File.ReadAllText(planPath));
        if (plan == null || plan.schema != "homm3_owned_attack_slot_remap_batch.v1" || plan.units == null || plan.units.Length == 0)
            throw new InvalidOperationException("invalid attack-slot remap plan");
        string project = Path.GetFullPath(Directory.GetParent(Application.dataPath).FullName);
        if (!string.Equals(Path.GetFullPath(plan.projectPath).TrimEnd('\\', '/'), project.TrimEnd('\\', '/'), StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("attack-slot plan targets a different Unity project: " + plan.projectPath);

        // Pass 1: validate every unit before editing any.
        var work = new List<(UnitPlan plan, AnimatorOverrideController aoc, List<KeyValuePair<AnimationClip, AnimationClip>> before, Dictionary<string, AnimationClip> desired)>();
        foreach (var unit in plan.units)
            work.Add(Validate(unit));

        // Pass 2: edit only the two stock slots of each source AOC.
        var reports = new List<UnitReport>();
        foreach (var w in work)
        {
            string aocPath = w.plan.sourceControllerAsset;
            string shaBefore = FileHash(AbsoluteAsset(aocPath));
            var changed = new List<KeyValuePair<AnimationClip, AnimationClip>>(w.before);
            bool any = false;
            for (int i = 0; i < changed.Count; i++)
            {
                if (w.desired.TryGetValue(changed[i].Key.name, out AnimationClip clip) && changed[i].Value != clip)
                {
                    changed[i] = new KeyValuePair<AnimationClip, AnimationClip>(changed[i].Key, clip);
                    any = true;
                }
            }
            if (any)
            {
                w.aoc.ApplyOverrides(changed);
                EditorUtility.SetDirty(w.aoc);
                AssetDatabase.SaveAssetIfDirty(w.aoc);
                AssetDatabase.ImportAsset(aocPath, ImportAssetOptions.ForceSynchronousImport);
            }
            var reloaded = AssetDatabase.LoadAssetAtPath<AnimatorOverrideController>(aocPath);
            if (reloaded == null || reloaded.runtimeAnimatorController == null || reloaded.runtimeAnimatorController.name != BaseName)
                throw new InvalidOperationException(w.plan.labSid + ": override base lost on readback");
            var after = Pairs(reloaded, w.plan.labSid);
            int unchangedOther = VerifyRemap(w.before, after, w.desired, w.plan.labSid);
            int unchangedFiles = CheckSourceHashes(w.plan.inputAssets, aocPath);
            reports.Add(new UnitReport
            {
                labSid = w.plan.labSid,
                controller = aocPath,
                basePath = AssetDatabase.GetAssetPath(reloaded.runtimeAnimatorController),
                controllerSha256Before = shaBefore,
                controllerSha256After = FileHash(AbsoluteAsset(aocPath)),
                changed = any,
                unchangedSourceFiles = unchangedFiles,
                unchangedOtherOverrides = unchangedOther,
                before = ToPairs(w.before),
                after = ToPairs(after),
            });
        }
        var report = new BatchReport { cohort = plan.cohort, coreSha256 = plan.coreSha256, units = reports.ToArray() };
        File.WriteAllText(reportPath, JsonUtility.ToJson(report, true) + "\n");
        Debug.Log("HOMM3_ATTACK_SLOT_REMAP_OK cohort=" + plan.cohort + " units=" + reports.Count
            + " changed=" + reports.Count(r => r.changed));
    }

    private static (UnitPlan, AnimatorOverrideController, List<KeyValuePair<AnimationClip, AnimationClip>>, Dictionary<string, AnimationClip>) Validate(UnitPlan unit)
    {
        if (unit == null || string.IsNullOrEmpty(unit.labSid) || unit.labSid.Any(ch => !char.IsLetterOrDigit(ch) && ch != '_')
            || unit.inputAssets == null || unit.inputAssets.Length == 0 || unit.desired == null || unit.desired.Length == 0)
            throw new InvalidOperationException("invalid unit in attack-slot plan");
        string root = "Assets/CustomUnits/homm3_lab/" + unit.labSid + "/OwnedSkinned";
        if (unit.sourcePrefabAsset != root + "/owned_skinned.prefab" || unit.sourceControllerAsset != root + "/owned_skinned.overrideController")
            throw new InvalidOperationException(unit.labSid + ": plan does not name its canonical source assets");
        var pinned = new HashSet<string>(unit.inputAssets.Select(a => a.path), StringComparer.Ordinal);
        if (!pinned.Contains(unit.sourcePrefabAsset) || !pinned.Contains(unit.sourceControllerAsset))
            throw new InvalidOperationException(unit.labSid + ": source prefab/controller are not hash-pinned");
        CheckSourceHashes(unit.inputAssets, null);

        var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(unit.sourcePrefabAsset);
        var aoc = AssetDatabase.LoadAssetAtPath<AnimatorOverrideController>(unit.sourceControllerAsset);
        if (prefab == null || aoc == null)
            throw new InvalidOperationException(unit.labSid + ": source prefab/controller missing");
        var animators = prefab.GetComponentsInChildren<Animator>(true);
        if (animators.Length != 1 || animators[0].runtimeAnimatorController != aoc)
            throw new InvalidOperationException(unit.labSid + ": prefab does not own exactly this controller");
        var stock = aoc.runtimeAnimatorController;
        if (stock == null || stock.name != BaseName)
            throw new InvalidOperationException(unit.labSid + ": override has a null or wrong stock base ("
                + (stock == null ? "<null>" : stock.name) + "); run the stock controller identity audit");
        var before = Pairs(aoc, unit.labSid);
        var slots = new HashSet<string>(before.Select(p => p.Key.name), StringComparer.Ordinal);
        if (slots.Count != before.Count)
            throw new InvalidOperationException(unit.labSid + ": duplicate stock slots");
        var desired = new Dictionary<string, AnimationClip>(StringComparer.Ordinal);
        foreach (var d in unit.desired)
        {
            if (d == null || !MutableSlots.Contains(d.slot) || !AllowedClips.Contains(d.clip) || desired.ContainsKey(d.slot) || !slots.Contains(d.slot))
                throw new InvalidOperationException(unit.labSid + ": invalid or duplicate desired slot " + d?.slot);
            string clipPath = root + "/Animations/" + d.clip + ".anim";
            if (!pinned.Contains(clipPath))
                throw new InvalidOperationException(unit.labSid + ": desired clip is not hash-pinned: " + clipPath);
            var clip = AssetDatabase.LoadAssetAtPath<AnimationClip>(clipPath);
            if (clip == null || clip.name != d.clip)
                throw new InvalidOperationException(unit.labSid + ": required clip missing: " + clipPath);
            desired.Add(d.slot, clip);
        }
        return (unit, aoc, before, desired);
    }

    public static void ProbeFromCommandLine()
    {
        string specPath = Arg("-attackSlotProbeSpec");
        string outPath = Arg("-attackSlotProbeOut");
        if (string.IsNullOrEmpty(specPath) || string.IsNullOrEmpty(outPath) || !File.Exists(specPath))
            throw new InvalidOperationException("attack-slot probe needs -attackSlotProbeSpec and -attackSlotProbeOut");
        var spec = JsonUtility.FromJson<ProbeSpec>(File.ReadAllText(specPath));
        if (spec == null || spec.schema != "homm3_owned_attack_slot_remap_probe_spec.v1" || spec.units == null || spec.units.Length == 0)
            throw new InvalidOperationException("invalid attack-slot probe spec");
        var results = spec.units.Select(Probe).ToArray();
        File.WriteAllText(outPath, JsonUtility.ToJson(new ProbeReport { units = results }, true) + "\n");
        if (results.Any(r => !r.ok))
            throw new InvalidOperationException("attack-slot bundle probe failed: " + string.Join("; ", results.Where(r => !r.ok).Select(r => r.labSid + ": " + r.error)));
        Debug.Log("HOMM3_ATTACK_SLOT_PROBE_OK units=" + results.Length);
    }

    private static ProbeResult Probe(ProbeUnit unit)
    {
        var result = new ProbeResult { labSid = unit.labSid };
        AssetBundle bundle = null;
        GameObject instance = null;
        try
        {
            bundle = AssetBundle.LoadFromFile(unit.bundlePath);
            if (bundle == null)
                throw new InvalidOperationException("bundle load failed");
            string name = bundle.GetAllAssetNames().FirstOrDefault(n => string.Equals(n, unit.prefabAssetPath, StringComparison.OrdinalIgnoreCase));
            if (name == null)
                throw new InvalidOperationException("owned prefab is not addressable");
            var prefab = bundle.LoadAsset<GameObject>(name);
            instance = UnityEngine.Object.Instantiate(prefab);
            result.skinnedRenderers = instance.GetComponentsInChildren<SkinnedMeshRenderer>(true).Length;
            if (result.skinnedRenderers == 0)
                throw new InvalidOperationException("no skinned renderer");
            var animators = instance.GetComponentsInChildren<Animator>(true);
            if (animators.Length != 1)
                throw new InvalidOperationException("expected one Animator, found " + animators.Length);
            var aoc = animators[0].runtimeAnimatorController as AnimatorOverrideController;
            if (aoc == null || aoc.runtimeAnimatorController == null || aoc.runtimeAnimatorController.name != BaseName)
                throw new InvalidOperationException("bundle AOC has a null or wrong stock base");
            result.basePath = aoc.runtimeAnimatorController.name;
            var pairs = new List<KeyValuePair<AnimationClip, AnimationClip>>();
            aoc.GetOverrides(pairs);
            result.pairs = pairs.Count;
            var got = pairs.ToDictionary(p => p.Key.name, p => p.Value == null ? "<stock>" : p.Value.name, StringComparer.Ordinal);
            result.attack = got.TryGetValue("14.Attack", out var a) ? a : null;
            result.skill1 = got.TryGetValue("15.Skill_1", out var s) ? s : null;
            var expected = (unit.expected ?? new Pair[0]).ToDictionary(p => p.slot, p => p.clip, StringComparer.Ordinal);
            if (expected.Count == 0 || expected.Count != got.Count)
                throw new InvalidOperationException("override pair count " + got.Count + " != expected " + expected.Count);
            foreach (var kv in expected)
                if (!got.TryGetValue(kv.Key, out var clip) || clip != kv.Value)
                    throw new InvalidOperationException("slot " + kv.Key + " plays " + (clip ?? "<missing>") + ", expected " + kv.Value);
            foreach (var p in pairs.Where(p => p.Value != null))
                if (!(p.Value.length > 0f) || float.IsInfinity(p.Value.length))
                    throw new InvalidOperationException("clip " + p.Value.name + " has no length");
            result.ok = true;
        }
        catch (Exception ex)
        {
            result.error = ex.Message;
        }
        finally
        {
            if (instance != null) UnityEngine.Object.DestroyImmediate(instance);
            if (bundle != null) bundle.Unload(true);
        }
        return result;
    }

    private static Pair[] ToPairs(List<KeyValuePair<AnimationClip, AnimationClip>> pairs)
    {
        return pairs.Select(p => new Pair { slot = p.Key.name, clip = p.Value == null ? "<stock>" : p.Value.name })
            .OrderBy(p => p.slot, StringComparer.Ordinal).ToArray();
    }

    private static List<KeyValuePair<AnimationClip, AnimationClip>> Pairs(AnimatorOverrideController controller, string sid)
    {
        var pairs = new List<KeyValuePair<AnimationClip, AnimationClip>>();
        controller.GetOverrides(pairs);
        if (pairs.Count == 0 || pairs.Any(p => p.Key == null))
            throw new InvalidOperationException(sid + ": override controller has no pairs or a null stock key");
        return pairs;
    }

    private static int VerifyRemap(List<KeyValuePair<AnimationClip, AnimationClip>> before,
                                   List<KeyValuePair<AnimationClip, AnimationClip>> after,
                                   Dictionary<string, AnimationClip> desired, string sid)
    {
        if (before.Count != after.Count)
            throw new InvalidOperationException(sid + ": remap changed the number of stock overrides");
        int unchangedOther = 0;
        foreach (var pair in before)
        {
            var matches = after.Where(o => o.Key == pair.Key).ToArray();
            if (matches.Length != 1)
                throw new InvalidOperationException(sid + ": remap lost or duplicated stock slot " + pair.Key.name);
            if (desired.TryGetValue(pair.Key.name, out AnimationClip clip))
            {
                if (matches[0].Value != clip)
                    throw new InvalidOperationException(sid + ": remap failed to assign " + pair.Key.name);
            }
            else
            {
                if (matches[0].Value != pair.Value)
                    throw new InvalidOperationException(sid + ": remap changed unrelated stock slot " + pair.Key.name);
                unchangedOther++;
            }
        }
        return unchangedOther;
    }

    // Returns the number of pinned files verified unchanged; the one allowed-to-change path is skipped.
    private static int CheckSourceHashes(AssetHash[] inputs, string mayChange)
    {
        var seen = new HashSet<string>(StringComparer.Ordinal);
        int unchanged = 0;
        foreach (var input in inputs)
        {
            if (input == null || !seen.Add(input.path))
                throw new InvalidOperationException("duplicate pinned asset " + input?.path);
            if (input.path == mayChange)
                continue;
            if (FileHash(AbsoluteAsset(input.path)) != input.sha256)
                throw new InvalidOperationException("attack-slot remap source asset changed: " + input.path);
            unchanged++;
        }
        return unchanged;
    }

    private static string AbsoluteAsset(string path)
    {
        if (string.IsNullOrEmpty(path) || !path.StartsWith("Assets/", StringComparison.Ordinal) || path.Split('/').Contains(".."))
            throw new InvalidOperationException("invalid Unity asset path: " + path);
        string project = Directory.GetParent(Application.dataPath).FullName;
        return Path.GetFullPath(Path.Combine(project, path.Replace('/', Path.DirectorySeparatorChar)));
    }

    private static string FileHash(string path)
    {
        using (var stream = File.OpenRead(path))
        using (var hash = SHA256.Create())
            return BitConverter.ToString(hash.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
    }

    private static string Arg(string name)
    {
        var args = UnityQueueArgs();
        for (int i = 0; i < args.Length - 1; i++)
            if (args[i] == name)
                return args[i + 1];
        return null;
    }
}
