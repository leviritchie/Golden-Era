// HOMM3_FACING_PROOF_GENERATED: staged by tools/homm3_import/owned_skinned_facing_proof.py. Editor-only proof rig; NOT a delivery path.
// Renders a native Olden Era unit and owned-skinned lab prefabs through the same transform composition the game
// uses for each presentation lane, and reports each unit's world forward against the camera.
//   map       SquadDrawer.Init: map prefab under an unrotated holder; native mesh = extracted <unit>_map prefab
//             (root yaw and scale_roll yaw included). Ours = shell (donor map root yaw) -> visual -> Orientation.
//   preview   BhUnitPreviews.TryGetModel: model root world yaw 22, camera at -Z looking +Z. Native mesh = extracted
//             battle prefab (scale_roll +90 included). Ours: synthetic lane keeps the prefab's baked Orientation;
//             vanilla-donor lane zeroes it and (fixed rule) takes the vanilla model's scale_roll yaw.
//   battleL/R UnitDrawer.Init root yaw = stayAngle (left 0 / right 180, right side X-mirrored by SideSettings).
//             Ours copies the root rotation (no mirror), zeroes Orientation and sets the side yaw 150 / -30.
// "rules" selects the plugin's composition: "before" (pre-fix: map/vanilla preview leave Orientation at 0),
// "after" (map/vanilla preview take the native scale_roll yaw; synthetic preview keeps the baked yaw) or
// "fleet" (every lane sets Orientation = native presentation yaw - bindFacingYaw (-60): map scale_roll+60,
// vanilla preview 90+60, synthetic preview 90+60; battle 150 / -30 unchanged in all three).
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using UnityEditor;
using UnityEngine;

namespace OldenEra.Homm3FacingProof
{
    public static class Homm3FacingProofRig
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

        [Serializable] private sealed class NativeSub { public string texture; public int[] tri; }
        [Serializable]
        private sealed class NativeMesh
        {
            public string name;
            public float[] pos;
            public float[] uv;
            public float[] forward; // idle-0 forward in prefab-root space, from the extracted hip/shoulder bones
            public NativeSub[] subs;
        }
        [Serializable]
        private sealed class Spec
        {
            public string schema, rules, outDir;
            public NativeMesh nativeBattle, nativeMap;
            public string nativeName;
            public float mapShellRootYaw, mapScaleRollYaw, battleScaleRollYaw, previewRootYaw, battleSideYawLeft, battleSideYawRight;
            public float bindFacingYaw; // fleet rule only: Homm3ImportVisuals.OwnedSkinnedBindFacingYaw
            public string[] prefabs;
            public int tile;
        }

        private static Shader _unlit;
        private static readonly StringBuilder Report = new StringBuilder();

        public static void RunFromCommandLine()
        {
            string[] args = UnityQueueArgs();
            string specPath = null;
            for (int i = 0; i < args.Length - 1; i++)
                if (args[i] == "-homm3FacingProofSpec") specPath = args[i + 1];
            if (string.IsNullOrEmpty(specPath) || !File.Exists(specPath))
                throw new InvalidOperationException("-homm3FacingProofSpec <file> is required");
            Spec spec = JsonUtility.FromJson<Spec>(File.ReadAllText(specPath));
            if (spec.schema != "homm3_owned_skinned_facing_proof.v1") throw new InvalidOperationException("schema " + spec.schema);
            if (spec.rules != "before" && spec.rules != "after" && spec.rules != "fleet") throw new InvalidOperationException("rules " + spec.rules);
            _unlit = Shader.Find("Unlit/Texture");
            if (_unlit == null) throw new InvalidOperationException("Unlit/Texture shader missing");
            Directory.CreateDirectory(spec.outDir);
            Report.Clear();
            Report.Append("{\n  \"schema\": \"homm3_owned_skinned_facing_proof_report.v1\",\n  \"rules\": \"" + spec.rules + "\",\n  \"proof\": \"Unity-editor rig render of the lane compositions (generated artifact); not an in-game capture\",\n  \"tiles\": [\n");
            bool first = true;
            foreach (string lane in new[] { "map", "preview_synthetic", "preview_vanilla", "battleL", "battleR" })
            {
                float nativeHeight = RenderNative(spec, lane, ref first);
                foreach (string prefab in spec.prefabs)
                    RenderOwned(spec, lane, prefab, nativeHeight, ref first);
            }
            Report.Append("\n  ]\n}\n");
            File.WriteAllText(Path.Combine(spec.outDir, "facing_report.json"), Report.ToString(), new UTF8Encoding(false));
            Debug.Log("HOMM3_FACING_PROOF_OK");
        }

