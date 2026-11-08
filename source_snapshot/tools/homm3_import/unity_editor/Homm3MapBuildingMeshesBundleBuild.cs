using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

namespace OldenEra.Homm3Import
{
	/// <summary>
	/// Builds <c>homm3_map_building_meshes</c> AssetBundle from Meshy GLBs under
	/// artifacts/meshy_map_buildings/meshes plus inventory.json. Writes catalog.json and
	/// asset manifest beside the bundle.
	/// Incremental (2026-09-27): staged files keep their .meta (GUID), a source whose bytes are unchanged is not
	/// copied or reimported, and only files that left the output set are deleted (with their .meta) before the
	/// bundle is built. Every run used to delete all metas and reimport all 96 models, leaving the previous
	/// run's artifacts orphaned in Library. Before each model the free space of the project drive is checked;
	/// below -minFreeGb (default 8) the build stops between models, never mid-import.
	/// </summary>
	public static class Homm3MapBuildingMeshesBundleBuild
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

		const string BundleName = "homm3_map_building_meshes";
		const string AssetRoot = "Assets/Homm3MapBuildingMeshes";
		const string CatalogSchema = "homm3_map_building_mesh_catalog.v1";
		const string ManifestSchema = "homm3_ui_bundle_asset_manifest.v1";

		[Serializable]
		class AssetManifest
		{
			public string schema;
			public string bundle;
			public int assetCount;
			public List<string> assets;
		}

		[Serializable]
		class CatalogFile
		{
			public string schema;
			public string bundle;
			public int entryCount;
			public List<CatalogEntryJson> entries;
		}

		[Serializable]
		class CatalogEntryJson
		{
			public string relativePng;
			public string prefabKey;
			public string kind;
			public float targetHeight;
			// Map-building animation baked into the prefab (tools/homm3_map_building_meshes/map_building_anim.py).
			// Empty lane = static prefab.
			public string animLane;
			public List<string> animRotorPaths;
			public List<string> animPartPaths;
			public List<string> animAnchorPaths;
			public string animSourceModel;
		}

		const string AnimSidecarSchema = "homm3_map_building_anim_sidecar.v1";
		const string RotorPivotPrefix = "HOMM3_anim_rotor_";
		const string PartPivotPrefix = "HOMM3_anim_part_";
		const string AnchorPrefix = "HOMM3_anim_anchor_";

		[Serializable]
		class AnimSidecar
		{
			public string schema;
			public string relativePng;
			public string prefabKey;
			public string lane;
			public AnimSidecarRotor[] rotors;
			public AnimSidecarPart[] parts;
			public AnimSidecarAnchor[] anchors;
		}

		// Keyed rigid part (pendulum / articulated_rigid): glTF angle about the pivot's local +Z and
		// lift along local +Z in model units, sampled densely over one loop by map_building_anim.py.
		[Serializable]
		class AnimSidecarPart
		{
			public string name;
			public string kind;
			public int parent;
			public float loopSeconds;
			public float[] keyTimes;
			public float[] angleDeg;
			public float[] lift;
		}

		[Serializable]
		class AnimSidecarRotor
		{
			public float gltfDegPerSecondAboutLocalZ;
			public float periodSeconds;
			public string direction;
		}

		[Serializable]
		class AnimSidecarAnchor
		{
			public string id;
		}

		public static void BuildFromBatch()
		{
			var inventoryPath = ResolveArg("-inventoryPath", null);
			var meshesRoot = ResolveArg("-meshesRoot", null);
			var outputPath = ResolveArg("-outputPath", Path.Combine("tools", "homm3_import", "build_out"));
			if (string.IsNullOrWhiteSpace(inventoryPath) || !File.Exists(inventoryPath))
				throw new InvalidOperationException("Requires -inventoryPath pointing at inventory.json");
			if (string.IsNullOrWhiteSpace(meshesRoot) || !Directory.Exists(meshesRoot))
				throw new InvalidOperationException("Requires -meshesRoot pointing at Meshy meshes folder");
			var minFreeGbArg = ResolveArg("-minFreeGb", "8");
			if (!double.TryParse(minFreeGbArg, NumberStyles.Float, CultureInfo.InvariantCulture, out var minFreeGb) || minFreeGb < 0)
				throw new InvalidOperationException("-minFreeGb must be a non-negative number, got '" + minFreeGbArg + "'");
			Build(inventoryPath, meshesRoot, outputPath, minFreeGb);
		}

