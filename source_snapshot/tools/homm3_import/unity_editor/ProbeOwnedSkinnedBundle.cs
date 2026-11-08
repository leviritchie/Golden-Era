// Canonical copy for git. Deploy to: <UnityProject>/Assets/Editor/ProbeOwnedSkinnedBundle.cs
// Batch: -executeMethod OldenEra.Homm3Import.ProbeOwnedSkinnedBundle.Run -bundlePath <abs> -logFile <abs>
// Offline probe of the crusader owned-skinned bundle: asset table, texture addressability,
// override/base controller resolution, and a real Animator.Update bone-motion smoke test.

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

namespace OldenEra.Homm3Import
{
	public static class ProbeOwnedSkinnedBundle
	{
		const string TexPath = "Assets/CustomUnits/homm3_lab/h3_crusader/OwnedSkinned/crusader_owned_skinned_basecolor.jpg";
		const string NormalPath = "Assets/CustomUnits/homm3_lab/h3_crusader/OwnedSkinned/crusader_owned_skinned_normal.png";
		const string MetallicGlossPath = "Assets/CustomUnits/homm3_lab/h3_crusader/OwnedSkinned/crusader_owned_skinned_metallicgloss.png";
		const string OverridePath = "Assets/CustomUnits/homm3_lab/h3_crusader/OwnedSkinned/crusader_owned_skinned.overrideController";
		const string BasePath = "Assets/CustomUnits/homm3_lab/h3_crusader/OwnedSkinned/Reference/StockEsquireBattle.controller";
		const string PrefabPath = "Assets/CustomUnits/homm3_lab/h3_crusader/OwnedSkinned/crusader_owned_skinned.prefab";