        // ---------------------------------------------------------------- native
        private static float RenderNative(Spec spec, string lane, ref bool first)
        {
            bool map = lane == "map";
            NativeMesh nm = map ? spec.nativeMap : spec.nativeBattle;
            var holder = new GameObject("native_holder");
            try
            {
                if (lane.StartsWith("preview", StringComparison.Ordinal))
                    holder.transform.rotation = Quaternion.Euler(0f, spec.previewRootYaw, 0f);
                else if (lane == "battleR")
                {
                    holder.transform.rotation = Quaternion.Euler(0f, 180f, 0f);
                    holder.transform.localScale = new Vector3(-1f, 1f, 1f);
                }
                var go = BuildNative(nm);
                go.transform.SetParent(holder.transform, false);
                // native forward: the extracted idle-0 limb forward, composed through the holder (mirror included)
                Vector3 fwd = holder.transform.localToWorldMatrix.MultiplyVector(new Vector3(nm.forward[0], nm.forward[1], nm.forward[2]));
                fwd.y = 0f;
                fwd.Normalize();
                return Shoot(spec, lane, "native_" + spec.nativeName, holder, fwd, 0f, "native", ref first);
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(holder);
            }
        }

        private static GameObject BuildNative(NativeMesh nm)
        {
            var mesh = new Mesh { indexFormat = UnityEngine.Rendering.IndexFormat.UInt32 };
            var v = new Vector3[nm.pos.Length / 3];
            for (int i = 0; i < v.Length; i++) v[i] = new Vector3(nm.pos[3 * i], nm.pos[3 * i + 1], nm.pos[3 * i + 2]);
            var uv = new Vector2[nm.uv.Length / 2];
            for (int i = 0; i < uv.Length; i++) uv[i] = new Vector2(nm.uv[2 * i], nm.uv[2 * i + 1]);
            mesh.vertices = v;
            mesh.uv = uv;
            mesh.subMeshCount = nm.subs.Length;
            var mats = new Material[nm.subs.Length];
            for (int s = 0; s < nm.subs.Length; s++)
            {
                mesh.SetTriangles(nm.subs[s].tri, s);
                var tex = new Texture2D(2, 2);
                tex.LoadImage(File.ReadAllBytes(nm.subs[s].texture));
                mats[s] = new Material(_unlit) { mainTexture = tex };
            }
            mesh.RecalculateBounds();
            var go = new GameObject(nm.name);
            go.AddComponent<MeshFilter>().sharedMesh = mesh;
            go.AddComponent<MeshRenderer>().sharedMaterials = mats;
            return go;
        }