		static void Build(string inventoryPath, string meshesRoot, string outputPath, double minFreeGb)
		{
			EnsureFolder(AssetRoot);
			var produced = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
			var modelIndex = 0;

			var inventoryJson = File.ReadAllText(inventoryPath);
			var entries = ParseInventoryEntries(inventoryJson);
			if (entries.Count == 0)
				throw new InvalidOperationException("inventory has no generate=true entries with meshes");

			var prefabPaths = new List<string>();
			var catalogEntries = new List<CatalogEntryJson>();

			foreach (var entry in entries)
			{
				modelIndex++;
				CheckFreeSpace(minFreeGb, "before model " + modelIndex + "/" + entries.Count + " (" + entry.PrefabKey + ")");
				var meshDir = Path.Combine(meshesRoot, entry.Dir.Replace('/', Path.DirectorySeparatorChar));
				var glb = Path.Combine(meshDir, "model.glb");
				var fbx = Path.Combine(meshDir, "model.fbx");
				var animGlb = Path.Combine(meshDir, "model_anim.glb");
				var animSidecarPath = Path.Combine(meshDir, "map_anim.json");
				AnimSidecar animSidecar = null;
				if (File.Exists(animSidecarPath))
				{
					animSidecar = JsonUtility.FromJson<AnimSidecar>(File.ReadAllText(animSidecarPath));
					if (animSidecar == null || animSidecar.schema != AnimSidecarSchema)
						throw new InvalidOperationException("map_anim.json schema mismatch under " + meshDir);
					if (!string.Equals(animSidecar.prefabKey, entry.PrefabKey, StringComparison.OrdinalIgnoreCase))
						throw new InvalidOperationException("map_anim.json prefabKey '" + animSidecar.prefabKey + "' != '" + entry.PrefabKey + "'");
					if (!File.Exists(animGlb))
						throw new InvalidOperationException("map_anim.json present but model_anim.glb missing under " + meshDir);
				}
				string modelSource = null;
				if (animSidecar != null)
					modelSource = animGlb;
				else if (File.Exists(glb))
					modelSource = glb;
				else if (File.Exists(fbx))
					modelSource = fbx;
				else
				{
					Debug.LogWarning("Skipping missing GLB/FBX for " + entry.RelativePng + " under " + meshDir);
					continue;
				}

				var safeKey = entry.PrefabKey;
				var modelExt = Path.GetExtension(modelSource);
				var modelAsset = AssetRoot + "/" + safeKey + modelExt;
				var changed = new List<string>();
				StageAsset(modelSource, modelAsset, produced, changed);

				var albedoPath = FindTexture(meshDir, "base_color") ?? Path.Combine(meshDir, "source_00_00.png");
				var albedoAsset = AssetRoot + "/" + safeKey + "_albedo.png";
				if (File.Exists(albedoPath))
					StageAsset(albedoPath, albedoAsset, produced, changed);
				else
					throw new InvalidOperationException("Missing albedo for " + entry.RelativePng);

				var normalSrc = FindTexture(meshDir, "normal");
				var metallicSrc = FindTexture(meshDir, "metallic");
				var roughnessSrc = FindTexture(meshDir, "roughness");
				string normalAsset = null;
				string metallicAsset = null;
				string roughnessAsset = null;
				if (normalSrc != null)
				{
					normalAsset = AssetRoot + "/" + safeKey + "_normal.png";
					StageAsset(normalSrc, normalAsset, produced, changed);
				}
				if (metallicSrc != null)
				{
					metallicAsset = AssetRoot + "/" + safeKey + "_metallic.png";
					StageAsset(metallicSrc, metallicAsset, produced, changed);
				}
				if (roughnessSrc != null)
				{
					roughnessAsset = AssetRoot + "/" + safeKey + "_roughness.png";
					StageAsset(roughnessSrc, roughnessAsset, produced, changed);
				}

				// Only changed files are imported; an unchanged file keeps its GUID and cached artifact, and its
				// importer is rewritten only if its settings drifted.
				AssetDatabase.Refresh();
				ConfigureTexture(albedoAsset, sRGB: true, normalMap: false);
				if (normalAsset != null)
					ConfigureTexture(normalAsset, sRGB: false, normalMap: true);
				if (metallicAsset != null)
					ConfigureTexture(metallicAsset, sRGB: false, normalMap: false);
				if (roughnessAsset != null)
					ConfigureTexture(roughnessAsset, sRGB: false, normalMap: false);
				if (changed.Contains(modelAsset) || AssetDatabase.LoadAssetAtPath<GameObject>(modelAsset) == null)
					ConfigureModel(modelAsset);
				AssetDatabase.Refresh();
				Debug.Log("Homm3MapBuildingMeshesBundleBuild: model " + modelIndex + "/" + entries.Count + " " + safeKey
				          + (changed.Count > 0 ? " imported [" + string.Join(", ", changed.ConvertAll(f => Path.GetFileName(f))) + "]" : " skipped (unchanged)"));

				var modelRoot = AssetDatabase.LoadAssetAtPath<GameObject>(modelAsset);
				if (modelRoot == null)
					throw new InvalidOperationException("Failed to load GLB " + modelAsset);

				var material = CreateAuthoredMaterial(
					safeKey,
					AssetDatabase.LoadAssetAtPath<Texture2D>(albedoAsset),
					normalAsset != null ? AssetDatabase.LoadAssetAtPath<Texture2D>(normalAsset) : null,
					metallicAsset != null ? AssetDatabase.LoadAssetAtPath<Texture2D>(metallicAsset) : null,
					roughnessAsset != null ? AssetDatabase.LoadAssetAtPath<Texture2D>(roughnessAsset) : null);
				var materialPath = AssetRoot + "/" + safeKey + ".mat";
				AssetDatabase.CreateAsset(material, materialPath);
				produced.Add(materialPath);

				var prefabPath = AssetRoot + "/" + safeKey + ".prefab";
				var prefabRoot = BuildPrefab(modelRoot, material, safeKey, entry.TargetHeight);
				var catalogEntry = new CatalogEntryJson
				{
					relativePng = entry.RelativePng,
					prefabKey = safeKey,
					kind = entry.Kind,
					targetHeight = entry.TargetHeight,
					animLane = string.Empty,
					animRotorPaths = new List<string>(),
					animPartPaths = new List<string>(),
					animAnchorPaths = new List<string>(),
					animSourceModel = string.Empty
				};
				if (animSidecar != null)
					BakeMapAnimation(prefabRoot, animSidecar, safeKey, catalogEntry);
				PrefabUtility.SaveAsPrefabAsset(prefabRoot, prefabPath);
				produced.Add(prefabPath);
				foreach (var suffix in new[] { "_rotor_loop.anim", "_rotor.controller", "_parts_loop.anim", "_parts.controller" })
				{
					var generated = AssetRoot + "/" + safeKey + suffix;
					if (File.Exists(Path.GetFullPath(generated)))
						produced.Add(generated);
				}
				UnityEngine.Object.DestroyImmediate(prefabRoot);

				prefabPaths.Add(prefabPath);
				catalogEntries.Add(catalogEntry);
			}

			if (prefabPaths.Count == 0)
				throw new InvalidOperationException("No prefabs built — no Meshy GLBs found for inventory generate set.");

			AssetDatabase.SaveAssets();
			RemoveAssetsOutsideOutputSet(produced);
			var absoluteOutput = Path.GetFullPath(outputPath);
			Directory.CreateDirectory(absoluteOutput);

			var buildMap = new[]
			{
				new AssetBundleBuild
				{
					assetBundleName = BundleName,
					assetNames = prefabPaths.ToArray()
				}
			};
			var manifest = BuildPipeline.BuildAssetBundles(
				absoluteOutput,
				buildMap,
				BuildAssetBundleOptions.ChunkBasedCompression,
				BuildTarget.StandaloneWindows64);
			if (manifest == null)
				throw new InvalidOperationException("BuildPipeline.BuildAssetBundles returned null for " + BundleName);

			var bundlePath = Path.Combine(absoluteOutput, BundleName);
			if (!File.Exists(bundlePath))
				throw new InvalidOperationException("Expected bundle missing: " + bundlePath);

			WriteAssetManifest(absoluteOutput, prefabPaths);
			WriteCatalog(absoluteOutput, catalogEntries);
			Debug.Log(
				"Homm3MapBuildingMeshesBundleBuild: built "
				+ bundlePath
				+ " prefabs="
				+ prefabPaths.Count);
		}