		public static void Run()
		{
			string bundlePath = null;
			var args = Environment.GetCommandLineArgs();
			for (var i = 0; i < args.Length - 1; i++)
			{
				if (args[i] == "-bundlePath")
					bundlePath = args[i + 1];
			}
			if (string.IsNullOrEmpty(bundlePath) || !File.Exists(bundlePath))
				throw new InvalidOperationException("ProbeOwnedSkinnedBundle: -bundlePath missing or not found: " + bundlePath);

			Log("=== ProbeOwnedSkinnedBundle start: " + bundlePath);
			var b = AssetBundle.LoadFromFile(bundlePath);
			if (b == null)
			{
				Log("FATAL: bundle load failed");
				return;
			}

			var names = b.GetAllAssetNames();
			Log("assetNames count=" + names.Length);
			foreach (var n in names)
				Log("  asset: " + n);

			var tex = b.LoadAsset<Texture2D>(TexPath);
			Log("LoadAsset<Texture2D>('" + TexPath + "') -> " + (tex ? tex.name + " " + tex.width + "x" + tex.height : "NULL"));
			var normal = b.LoadAsset<Texture2D>(NormalPath);
			Log("LoadAsset<Texture2D>('" + NormalPath + "') -> " + (normal ? normal.name + " " + normal.width + "x" + normal.height : "NULL"));
			var metal = b.LoadAsset<Texture2D>(MetallicGlossPath);
			Log("LoadAsset<Texture2D>('" + MetallicGlossPath + "') -> " + (metal ? metal.name + " " + metal.width + "x" + metal.height : "NULL"));
			if (tex == null || normal == null || metal == null)
				throw new InvalidOperationException("ProbeOwnedSkinnedBundle: crusader Hex/Lit PBR textures are missing from the bundle.");

			var ovr = b.LoadAsset<AnimatorOverrideController>(OverridePath);
			Log("override='" + (ovr ? ovr.name : "NULL") + "'");
			if (ovr)
			{
				var rb = ovr.runtimeAnimatorController;
				Log("override.runtimeAnimatorController(base) -> " + (rb ? rb.name : "NULL"));
				var pairs = new List<KeyValuePair<AnimationClip, AnimationClip>>();
				ovr.GetOverrides(pairs);
				Log("override pairs=" + pairs.Count);
				foreach (var p in pairs.Take(6))
					Log("  pair orig=" + (p.Key ? p.Key.name : "NULL")
						+ " override=" + (p.Value ? p.Value.name : "NULL"));
			}

			var baseCtrl = b.LoadAsset<RuntimeAnimatorController>(BasePath);
			Log("baseController load -> " + (baseCtrl ? baseCtrl.name : "NULL"));
			if (baseCtrl is AnimatorController ac)
			{
				var layers = ac.layers;
				Log("base layers=" + layers.Length);
				foreach (var l in layers)
				{
					var sm = l.stateMachine;
					var states = sm.states;
					Log("  layer '" + l.name + "' states=" + states.Length
						+ " default=" + (sm.defaultState ? sm.defaultState.name : "NULL"));
					foreach (var s in states.Take(4))
						Log("    state '" + s.state.name + "' motion=" + (s.state.motion ? s.state.motion.name : "NULL"));
				}
			}

			var prefab = b.LoadAsset<GameObject>(PrefabPath);
			Log("prefab load -> " + (prefab ? prefab.name : "NULL"));
			if (prefab)
			{
				var go = UnityEngine.Object.Instantiate(prefab);
				go.SetActive(true);
				var skin = go.GetComponentInChildren<SkinnedMeshRenderer>(true);
				var anim = go.GetComponentInChildren<Animator>(true);
				Log("animator -> " + (anim ? anim.name + " ctrl="
					+ (anim.runtimeAnimatorController ? anim.runtimeAnimatorController.name : "NULL")
					+ " enabled=" + anim.enabled : "NULL"));
				if (anim && skin != null)
				{
					anim.enabled = true;
					anim.cullingMode = AnimatorCullingMode.AlwaysAnimate;
					var bones = skin.bones;
					var sample = bones != null && bones.Length >= 3
						? new[] { bones[0], bones[bones.Length / 2], bones[bones.Length - 1] }
						: go.GetComponentsInChildren<Transform>(true).Take(3).ToArray();
					var before = sample.Select(t => t.position).ToArray();
					anim.Update(0.05f);
					var state0 = anim.GetCurrentAnimatorStateInfo(0);
					Log("state0 nameHash=" + state0.shortNameHash + " length=" + state0.length
						+ " normTime=" + state0.normalizedTime + " playing=" + (state0.length > 0f));
					var clipInfo = anim.GetCurrentAnimatorClipInfo(0);
					Log("active clips: " + string.Join(", ", clipInfo.Select(c => c.clip ? c.clip.name : "NULL")));
					var rc = anim.runtimeAnimatorController;
					if (rc is AnimatorController rac)
					{
						try
						{
							var lay0 = rac.layers[0];
							var sm0 = lay0.stateMachine;
							var ds = sm0 ? sm0.defaultState : null;
							Log("overrideBase layers=" + rac.layers.Length
								+ " defaultState=" + (ds ? ds.name : "NULL")
								+ " motion=" + (ds && ds.motion ? ds.motion.name : "NULL"));
						}
						catch (Exception ex)
						{
							Log("overrideBase layer read failed: " + ex.Message);
						}
					}
					var hierarchyPaths = new List<string>();
					CollectPaths(anim.transform, "", hierarchyPaths, 24);
					Log("hierarchy paths (" + hierarchyPaths.Count + "): " + string.Join(" | ", hierarchyPaths.Take(12)));
					var moveClip = b.LoadAsset<AnimationClip>("assets/customunits/homm3_lab/h3_crusader/ownedskinned/animations/crusader_move.anim");
					Log("crusader_move.anim load -> " + (moveClip ? moveClip.name + " frames=" + moveClip.length : "NULL"));
					if (moveClip)
					{
						Log("crusader_move empty=" + moveClip.empty + " legacy=" + moveClip.legacy);
						var bindings = AnimationUtility.GetCurveBindings(moveClip);
						Log("crusader_move bindings=" + bindings.Length + ": "
							+ string.Join(" | ", bindings.Take(8).Select(bp => bp.path)));
					}
					var mouseoverClip = b.LoadAsset<AnimationClip>("assets/customunits/homm3_lab/h3_crusader/ownedskinned/animations/crusader_mouseover.anim");
					if (mouseoverClip)
					{
						Log("crusader_mouseover empty=" + mouseoverClip.empty
							+ " bindings=" + AnimationUtility.GetCurveBindings(mouseoverClip).Length);
					}
					var mat = b.LoadAsset<Material>("assets/customunits/homm3_lab/h3_crusader/ownedskinned/crusader_owned_skinned.mat");
					if (mat)
					{
						var t = mat.GetTexture("_MainTex");
						Log("bundle mat _MainTex -> " + (t ? t.name : "NULL") + " shader=" + (mat.shader ? mat.shader.name : "NULL"));
					}
					anim.Update(0.3f);
					var after = sample.Select(t => t.position).ToArray();
					var moved = false;
					for (var i = 0; i < sample.Length; i++)
						if ((before[i] - after[i]).sqrMagnitude > 1e-6f)
							moved = true;
					Log("bones moved after animator.Update: " + moved);
				}
			}

			b.Unload(false);
			Log("=== ProbeOwnedSkinnedBundle end");
		}

		static void Log(string msg)
		{
			Debug.Log("[ProbeOwnedSkinnedBundle] " + msg);
		}

		static void CollectPaths(Transform t, string prefix, List<string> dest, int max)
		{
			if (t == null || dest.Count >= max)
				return;
			var path = string.IsNullOrEmpty(prefix) ? t.name : prefix + "/" + t.name;
			dest.Add(path);
			for (var i = 0; i < t.childCount && dest.Count < max; i++)
				CollectPaths(t.GetChild(i), path, dest, max);
		}
	}
}