        // ---------------------------------------------------------------- owned
        private static void RenderOwned(Spec spec, string lane, string prefabPath, float nativeHeight, ref bool first)
        {
            GameObject asset = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
            if (asset == null) throw new InvalidOperationException("missing prefab " + prefabPath);
            string sid = prefabPath.Split('/')[3];
            var holder = new GameObject("owned_holder");
            try
            {
                GameObject inst = UnityEngine.Object.Instantiate(asset);
                inst.name = "owned_skinned";
                var orientation = inst.transform.Find("Orientation")
                                  ?? inst.GetComponentsInChildren<Transform>(true).FirstOrDefault(t => t.name == "Orientation" || t.name == "MocapDeliveryRoot");
                float baked = orientation != null ? Yaw(orientation.localRotation) : float.NaN;
                bool fleet = spec.rules == "fleet";
                bool after = spec.rules == "after" || fleet;
                float bind = fleet ? spec.bindFacingYaw : 0f;
                if (lane == "map")
                {
                    var shell = new GameObject("shell");
                    shell.transform.SetParent(holder.transform, false);
                    shell.transform.localRotation = Quaternion.Euler(0f, spec.mapShellRootYaw, 0f);
                    inst.transform.SetParent(shell.transform, false);
                    inst.transform.localRotation = Quaternion.identity;
                    Zero(inst);
                    if (after) SetYaw(orientation, spec.mapScaleRollYaw - bind);
                }
                else if (lane == "preview_synthetic")
                {
                    inst.transform.SetParent(holder.transform, false);
                    inst.transform.rotation = Quaternion.Euler(0f, spec.previewRootYaw, 0f);
                    if (fleet)
                    {
                        Zero(inst);
                        SetYaw(orientation, spec.battleScaleRollYaw - bind);
                    }
                }
                else if (lane == "preview_vanilla")
                {
                    inst.transform.SetParent(holder.transform, false);
                    inst.transform.rotation = Quaternion.Euler(0f, spec.previewRootYaw, 0f);
                    Zero(inst);
                    if (after) SetYaw(orientation, spec.battleScaleRollYaw - bind);
                }
                else
                {
                    bool left = lane == "battleL";
                    inst.transform.SetParent(holder.transform, false);
                    inst.transform.localRotation = Quaternion.Euler(0f, left ? 0f : 180f, 0f);
                    Zero(inst);
                    SetYaw(orientation, left ? spec.battleSideYawLeft : spec.battleSideYawRight);
                }
                SampleIdle(inst, prefabPath);
                Vector3 fwd = LimbForward(inst);
                // display size only: match the native unit's height in this lane (a uniform scale, facing unchanged)
                if (TryBounds(holder, out Bounds b) && b.size.y > 1e-4f && nativeHeight > 0f)
                    holder.transform.localScale = Vector3.one * (nativeHeight / b.size.y);
                BakeSkins(holder);
                // Attack aim: Homm3BattleAttackFacingHook turns the unit so the lane marker's forward points at the
                // target; the error is the angle between the body (limb) forward and the marker forward.
                var marker = inst.transform.Find("__homm3_skinned_battle_lane__");
                _attackAimError = float.NaN;
                if (marker != null && fwd != Vector3.zero)
                {
                    Vector3 m = marker.forward; m.y = 0f;
                    _attackAimError = Vector3.SignedAngle(m.normalized, fwd, Vector3.up);
                }
                Shoot(spec, lane, sid, holder, fwd, baked, "owned", ref first);
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(holder);
            }
        }

        private static void Zero(GameObject inst)
        {
            foreach (Transform t in inst.GetComponentsInChildren<Transform>(true))
                if (t != inst.transform && (t.name == "Orientation" || t.name == "MocapDeliveryRoot"))
                    t.localRotation = Quaternion.identity;
        }

        private static void SetYaw(Transform node, float yaw)
        {
            if (node == null) throw new InvalidOperationException("prefab has no Orientation node");
            node.localRotation = Quaternion.Euler(0f, yaw, 0f);
        }

        private static float Yaw(Quaternion q)
        {
            Vector3 f = q * Vector3.forward;
            return Mathf.Atan2(f.x, f.z) * Mathf.Rad2Deg;
        }