		sealed class InventoryEntry
		{
			public string RelativePng;
			public string PrefabKey;
			public string Kind;
			public string Dir;
			public float TargetHeight;
			public bool Generate;
		}

		static List<InventoryEntry> ParseInventoryEntries(string json)
		{
			// Lightweight parse via MiniJSON-like regex-free scan using JsonUtility is awkward for
			// nested arrays; use Unity's JsonUtility on a wrapper after extracting with simple splits.
			var list = new List<InventoryEntry>();
			var idx = 0;
			while (true)
			{
				var relIdx = json.IndexOf("\"relativePng\"", idx, StringComparison.Ordinal);
				if (relIdx < 0)
					break;
				var relativePng = ReadString(json, relIdx);
				// Read every field inside this row's own braces. inventory.json writes "kind" before
				// "relativePng", so a forward scan from relativePng took the NEXT row's kind (every city was
				// catalogued "dwelling" and each faction's last dwelling "city").
				var objStart = json.LastIndexOf('{', relIdx);
				var objEnd = FindObjectEnd(json, objStart);
				var prefabKey = ReadFieldString(json, objStart, objEnd, "prefabKey");
				var kind = ReadFieldString(json, objStart, objEnd, "kind");
				var dir = ReadFieldString(json, objStart, objEnd, "dir");
				var generate = ReadFieldBool(json, objStart, objEnd, "generate", false);
				var height = ReadFieldFloat(json, objStart, objEnd, "targetHeight", 2.25f);
				idx = objEnd;
				if (!generate || string.IsNullOrEmpty(relativePng) || string.IsNullOrEmpty(prefabKey) || string.IsNullOrEmpty(dir))
					continue;
				if (string.IsNullOrEmpty(kind))
					throw new InvalidOperationException("inventory row " + prefabKey + " has no \"kind\"");
				list.Add(new InventoryEntry
				{
					RelativePng = relativePng.Replace('\\', '/'),
					PrefabKey = prefabKey,
					Kind = kind,
					Dir = dir.Replace('\\', '/'),
					TargetHeight = height > 0.01f ? height : 2.25f,
					Generate = true
				});
			}
			return list;
		}

		/// <summary>Index of the closing brace of the object opening at <paramref name="objStart"/> (strings skipped).</summary>
		static int FindObjectEnd(string json, int objStart)
		{
			if (objStart < 0 || json[objStart] != '{')
				throw new InvalidOperationException("inventory row has no opening brace before relativePng");
			var depth = 0;
			var inString = false;
			for (var i = objStart; i < json.Length; i++)
			{
				var c = json[i];
				if (inString)
				{
					if (c == '\\')
						i++;
					else if (c == '"')
						inString = false;
					continue;
				}
				if (c == '"')
					inString = true;
				else if (c == '{' || c == '[')
					depth++;
				else if ((c == '}' || c == ']') && --depth == 0)
					return i;
			}
			throw new InvalidOperationException("inventory row starting at " + objStart + " is not closed");
		}

		/// <summary>Index of <c>"field"</c> as a key between <paramref name="from"/> and <paramref name="end"/>, else -1.</summary>
		static int FindField(string json, int from, int end, string field)
		{
			var idx = json.IndexOf("\"" + field + "\"", from, StringComparison.Ordinal);
			return idx < 0 || idx > end ? -1 : idx;
		}

		static string ReadFieldString(string json, int from, int end, string field)
		{
			var idx = FindField(json, from, end, field);
			if (idx < 0)
				return null;
			return ReadString(json, idx);
		}

		static bool ReadFieldBool(string json, int from, int end, string field, bool fallback)
		{
			var idx = FindField(json, from, end, field);
			if (idx < 0)
				return fallback;
			var colon = json.IndexOf(':', idx);
			if (colon < 0)
				return fallback;
			var slice = json.Substring(colon + 1, Math.Min(16, json.Length - colon - 1));
			if (slice.IndexOf("true", StringComparison.OrdinalIgnoreCase) >= 0)
				return true;
			if (slice.IndexOf("false", StringComparison.OrdinalIgnoreCase) >= 0)
				return false;
			return fallback;
		}

		static float ReadFieldFloat(string json, int from, int objEnd, string field, float fallback)
		{
			var idx = FindField(json, from, objEnd, field);
			if (idx < 0)
				return fallback;
			var colon = json.IndexOf(':', idx);
			if (colon < 0)
				return fallback;
			var end = colon + 1;
			while (end < json.Length && char.IsWhiteSpace(json[end]))
				end++;
			var start = end;
			while (end < json.Length && (char.IsDigit(json[end]) || json[end] == '.' || json[end] == '-'))
				end++;
			if (start >= end)
				return fallback;
			return float.TryParse(
				json.Substring(start, end - start),
				NumberStyles.Float,
				CultureInfo.InvariantCulture,
				out var v)
				? v
				: fallback;
		}

		static string ReadString(string json, int fieldNameIdx)
		{
			var colon = json.IndexOf(':', fieldNameIdx);
			if (colon < 0)
				return null;
			var firstQuote = json.IndexOf('"', colon + 1);
			if (firstQuote < 0)
				return null;
			var i = firstQuote + 1;
			var chars = new List<char>();
			while (i < json.Length)
			{
				var c = json[i++];
				if (c == '\\' && i < json.Length)
				{
					chars.Add(json[i++]);
					continue;
				}
				if (c == '"')
					break;
				chars.Add(c);
			}
			return new string(chars.ToArray());
		}

		static string FindTexture(string meshDir, string key)
		{
			var matches = Directory.GetFiles(meshDir, "texture_*_" + key + ".png");
			if (matches != null && matches.Length > 0)
				return matches[0];
			matches = Directory.GetFiles(meshDir, "*" + key + "*.png");
			if (matches != null && matches.Length > 0)
				return matches[0];
			return null;
		}

		static GameObject BuildPrefab(GameObject modelRoot, Material material, string prefabName, float targetHeight)
		{
			var instance = PrefabUtility.InstantiatePrefab(modelRoot) as GameObject;
			if (instance == null)
				instance = UnityEngine.Object.Instantiate(modelRoot);
			instance.name = prefabName;
			var renderers = instance.GetComponentsInChildren<Renderer>(true);
			if (renderers == null || renderers.Length == 0)
				throw new InvalidOperationException("Meshy GLB has no Renderer: " + prefabName);
			foreach (var renderer in renderers)
			{
				var mats = new Material[renderer.sharedMaterials != null && renderer.sharedMaterials.Length > 0
					? renderer.sharedMaterials.Length
					: 1];
				for (var i = 0; i < mats.Length; i++)
					mats[i] = material;
				renderer.sharedMaterials = mats;
				renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.On;
				renderer.receiveShadows = true;
			}
			NormalizeToTargetHeight(instance.transform, targetHeight);
			return instance;
		}