        // The lab's idle clip (Unit_Idle): from the controller when it resolves, else the prefab folder's own clip asset
        // (some mocap-lane lab controllers do not validate in this project, but their clips are the prefab's clips).
        private static void SampleIdle(GameObject inst, string prefabPath)
        {
            Animator animator = inst.GetComponentInChildren<Animator>(true);
            if (animator == null)
                throw new InvalidOperationException(inst.name + " has no animator");
            AnimationClip idle = (animator.runtimeAnimatorController != null ? animator.runtimeAnimatorController.animationClips : new AnimationClip[0])
                .Where(c => c != null && c.name.IndexOf("Idle", StringComparison.OrdinalIgnoreCase) >= 0)
                .OrderBy(c => c.name.Length).FirstOrDefault();
            if (idle == null)
                idle = AssetDatabase.FindAssets("t:AnimationClip", new[] { Path.GetDirectoryName(prefabPath).Replace('\\', '/') })
                    .Select(g => AssetDatabase.LoadAssetAtPath<AnimationClip>(AssetDatabase.GUIDToAssetPath(g)))
                    .Where(c => c != null && c.name.IndexOf("Idle", StringComparison.OrdinalIgnoreCase) >= 0 && !c.name.StartsWith("__preview__", StringComparison.Ordinal))
                    .OrderBy(c => c.name.Length).FirstOrDefault();
            if (idle == null) throw new InvalidOperationException(prefabPath + " has no idle clip");
            idle.SampleAnimation(animator.gameObject, 0f);
        }

        private static Vector3 LimbForward(GameObject inst)
        {
            // Same limb pairs, same order, as tools/validate_homm3_owned_skinned_facing_contract.py LIMB_PAIRS.
            string[][] pairs =
            {
                new[] { "mount:Bip01_L_Thigh", "mount:Bip01_R_Thigh" },
                new[] { "mixamorig:LeftUpLeg", "mixamorig:RightUpLeg" },
                new[] { "rider:mixamorig:LeftUpLeg", "rider:mixamorig:RightUpLeg" },
                new[] { "Bip01_L_Thigh", "Bip01_R_Thigh" },
                new[] { "LeftUpLeg", "RightUpLeg" },
                new[] { "LeftArm", "RightArm" },
            };
            Transform[] all = inst.GetComponentsInChildren<Transform>(true);
            foreach (string[] pair in pairs)
            {
                Transform l = all.FirstOrDefault(t => t.name == pair[0]), r = all.FirstOrDefault(t => t.name == pair[1]);
                if (l == null || r == null) continue;
                Vector3 f = Vector3.Cross(r.position - l.position, Vector3.up);
                f.y = 0f;
                if (f.sqrMagnitude < 1e-10f) continue;
                return f.normalized;
            }
            return Vector3.zero;
        }

        private static bool TryBounds(GameObject root, out Bounds b)
        {
            b = default;
            bool any = false;
            foreach (Renderer r in root.GetComponentsInChildren<Renderer>(true))
            {
                if (!(r is SkinnedMeshRenderer) && !(r is MeshRenderer)) continue;
                if (r is MeshRenderer && !r.enabled) continue;
                if (!any) { b = r.bounds; any = true; } else b.Encapsulate(r.bounds);
            }
            return any;
        }

        private static void BakeSkins(GameObject root)
        {
            foreach (MeshRenderer mr in root.GetComponentsInChildren<MeshRenderer>(true))
                mr.enabled = false; // effect quads, not the body
            // a uvAtlas albedo shows one cell at a time (the runtime restamps _MainTex_ST); show the rest cell0
            Transform cell0 = root.GetComponentsInChildren<Transform>(true).FirstOrDefault(t => t.name == "cell0" && t.parent != null && t.parent.name == "__homm3_vfx_uvatlas__");
            foreach (SkinnedMeshRenderer smr in root.GetComponentsInChildren<SkinnedMeshRenderer>(true))
            {
                var baked = new Mesh { indexFormat = UnityEngine.Rendering.IndexFormat.UInt32 };
                smr.BakeMesh(baked, true);
                var go = new GameObject(smr.name + "_baked");
                go.transform.SetPositionAndRotation(smr.transform.position, smr.transform.rotation);
                go.transform.SetParent(root.transform, true);
                go.transform.localScale = new Vector3(1f / root.transform.lossyScale.x, 1f / root.transform.lossyScale.y, 1f / root.transform.lossyScale.z);
                go.AddComponent<MeshFilter>().sharedMesh = baked;
                var mats = smr.sharedMaterials.Select(m =>
                {
                    Texture t = null;
                    if (m != null)
                        foreach (string p in new[] { "_MainTex", "_BaseMap", "_BaseColorMap" })
                            if (m.HasProperty(p) && m.GetTexture(p) != null) { t = m.GetTexture(p); break; }
                    var mat = new Material(_unlit) { mainTexture = t };
                    if (cell0 != null)
                    {
                        mat.mainTextureScale = new Vector2(cell0.localScale.x, cell0.localScale.y);
                        mat.mainTextureOffset = new Vector2(cell0.localPosition.x, cell0.localPosition.y);
                    }
                    return mat;
                }).ToArray();
                go.AddComponent<MeshRenderer>().sharedMaterials = mats;
                smr.enabled = false;
            }
        }