		/// <summary>
		/// Native Olden Era map objects (windmill, sawmill) animate rigid parts with an Animator on the
		/// prefab. Rotor pivots from model_anim.glb get one looping clip that spins each pivot about its
		/// local Z; flipbook anchors are only verified here (the runtime puts quads on them).
		/// </summary>
		static void BakeMapAnimation(GameObject prefabRoot, AnimSidecar sidecar, string safeKey, CatalogEntryJson catalogEntry)
		{
			catalogEntry.animLane = sidecar.lane ?? string.Empty;
			catalogEntry.animSourceModel = "model_anim.glb";
			var all = prefabRoot.GetComponentsInChildren<Transform>(true);
			var pivots = new List<Transform>();
			var anchors = new List<Transform>();
			foreach (var t in all)
			{
				if (t.name.StartsWith(RotorPivotPrefix, StringComparison.Ordinal) && t.name.EndsWith("_pivot", StringComparison.Ordinal))
					pivots.Add(t);
				else if (t.name.StartsWith(AnchorPrefix, StringComparison.Ordinal))
					anchors.Add(t);
			}
			pivots.Sort((a, b) => string.CompareOrdinal(a.name, b.name));
			anchors.Sort((a, b) => string.CompareOrdinal(a.name, b.name));
			var rotorCount = sidecar.rotors != null ? sidecar.rotors.Length : 0;
			var anchorCount = sidecar.anchors != null ? sidecar.anchors.Length : 0;
			if (pivots.Count != rotorCount)
				throw new InvalidOperationException(safeKey + ": sidecar lists " + rotorCount + " rotor(s) but model_anim.glb imported " + pivots.Count + " pivot(s).");
			if (anchors.Count != anchorCount)
				throw new InvalidOperationException(safeKey + ": sidecar lists " + anchorCount + " anchor(s) but model_anim.glb imported " + anchors.Count + ".");
			foreach (var a in anchors)
				catalogEntry.animAnchorPaths.Add(AnimationUtility.CalculateTransformPath(a, prefabRoot.transform));
			var partCount = sidecar.parts != null ? sidecar.parts.Length : 0;
			if (partCount > 0)
			{
				if (rotorCount > 0)
					throw new InvalidOperationException(safeKey + ": sidecar mixes rotors and keyed parts; one clip lane per prefab.");
				BakeKeyedParts(prefabRoot, sidecar.parts, safeKey, catalogEntry);
				return;
			}
			if (rotorCount == 0)
				return;

			// One clip covers a whole revolution of the slowest rotor so the loop point is seamless.
			var longest = 0f;
			for (var i = 0; i < rotorCount; i++)
			{
				var deg = Mathf.Abs(sidecar.rotors[i].gltfDegPerSecondAboutLocalZ);
				if (deg < 1e-3f)
					throw new InvalidOperationException(safeKey + ": rotor " + i + " has zero spin rate.");
				longest = Mathf.Max(longest, 360f / deg);
			}
			var clip = new AnimationClip { name = safeKey + "_rotor_loop", legacy = false, frameRate = 60f };
			const int keys = 144;
			for (var i = 0; i < rotorCount; i++)
			{
				var pivot = pivots[i];
				var path = AnimationUtility.CalculateTransformPath(pivot, prefabRoot.transform);
				catalogEntry.animRotorPaths.Add(path);
				// glTF -> Unity mirrors X; a spin about local +Z by theta becomes -theta.
				var unityDegPerSecond = -sidecar.rotors[i].gltfDegPerSecondAboutLocalZ;
				var rest = pivot.localRotation;
				var curves = new[] { new AnimationCurve(), new AnimationCurve(), new AnimationCurve(), new AnimationCurve() };
				var prev = rest;
				for (var k = 0; k <= keys; k++)
				{
					var t = longest * k / keys;
					var q = rest * Quaternion.AngleAxis(unityDegPerSecond * t, Vector3.forward);
					if (Quaternion.Dot(prev, q) < 0f)
						q = new Quaternion(-q.x, -q.y, -q.z, -q.w);
					prev = q;
					curves[0].AddKey(new Keyframe(t, q.x));
					curves[1].AddKey(new Keyframe(t, q.y));
					curves[2].AddKey(new Keyframe(t, q.z));
					curves[3].AddKey(new Keyframe(t, q.w));
				}
				foreach (var curve in curves)
				{
					for (var k = 0; k < curve.length; k++)
					{
						AnimationUtility.SetKeyLeftTangentMode(curve, k, AnimationUtility.TangentMode.Linear);
						AnimationUtility.SetKeyRightTangentMode(curve, k, AnimationUtility.TangentMode.Linear);
					}
				}
				clip.SetCurve(path, typeof(Transform), "localRotation.x", curves[0]);
				clip.SetCurve(path, typeof(Transform), "localRotation.y", curves[1]);
				clip.SetCurve(path, typeof(Transform), "localRotation.z", curves[2]);
				clip.SetCurve(path, typeof(Transform), "localRotation.w", curves[3]);
			}
			clip.EnsureQuaternionContinuity();
			var settings = AnimationUtility.GetAnimationClipSettings(clip);
			settings.loopTime = true;
			settings.loopBlend = false;
			AnimationUtility.SetAnimationClipSettings(clip, settings);
			var clipPath = AssetRoot + "/" + safeKey + "_rotor_loop.anim";
			AssetDatabase.CreateAsset(clip, clipPath);
			var controllerPath = AssetRoot + "/" + safeKey + "_rotor.controller";
			var controller = AnimatorController.CreateAnimatorControllerAtPathWithClip(controllerPath, clip);
			if (controller == null)
				throw new InvalidOperationException(safeKey + ": AnimatorController creation failed.");
			// Unity fake-null: '??' does not see a missing component.
			var animator = prefabRoot.GetComponent<Animator>();
			if (animator == null)
				animator = prefabRoot.AddComponent<Animator>();
			animator.runtimeAnimatorController = controller;
			animator.applyRootMotion = false;
			animator.cullingMode = AnimatorCullingMode.CullUpdateTransforms;
			animator.updateMode = AnimatorUpdateMode.Normal;
		}

		/// <summary>
		/// One looping clip for all keyed parts. Each key: localRotation = rest * AngleAxis(-angle, Z)
		/// (glTF -> Unity mirrors X, as for rotors) and localPosition = restPos + restRot * Z * lift
		/// (the pivot's local Z in its parent's space; the mirror maps the glTF axis onto it).
		/// </summary>
		static void BakeKeyedParts(GameObject prefabRoot, AnimSidecarPart[] parts, string safeKey, CatalogEntryJson catalogEntry)
		{
			var all = prefabRoot.GetComponentsInChildren<Transform>(true);
			var found = new List<Transform>();
			foreach (var t in all)
				if (t.name.StartsWith(PartPivotPrefix, StringComparison.Ordinal) && t.name.EndsWith("_pivot", StringComparison.Ordinal))
					found.Add(t);
			if (found.Count != parts.Length)
				throw new InvalidOperationException(safeKey + ": sidecar lists " + parts.Length + " part(s) but model_anim.glb imported " + found.Count + " part pivot(s).");
			var loop = parts[0].loopSeconds;
			if (loop <= 0f)
				throw new InvalidOperationException(safeKey + ": part loopSeconds must be > 0.");
			var clip = new AnimationClip { name = safeKey + "_parts_loop", legacy = false, frameRate = 60f };
			for (var i = 0; i < parts.Length; i++)
			{
				var part = parts[i];
				if (Mathf.Abs(part.loopSeconds - loop) > 1e-4f)
					throw new InvalidOperationException(safeKey + ": part " + i + " loop " + part.loopSeconds + " != " + loop + "; parts share one clip.");
				var n = part.keyTimes != null ? part.keyTimes.Length : 0;
				if (n < 2 || part.angleDeg == null || part.angleDeg.Length != n || part.lift == null || part.lift.Length != n)
					throw new InvalidOperationException(safeKey + ": part " + i + " key arrays are missing or differ in length.");
				if (Mathf.Abs(part.keyTimes[0]) > 1e-4f || Mathf.Abs(part.keyTimes[n - 1] - loop) > 1e-3f)
					throw new InvalidOperationException(safeKey + ": part " + i + " keys must span exactly one loop.");
				Transform pivot = null;
				foreach (var t in found)
					if (t.name == part.name)
						pivot = t;
				if (pivot == null)
					throw new InvalidOperationException(safeKey + ": part pivot '" + part.name + "' missing from the imported model.");
				if (part.parent >= 0)
				{
					var parentName = parts[part.parent].name;
					if (pivot.parent == null || pivot.parent.name != parentName)
						throw new InvalidOperationException(safeKey + ": part '" + part.name + "' is not nested under '" + parentName + "'.");
				}
				var path = AnimationUtility.CalculateTransformPath(pivot, prefabRoot.transform);
				catalogEntry.animPartPaths.Add(path);
				var rest = pivot.localRotation;
				var restPos = pivot.localPosition;
				var hasLift = false;
				for (var k = 0; k < n; k++)
					if (Mathf.Abs(part.lift[k]) > 1e-7f)
						hasLift = true;
				var rc = new[] { new AnimationCurve(), new AnimationCurve(), new AnimationCurve(), new AnimationCurve() };
				var pc = new[] { new AnimationCurve(), new AnimationCurve(), new AnimationCurve() };
				var prev = rest;
				for (var k = 0; k < n; k++)
				{
					var t = part.keyTimes[k];
					var q = rest * Quaternion.AngleAxis(-part.angleDeg[k], Vector3.forward);
					if (Quaternion.Dot(prev, q) < 0f)
						q = new Quaternion(-q.x, -q.y, -q.z, -q.w);
					prev = q;
					rc[0].AddKey(new Keyframe(t, q.x));
					rc[1].AddKey(new Keyframe(t, q.y));
					rc[2].AddKey(new Keyframe(t, q.z));
					rc[3].AddKey(new Keyframe(t, q.w));
					var p = restPos + rest * Vector3.forward * part.lift[k];
					pc[0].AddKey(new Keyframe(t, p.x));
					pc[1].AddKey(new Keyframe(t, p.y));
					pc[2].AddKey(new Keyframe(t, p.z));
				}
				foreach (var curve in rc)
					SetLinear(curve);
				clip.SetCurve(path, typeof(Transform), "localRotation.x", rc[0]);
				clip.SetCurve(path, typeof(Transform), "localRotation.y", rc[1]);
				clip.SetCurve(path, typeof(Transform), "localRotation.z", rc[2]);
				clip.SetCurve(path, typeof(Transform), "localRotation.w", rc[3]);
				if (hasLift)
				{
					foreach (var curve in pc)
						SetLinear(curve);
					clip.SetCurve(path, typeof(Transform), "localPosition.x", pc[0]);
					clip.SetCurve(path, typeof(Transform), "localPosition.y", pc[1]);
					clip.SetCurve(path, typeof(Transform), "localPosition.z", pc[2]);
				}
			}
			clip.EnsureQuaternionContinuity();
			var settings = AnimationUtility.GetAnimationClipSettings(clip);
			settings.loopTime = true;
			settings.loopBlend = false;
			AnimationUtility.SetAnimationClipSettings(clip, settings);
			var clipPath = AssetRoot + "/" + safeKey + "_parts_loop.anim";
			AssetDatabase.CreateAsset(clip, clipPath);
			var controllerPath = AssetRoot + "/" + safeKey + "_parts.controller";
			var controller = AnimatorController.CreateAnimatorControllerAtPathWithClip(controllerPath, clip);
			if (controller == null)
				throw new InvalidOperationException(safeKey + ": AnimatorController creation failed.");
			// Unity fake-null: '??' does not see a missing component.
			var animator = prefabRoot.GetComponent<Animator>();
			if (animator == null)
				animator = prefabRoot.AddComponent<Animator>();
			animator.runtimeAnimatorController = controller;
			animator.applyRootMotion = false;
			animator.cullingMode = AnimatorCullingMode.CullUpdateTransforms;
			animator.updateMode = AnimatorUpdateMode.Normal;
		}

		static void SetLinear(AnimationCurve curve)
		{
			for (var k = 0; k < curve.length; k++)
			{
				AnimationUtility.SetKeyLeftTangentMode(curve, k, AnimationUtility.TangentMode.Linear);
				AnimationUtility.SetKeyRightTangentMode(curve, k, AnimationUtility.TangentMode.Linear);
			}
		}