        // ---------------------------------------------------------------- camera
        private static float Pitch(string lane) => lane == "map" ? 50f : lane.StartsWith("preview", StringComparison.Ordinal) ? 10f : 35f;

        private static float _attackAimError = float.NaN;

        private static float Shoot(Spec spec, string lane, string name, GameObject root, Vector3 fwd, float bakedYaw, string kind, ref bool first)
        {
            if (!TryBounds(root, out Bounds b)) throw new InvalidOperationException(name + " has no renderers");
            float pitch = Pitch(lane) * Mathf.Deg2Rad;
            Vector3 toCam = new Vector3(0f, Mathf.Sin(pitch), -Mathf.Cos(pitch));
            var camGo = new GameObject("proof_cam");
            try
            {
                var cam = camGo.AddComponent<Camera>();
                cam.orthographic = true;
                float extent = Mathf.Max(b.extents.x, b.extents.y, b.extents.z);
                cam.orthographicSize = extent * 1.15f;
                cam.transform.position = b.center + toCam * (extent * 6f);
                cam.transform.LookAt(b.center);
                cam.nearClipPlane = 0.01f;
                cam.farClipPlane = extent * 20f;
                cam.clearFlags = CameraClearFlags.SolidColor;
                cam.backgroundColor = new Color(0.36f, 0.38f, 0.42f, 1f);
                int size = spec.tile > 0 ? spec.tile : 384;
                var rt = new RenderTexture(size, size, 24, RenderTextureFormat.ARGB32);
                cam.targetTexture = rt;
                cam.Render();
                RenderTexture.active = rt;
                var tex = new Texture2D(size, size, TextureFormat.RGBA32, false);
                tex.ReadPixels(new Rect(0, 0, size, size), 0, 0);
                tex.Apply();
                RenderTexture.active = null;
                cam.targetTexture = null;
                string file = lane + "__" + name + ".png";
                File.WriteAllBytes(Path.Combine(spec.outDir, file), tex.EncodeToPNG());
                UnityEngine.Object.DestroyImmediate(rt);
                UnityEngine.Object.DestroyImmediate(tex);
                Vector3 flatCam = new Vector3(0f, 0f, -1f);
                float yaw = fwd == Vector3.zero ? float.NaN : Mathf.Atan2(fwd.x, fwd.z) * Mathf.Rad2Deg;
                float towardCamera = fwd == Vector3.zero ? float.NaN : Vector3.Angle(fwd, flatCam);
                if (!first) Report.Append(",\n");
                first = false;
                Report.Append("    {\"lane\": \"" + lane + "\", \"unit\": \"" + name + "\", \"kind\": \"" + kind + "\", \"png\": \"" + file
                    + "\", \"worldForwardYaw\": " + F(yaw) + ", \"angleFromCameraDir\": " + F(towardCamera)
                    + ", \"facesCamera\": " + (float.IsNaN(towardCamera) ? "null" : (towardCamera < 90f ? "true" : "false"))
                    + (kind == "owned" ? ", \"prefabBakedOrientationYaw\": " + F(bakedYaw) + ", \"attackAimErrorDeg\": " + F(_attackAimError) : "") + ", \"height\": " + F(b.size.y) + "}");
                return b.size.y;
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(camGo);
            }
        }

        private static string F(float v) => float.IsNaN(v) ? "null" : v.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture);
    }
}