		static void NormalizeToTargetHeight(Transform root, float targetHeight)
		{
			root.localPosition = Vector3.zero;
			root.localRotation = Quaternion.identity;
			root.localScale = Vector3.one;
			OrientUprightByMaxHeight(root);
			var renderers = root.GetComponentsInChildren<Renderer>(true);
			var bounds = renderers[0].bounds;
			for (var i = 1; i < renderers.Length; i++)
				bounds.Encapsulate(renderers[i].bounds);
			var height = bounds.size.y;
			if (height <= 0.0001f)
				throw new InvalidOperationException("Mesh bounds height is zero after upright orient.");
			root.localScale = Vector3.one * (targetHeight / height);
			// Seat the children in the pose the game renders, not the tipped one. The runtime
			// (Homm3MapBuildingMeshBundle.OrientToBillboardArtAndSeat) keeps this tip only as the input to its
			// flat test and then replaces the root rotation with a yaw on the glTF +Y up axis. A bottom
			// centre measured in the tipped pose is a side face's centre in model space, so every tipped
			// multi-node prefab (model_anim.glb: body + pivots/anchors) slid half its footprint off the
			// donor's centre once the tip was gone (Factory city 1.8 world units, playtest 2026-09-29).
			// Single-node models have no children and keep their Meshy bbox-centred origin either way.
			// validate_map_building_mesh_contract.py measures this on the staged bundle.
			var tipped = root.localRotation;
			root.localRotation = Quaternion.identity;
			renderers = root.GetComponentsInChildren<Renderer>(true);
			bounds = renderers[0].bounds;
			for (var i = 1; i < renderers.Length; i++)
				bounds.Encapsulate(renderers[i].bounds);
			var worldBottomCenter = new Vector3(bounds.center.x, bounds.min.y, bounds.center.z);
			var localBottomCenter = root.InverseTransformPoint(worldBottomCenter);
			foreach (Transform child in root)
				child.localPosition -= localBottomCenter;
			root.localRotation = tipped;
		}

		static void OrientUprightByMaxHeight(Transform root)
		{
			var candidates = new[]
			{
				Quaternion.identity,
				Quaternion.Euler(-90f, 0f, 0f),
				Quaternion.Euler(90f, 0f, 0f),
				Quaternion.Euler(0f, 0f, -90f),
				Quaternion.Euler(0f, 0f, 90f)
			};
			var renderers = root.GetComponentsInChildren<Renderer>(true);
			var best = Quaternion.identity;
			var bestHeight = -1f;
			foreach (var rot in candidates)
			{
				root.localRotation = rot;
				var bounds = renderers[0].bounds;
				for (var i = 1; i < renderers.Length; i++)
					bounds.Encapsulate(renderers[i].bounds);
				if (bounds.size.y > bestHeight)
				{
					bestHeight = bounds.size.y;
					best = rot;
				}
			}
			root.localRotation = best;
		}

		static Material CreateAuthoredMaterial(
			string name,
			Texture2D albedo,
			Texture2D normal,
			Texture2D metallic,
			Texture2D roughness)
		{
			if (albedo == null)
				throw new InvalidOperationException("Missing albedo for " + name);
			var shader = Shader.Find("Universal Render Pipeline/Lit")
			             ?? Shader.Find("HDRP/Lit")
			             ?? Shader.Find("Standard");
			if (shader == null)
				throw new InvalidOperationException("No Lit/Standard shader for map building mesh material.");
			var mat = new Material(shader) { name = name };
			if (mat.HasProperty("_BaseMap"))
				mat.SetTexture("_BaseMap", albedo);
			if (mat.HasProperty("_MainTex"))
				mat.SetTexture("_MainTex", albedo);
			mat.mainTexture = albedo;
			if (normal != null)
			{
				if (mat.HasProperty("_BumpMap"))
					mat.SetTexture("_BumpMap", normal);
				if (mat.HasProperty("_NormalMap"))
					mat.SetTexture("_NormalMap", normal);
				mat.EnableKeyword("_NORMALMAP");
			}
			if (metallic != null && mat.HasProperty("_MetallicGlossMap"))
			{
				mat.SetTexture("_MetallicGlossMap", metallic);
				mat.EnableKeyword("_METALLICGLOSSMAP");
			}
			if (mat.HasProperty("_Smoothness"))
				mat.SetFloat("_Smoothness", 0.35f);
			else if (mat.HasProperty("_Glossiness"))
				mat.SetFloat("_Glossiness", 0.35f);
			return mat;
		}

		static void ConfigureModel(string assetPath)
		{
			// .glb/.gltf use GLTFast ScriptedImporter — not ModelImporter.
			if (assetPath.EndsWith(".glb", StringComparison.OrdinalIgnoreCase)
			    || assetPath.EndsWith(".gltf", StringComparison.OrdinalIgnoreCase))
			{
				AssetDatabase.ImportAsset(assetPath, ImportAssetOptions.ForceUpdate);
				return;
			}
			var importer = AssetImporter.GetAtPath(assetPath) as ModelImporter;
			if (importer == null)
				throw new InvalidOperationException("Missing ModelImporter for " + assetPath);
			importer.meshCompression = ModelImporterMeshCompression.Off;
			importer.isReadable = false;
			importer.materialImportMode = ModelImporterMaterialImportMode.None;
			importer.animationType = ModelImporterAnimationType.None;
			importer.importAnimation = false;
			importer.SaveAndReimport();
		}

		static void ConfigureTexture(string assetPath, bool sRGB, bool normalMap)
		{
			var importer = AssetImporter.GetAtPath(assetPath) as TextureImporter;
			if (importer == null)
				throw new InvalidOperationException("Missing TextureImporter for " + assetPath);
			var type = normalMap ? TextureImporterType.NormalMap : TextureImporterType.Default;
			if (importer.textureType == type && importer.sRGBTexture == sRGB && importer.mipmapEnabled
			    && importer.maxTextureSize == 2048 && importer.textureCompression == TextureImporterCompression.Compressed
			    && importer.filterMode == FilterMode.Bilinear && importer.wrapMode == TextureWrapMode.Repeat)
				return;
			importer.textureType = type;
			importer.sRGBTexture = sRGB;
			importer.mipmapEnabled = true;
			importer.maxTextureSize = 2048;
			importer.textureCompression = TextureImporterCompression.Compressed;
			importer.filterMode = FilterMode.Bilinear;
			importer.wrapMode = TextureWrapMode.Repeat;
			importer.SaveAndReimport();
		}

		static void CopyAsset(string sourceAbsolute, string destRelative)
		{
			var destAbsolute = Path.GetFullPath(destRelative);
			Directory.CreateDirectory(Path.GetDirectoryName(destAbsolute) ?? ".");
			File.Copy(sourceAbsolute, destAbsolute, overwrite: true);
		}

		/// <summary>Copy a source into the project only when its bytes differ; records the staged path.</summary>
		static void StageAsset(string sourceAbsolute, string destRelative, HashSet<string> produced, List<string> changed)
		{
			produced.Add(destRelative);
			var destAbsolute = Path.GetFullPath(destRelative);
			if (File.Exists(destAbsolute) && SameBytes(sourceAbsolute, destAbsolute))
				return;
			CopyAsset(sourceAbsolute, destRelative);
			changed.Add(destRelative);
		}

		static bool SameBytes(string a, string b)
		{
			var fa = new FileInfo(a);
			var fb = new FileInfo(b);
			if (fa.Length != fb.Length)
				return false;
			const int Chunk = 1 << 20;
			var ba = new byte[Chunk];
			var bb = new byte[Chunk];
			using (var sa = File.OpenRead(a))
			using (var sb = File.OpenRead(b))
			{
				while (true)
				{
					var na = sa.Read(ba, 0, Chunk);
					var nb = sb.Read(bb, 0, Chunk);
					if (na != nb)
						return false;
					if (na == 0)
						return true;
					for (var i = 0; i < na; i++)
					{
						if (ba[i] != bb[i])
							return false;
					}
				}
			}
		}

		/// <summary>Delete (with its .meta) every file under AssetRoot this run did not produce, so nothing stale ships.</summary>
		static void RemoveAssetsOutsideOutputSet(HashSet<string> produced)
		{
			var absoluteRoot = Path.GetFullPath(AssetRoot);
			var keep = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
			foreach (var rel in produced)
				keep.Add(Path.GetFullPath(rel));
			var removed = 0;
			foreach (var file in Directory.GetFiles(absoluteRoot, "*", SearchOption.AllDirectories))
			{
				if (file.EndsWith(".meta", StringComparison.OrdinalIgnoreCase) || keep.Contains(Path.GetFullPath(file)))
					continue;
				File.Delete(file);
				var meta = file + ".meta";
				if (File.Exists(meta))
					File.Delete(meta);
				removed++;
				Debug.Log("Homm3MapBuildingMeshesBundleBuild: removed stale " + Path.GetFileName(file));
			}
			foreach (var meta in Directory.GetFiles(absoluteRoot, "*.meta", SearchOption.AllDirectories))
			{
				var owner = meta.Substring(0, meta.Length - ".meta".Length);
				if (!File.Exists(owner) && !Directory.Exists(owner))
					File.Delete(meta);
			}
			AssetDatabase.Refresh();
			Debug.Log("Homm3MapBuildingMeshesBundleBuild: output set " + produced.Count + " file(s), removed " + removed + " stale.");
		}

		static void CheckFreeSpace(double minFreeGb, string where)
		{
			var root = Path.GetPathRoot(Path.GetFullPath(AssetRoot));
			var freeGb = new DriveInfo(root).AvailableFreeSpace / 1e9;
			if (freeGb < minFreeGb)
				throw new InvalidOperationException(
					"Homm3MapBuildingMeshesBundleBuild: " + root + " has " + freeGb.ToString("0.0", CultureInfo.InvariantCulture)
					+ " GB free, below -minFreeGb " + minFreeGb.ToString("0.0", CultureInfo.InvariantCulture) + "; stopped cleanly " + where + ".");
		}

		static void WriteAssetManifest(string absoluteOutput, List<string> prefabPaths)
		{
			var assets = new List<string>();
			foreach (var p in prefabPaths)
				assets.Add(Path.GetFileNameWithoutExtension(p));
			var assetManifest = new AssetManifest
			{
				schema = ManifestSchema,
				bundle = BundleName,
				assetCount = assets.Count,
				assets = assets
			};
			File.WriteAllText(
				Path.Combine(absoluteOutput, BundleName + ".asset_manifest.json"),
				JsonUtility.ToJson(assetManifest, true));
		}

		static void WriteCatalog(string absoluteOutput, List<CatalogEntryJson> entries)
		{
			var catalog = new CatalogFile
			{
				schema = CatalogSchema,
				bundle = BundleName,
				entryCount = entries.Count,
				entries = entries
			};
			File.WriteAllText(
				Path.Combine(absoluteOutput, "catalog.json"),
				JsonUtility.ToJson(catalog, true));
		}

		static void EnsureFolder(string assetFolder)
		{
			if (AssetDatabase.IsValidFolder(assetFolder))
				return;
			var parts = assetFolder.Split('/');
			var current = parts[0];
			for (var i = 1; i < parts.Length; i++)
			{
				var next = current + "/" + parts[i];
				if (!AssetDatabase.IsValidFolder(next))
					AssetDatabase.CreateFolder(current, parts[i]);
				current = next;
			}
		}

		static string ResolveArg(string name, string fallback)
		{
			var args = UnityQueueArgs();
			for (var i = 0; i + 1 < args.Length; i++)
			{
				if (string.Equals(args[i], name, StringComparison.OrdinalIgnoreCase))
					return args[i + 1];
			}
			return fallback;
		}
	}
}
