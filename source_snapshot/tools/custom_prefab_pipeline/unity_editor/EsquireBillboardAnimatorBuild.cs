// Canonical copy for git. Deploy to: <UnityProject>/Assets/Editor/EsquireBillboardAnimatorBuild.cs
// (kept in sync with C:\Users\<user>\oldenera_factions when you edit either copy)

// Builds flip-book AnimationClips + AnimatorOverrideController for Esquire battle billboard (MeshRenderer quad).
// Map: separate adventure/map DEF folder → looping MeshRenderer material flip-book + minimal AnimatorController (not stock battle controller).
// Requires stock AnimatorController at ReferenceControllerPath (AssetStudio export) for battle parity only.
// Menu: Olden Era / Custom Units / Rebuild Esquire Battle Billboard Animator
// Batch: -executeMethod OldenEra.CustomUnitBuilder.EsquireBillboardAnimatorBuild.RebuildFromBatch

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

namespace OldenEra.CustomUnitBuilder
{
	public static class EsquireBillboardAnimatorBuild
	{
		/// <summary>Root JSON object written by <c>tools/defextract_py3.py</c> next to <c>*.dir/</c>.</summary>
		[Serializable]
		class DefExtractManifest
		{
			public DefExtractSequence[] sequences;
			public int type;
			public int format;
		}

		[Serializable]
		class DefExtractSequence
		{
			public int group;
			public string[] frames;
		}

		const string FramesFolder = "Assets/CustomUnits/esquire/extracted_avwpike/avwpike.dir";
		const string TemplateMaterialPath = "Assets/CustomUnits/esquire/battle_billboard_mesh.mat";
		const string BattlePrefabPath = "Assets/CustomUnits/esquire/battle.prefab";
		const string MapPrefabPath = "Assets/CustomUnits/esquire/map.prefab";
		/// <summary>
		/// Adventure / world-map creature DEF extract (e.g. VCMI group 0 movement from <c>AvWPike.def</c>), <b>not</b> the battle <c>PIKEMAN.DEF</c> tree.
		/// If this folder is missing, the builder falls back to <see cref="FramesFolder"/> and logs a warning (wrong art for map-only parity).
		/// </summary>
		const string MapFramesFolder = "Assets/CustomUnits/esquire/extracted_map/avwpike.dir";
		const string MapGeneratedRoot = "Assets/CustomUnits/esquire/Generated/MapBillboard";
		const string MapAnimatorControllerPath = "Assets/CustomUnits/esquire/Generated/MapBillboard/EsquireMapBillboard.controller";
		/// <summary>Looping map billboard clip (idle-first frames; see <see cref="RebuildMapMeshBillboard"/>).</summary>
		const string MapWalkClipName = "MapIdle";
		const float MapFlipBookFps = 10f;
		const string GeneratedRoot = "Assets/CustomUnits/esquire/Generated/BillboardAnim";
		const string MaterialsRel = "Materials";
		const string ClipsRel = "Clips";
		/// <summary>Exported from AssetStudio (game). See Reference/README.txt.</summary>
		const string ReferenceControllerPath = "Assets/CustomUnits/esquire/Reference/StockEsquireBattle.controller";
		const string OverrideOutputPath = "Assets/CustomUnits/esquire/Generated/BillboardAnim/EsquireBattleBillboard.overrideController";
		/// <summary>Removed on rebuild if present (pre-override flat controller).</summary>
		const string LegacyFlatControllerPath = "Assets/CustomUnits/esquire/Generated/BillboardAnim/EsquireBattleBillboard.controller";
		const string QuadRendererPath = "billboard/quad";
		const float FlipBookFps = 12f;
		const float DeathClipFps = 10f;

		/// <summary>
		/// Reference values for <c>billboard/quad</c>. Menu <b>Apply Battle Quad Defaults</b> writes them anytime.
		/// <see cref="RebuildFromBatch"/> also applies them so <c>build_esquire_bundle.cmd</c> picks up changes without opening the editor.
		/// Menu <b>Rebuild Esquire Battle Billboard Animator</b> does <b>not</b> touch the quad (manual tuning preserved).
		/// </summary>
		const float BattleQuadLocalScaleX = 16f;
		const float BattleQuadLocalScaleY = 16f;
		const float BattleQuadLocalScaleZ = 1f;

		/// <summary>
		/// Quad <c>localPosition.x</c> (positive usually shifts the mesh toward +X in <c>billboard</c> space — tune if HoMM frames sit off-center).
		/// </summary>
		const float BattleQuadLocalPositionX = 1.15f;

		/// <summary>
		/// Quad <c>localPosition.y</c> for the centered 1×1 quad mesh. We do <b>not</b> auto-set <c>y = scaleY/2</c>: battle uses world-axis renderer bounds for optional foot alignment,
		/// and large billboards + AABB min-<c>Y</c> interact badly with that, which read as “floating higher” when <c>y</c> was tied to scale.
		/// </summary>
		const float BattleQuadLocalPositionY = 2.68f;

		/// <summary>Optional add-on to <see cref="BattleQuadLocalPositionY"/> for fine-tuning after rebuild.</summary>
		const float BattleQuadLocalPositionExtraY = 0f;

		/// <summary>Adventure map quad — tune separately from battle (world map scale / framing).</summary>
		const float MapQuadLocalScaleX = 16f;

		const float MapQuadLocalScaleY = 16f;
		const float MapQuadLocalScaleZ = 1f;
		const float MapQuadLocalPositionX = 1.45f;
		const float MapQuadLocalPositionY = 2.45f;

		// HoMM3 / VCMI creature DEF group ids — https://vcmi.eu/modders/Animation_Format/
		const int GroupMovement = 0;
		const int GroupIdle = 2;
		const int GroupHitted = 3;
		const int GroupDeath = 5;
		const int GroupAttackUp = 11;
		const int GroupAttackFront = 12;
		const int GroupAttackDown = 13;

		/// <summary>
		/// AnimationClip.name must match motions in Reference StockEsquireBattle.controller.
		/// Rip uses shared <c>_Battle_Unit_Anim_ctrl_v2</c> etalon clips (see <c>units/_system/etalon/*.anim</c> in AssetRipper export).
		/// </summary>
		static readonly string[] GeneratedClipNames =
		{
			"22.Idle",
			"01.Walk",
			"14.Attack",
			"20.Damage",
			"21.Death"
		};

		static bool s_applyBattleQuadDefaultsThisRun;

		[MenuItem("Olden Era/Custom Units/Rebuild Esquire Battle Billboard Animator")]
		public static void RebuildMenu() => Rebuild();

		[MenuItem("Olden Era/Custom Units/Rebuild Esquire Map Mesh Billboard")]
		public static void RebuildMapMenu()
		{
			try
			{
				RebuildMapMeshBillboard();
				AssetDatabase.SaveAssets();
				AssetDatabase.Refresh();
				Debug.Log("EsquireBillboardAnimatorBuild: map mesh billboard completed.");
			}
			catch (Exception ex)
			{
				Debug.LogError("EsquireBillboardAnimatorBuild map rebuild failed: " + ex);
			}
		}

		[MenuItem("Olden Era/Custom Units/Apply Battle Quad Defaults (from constants)")]
		public static void ApplyQuadDefaultsMenu()
		{
			var battle = AssetDatabase.LoadAssetAtPath<GameObject>(BattlePrefabPath);
			if (battle == null)
			{
				Debug.LogError("EsquireBillboardAnimatorBuild: missing " + BattlePrefabPath);
				return;
			}

			ApplyBattleQuadAuthoringDefaults(battle);
			EditorUtility.SetDirty(battle);
			PrefabUtility.SavePrefabAsset(battle);
			AssetDatabase.SaveAssets();
			var p = ComputeBattleQuadLocalPosition();
			Debug.Log(
				"EsquireBillboardAnimatorBuild: wrote quad defaults localScale=("
				+ BattleQuadLocalScaleX
				+ ","
				+ BattleQuadLocalScaleY
				+ ","
				+ BattleQuadLocalScaleZ
				+ ") localPos=("
				+ p.x
				+ ","
				+ p.y
				+ ","
				+ p.z
				+ ") to "
				+ BattlePrefabPath);
		}

		public static void RebuildFromBatch()
		{
			try
			{
				s_applyBattleQuadDefaultsThisRun = true;
				Rebuild();
				Debug.Log("EsquireBillboardAnimatorBuild: completed.");
			}
			catch (Exception ex)
			{
				Debug.LogError("EsquireBillboardAnimatorBuild failed: " + ex);
				EditorApplication.Exit(1);
				throw;
			}
			finally
			{
				s_applyBattleQuadDefaultsThisRun = false;
			}
		}

		static void Rebuild()
		{
			if (!AssetDatabase.IsValidFolder(FramesFolder))
				throw new InvalidOperationException("Frames folder missing: " + FramesFolder);
			ApplyBattleFramePngImportSettings();
			AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
			var template = AssetDatabase.LoadAssetAtPath<Material>(TemplateMaterialPath);
			if (template == null)
				throw new InvalidOperationException("Template material missing: " + TemplateMaterialPath);

			var baseController = AssetDatabase.LoadAssetAtPath<AnimatorController>(ReferenceControllerPath);
			if (baseController == null)
				throw new InvalidOperationException(
					"Missing stock AnimatorController for GUI parity. Export from AssetStudio to:\n  "
					+ ReferenceControllerPath
					+ "\nSee Assets/CustomUnits/esquire/Reference/README.txt or tools/custom_prefab_pipeline/unity_editor/StockEsquireBattle_IMPORT.txt");

			EnsureFolder("Assets/CustomUnits/esquire/Generated");
			EnsureFolder(GeneratedRoot);
			EnsureFolder($"{GeneratedRoot}/{MaterialsRel}");
			EnsureFolder($"{GeneratedRoot}/{ClipsRel}");

			ClearSubfolders($"{GeneratedRoot}/{MaterialsRel}", $"{GeneratedRoot}/{ClipsRel}");
			if (AssetDatabase.LoadAssetAtPath<AnimatorOverrideController>(OverrideOutputPath))
				AssetDatabase.DeleteAsset(OverrideOutputPath);
			if (AssetDatabase.LoadAssetAtPath<AnimatorController>(LegacyFlatControllerPath))
				AssetDatabase.DeleteAsset(LegacyFlatControllerPath);

			AnimationClip idleClip, moveClip, attackClip, hitClip, deathClip;

			DefExtractManifest manifest = null;
			string manifestJsonPath = null;
			var manifestGroupSummary = "";
			var haveDefExtractJson = TryLoadDefExtractManifest(out manifest, out manifestJsonPath);
			var useDefExtractGroups = haveDefExtractJson && ManifestCoversBattleClips(manifest, out manifestGroupSummary);

			if (useDefExtractGroups)
			{
				var matCache = new Dictionary<string, Material>(StringComparer.OrdinalIgnoreCase);
				var matCounter = 0;
				var logGroups = new StringBuilder();
				logGroups.Append("EsquireBillboardAnimatorBuild: using defextract manifest ").Append(manifestJsonPath).AppendLine();

				idleClip = BuildClipFromManifestGroup(
					"22.Idle", manifest, GroupIdle, FlipBookFps, loop: true, template, ref matCounter, matCache, logGroups);
				moveClip = BuildClipFromManifestGroup(
					"01.Walk", manifest, GroupMovement, FlipBookFps, loop: true, template, ref matCounter, matCache, logGroups);
				attackClip = BuildClipFromManifestAttack(
					"14.Attack", manifest, FlipBookFps, template, ref matCounter, matCache, logGroups);
				hitClip = BuildClipFromManifestGroup(
					"20.Damage", manifest, GroupHitted, FlipBookFps, loop: false, template, ref matCounter, matCache, logGroups);
				deathClip = BuildClipFromManifestGroup(
					"21.Death", manifest, GroupDeath, DeathClipFps, loop: false, template, ref matCounter, matCache, logGroups);

				Debug.Log(logGroups.ToString().TrimEnd());
				AssetDatabase.SaveAssets();
			}
			else
			{
				if (haveDefExtractJson)
				{
					Debug.LogWarning(
						"EsquireBillboardAnimatorBuild: defextract JSON found at "
						+ manifestJsonPath
						+ " but it does not include all battle groups (need idle=2, movement=0, hitted=3, death=5, "
						+ "and at least one of attack "
						+ GroupAttackUp
						+ "/"
						+ GroupAttackFront
						+ "/"
						+ GroupAttackDown
						+ " with frames). Groups present in file: "
						+ manifestGroupSummary
						+ ". This often means the source was an adventure-map .def (e.g. AvWPike.def) rather than "
						+ "the battle creature DEF. Re-extract from PIKEMAN.DEF (or your mod’s battle equivalent). "
						+ "Falling back to legacy flat-folder slices.");
				}
				else
				{
					Debug.LogWarning(
						"EsquireBillboardAnimatorBuild: no defextract JSON beside frames folder (expected "
						+ GuessDefExtractJsonAssetPath()
						+ "). Run tools/defextract_py3.py on the battle .def; falling back to legacy flat-folder slices.");
				}

				var textures = LoadOrderedFrameTextures();
				if (textures.Count == 0)
					throw new InvalidOperationException("No PNG frames under " + FramesFolder);

				var materials = BuildFrameMaterials(template, textures);
				var matArray = materials.ToArray();

				idleClip = BuildMaterialSwapClip("22.Idle", matArray, 0, matArray.Length, FlipBookFps, loop: true);
				moveClip = BuildMaterialSwapClip("01.Walk", matArray, 0, matArray.Length, FlipBookFps, loop: true);
				var attackLen = Mathf.Min(11, matArray.Length);
				attackClip = BuildMaterialSwapClip("14.Attack", matArray, 0, attackLen, FlipBookFps, loop: false);
				var hitLen = Mathf.Min(4, matArray.Length);
				var hitStart = Mathf.Clamp(matArray.Length / 2 - hitLen / 2, 0, Mathf.Max(0, matArray.Length - hitLen));
				hitClip = BuildMaterialSwapClip("20.Damage", matArray, hitStart, hitLen, FlipBookFps, loop: false);
				var deathLen = Mathf.Min(10, matArray.Length);
				var deathStart = Mathf.Max(0, matArray.Length - deathLen);
				deathClip = BuildMaterialSwapClip("21.Death", matArray, deathStart, deathLen, DeathClipFps, loop: false);
			}

			SaveClip(idleClip);
			SaveClip(moveClip);
			SaveClip(attackClip);
			SaveClip(hitClip);
			SaveClip(deathClip);

			AssetDatabase.SaveAssets();
			AssetDatabase.Refresh();

			var generatedByName = new Dictionary<string, AnimationClip>(StringComparer.Ordinal);
			foreach (var clipName in GeneratedClipNames)
			{
				var clipPath = $"{GeneratedRoot}/{ClipsRel}/{clipName}.anim";
				var c = AssetDatabase.LoadAssetAtPath<AnimationClip>(clipPath);
				if (c != null)
					generatedByName[clipName] = c;
				else
					Debug.LogWarning("EsquireBillboardAnimatorBuild: expected generated clip missing: " + clipPath);
			}

			// Create empty asset first, then assign base so serialization keeps runtimeAnimatorController
			// (new AnimatorOverrideController(base) + CreateAsset can yield GetOverrides with null keys on some Unity versions).
			var overrideController = new AnimatorOverrideController();
			AssetDatabase.CreateAsset(overrideController, OverrideOutputPath);
			overrideController.runtimeAnimatorController = baseController;
			EditorUtility.SetDirty(overrideController);
			AssetDatabase.SaveAssets();
			var overrides = new List<KeyValuePair<AnimationClip, AnimationClip>>();
			overrideController.GetOverrides(overrides);
			var warnedMissing = new HashSet<string>(StringComparer.Ordinal);
			var replaced = 0;
			for (var i = 0; i < overrides.Count; i++)
			{
				var orig = overrides[i].Key;
				if (orig == null)
					continue;
				if (!generatedByName.TryGetValue(orig.name, out var replacement))
				{
					if (warnedMissing.Add(orig.name))
						Debug.LogWarning(
							"EsquireBillboardAnimatorBuild: no flip-book clip named '"
							+ orig.name
							+ "' - stock motion kept (extend GeneratedClipNames / builder if needed).");
					continue;
				}

				overrides[i] = new KeyValuePair<AnimationClip, AnimationClip>(orig, replacement);
				replaced++;
			}

			overrideController.ApplyOverrides(overrides);
			EditorUtility.SetDirty(overrideController);
			AssetDatabase.SaveAssets();

			Debug.Log(
				"EsquireBillboardAnimatorBuild: AnimatorOverrideController applied "
				+ replaced
				+ " clip override(s) from "
				+ generatedByName.Count
				+ " generated flip-book clip(s).");

			var battle = AssetDatabase.LoadAssetAtPath<GameObject>(BattlePrefabPath);
			if (battle == null)
				throw new InvalidOperationException("battle.prefab missing: " + BattlePrefabPath);
			if (s_applyBattleQuadDefaultsThisRun)
			{
				ApplyBattleQuadAuthoringDefaults(battle);
				var p = ComputeBattleQuadLocalPosition();
				Debug.Log(
					"EsquireBillboardAnimatorBuild: applied battle quad defaults (batch) localScale=("
					+ BattleQuadLocalScaleX
					+ ","
					+ BattleQuadLocalScaleY
					+ ","
					+ BattleQuadLocalScaleZ
					+ ") localPos=("
					+ p.x
					+ ","
					+ p.y
					+ ","
					+ p.z
					+ ")");
			}

			var animator = battle.GetComponent<Animator>();
			if (animator == null)
				throw new InvalidOperationException("Animator missing on battle.prefab root.");
			var finalOverride = AssetDatabase.LoadAssetAtPath<AnimatorOverrideController>(OverrideOutputPath);
			if (finalOverride == null)
				throw new InvalidOperationException("Failed to load override controller at " + OverrideOutputPath);
			animator.runtimeAnimatorController = finalOverride;
			animator.applyRootMotion = false;
			EditorUtility.SetDirty(battle);
			PrefabUtility.SavePrefabAsset(battle);

			RebuildMapMeshBillboard();

			AssetDatabase.SaveAssets();
			AssetDatabase.Refresh();
		}

		/// <summary>
		/// (Re)author <c>map.prefab</c> as <c>billboard/quad</c> + <see cref="MeshRenderer"/> flip-book + minimal <see cref="Animator"/>.
		/// Uses <see cref="MapFramesFolder"/> (adventure-map DEF extract); falls back to battle <see cref="FramesFolder"/> if missing.
		/// Prefers DEF <b>idle</b> (group 2) so the map does not play the battle <b>walk</b> cycle; only uses movement (group 0) if idle is absent.
		/// </summary>
		public static void RebuildMapMeshBillboard()
		{
			var framesRoot = ResolveMapFramesFolder();
			ApplyFolderPngMeshBillboardImport(framesRoot);
			AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);

			var template = AssetDatabase.LoadAssetAtPath<Material>(TemplateMaterialPath);
			if (template == null)
				throw new InvalidOperationException("Template material missing: " + TemplateMaterialPath);

			EnsureFolder("Assets/CustomUnits/esquire/Generated");
			EnsureFolder(MapGeneratedRoot);
			EnsureFolder($"{MapGeneratedRoot}/{MaterialsRel}");
			EnsureFolder($"{MapGeneratedRoot}/{ClipsRel}");

			ClearSubfolders($"{MapGeneratedRoot}/{MaterialsRel}", $"{MapGeneratedRoot}/{ClipsRel}");
			if (AssetDatabase.LoadAssetAtPath<AnimatorController>(MapAnimatorControllerPath))
				AssetDatabase.DeleteAsset(MapAnimatorControllerPath);
			AssetDatabase.SaveAssets();

			List<Material> mapMats = null;
			if (TryLoadDefExtractManifestForFolder(framesRoot, out var manifest, out var jsonPath))
			{
				var rel = GetRelativeFramePathsForGroup(manifest, GroupIdle);
				if (rel.Count == 0)
					rel = GetRelativeFramePathsForGroup(manifest, GroupMovement);
				if (rel.Count > 0)
				{
					var matCache = new Dictionary<string, Material>(StringComparer.OrdinalIgnoreCase);
					var c = 0;
					mapMats = MaterialsForRelativeFramePathsMap(template, rel, framesRoot, ref c, matCache);
					Debug.Log(
						"EsquireBillboardAnimatorBuild: map flip-book from defextract "
						+ jsonPath
						+ " ("
						+ rel.Count
						+ " frames); DEF groups: "
						+ SummarizeManifestGroups(manifest));
				}
			}

			if (mapMats == null || mapMats.Count == 0)
			{
				var textures = LoadOrderedTexturesFromFolder(framesRoot);
				if (textures.Count == 0)
					throw new InvalidOperationException("No PNG textures under " + framesRoot + " for map billboard.");
				mapMats = BuildMapMaterialsFromTextures(template, textures);
				Debug.LogWarning(
					"EsquireBillboardAnimatorBuild: map used flat PNG order ("
					+ textures.Count
					+ " frames). Prefer defextract JSON + "
					+ MapFramesFolder
					+ " from the adventure-map .def (not the battle DEF).");
			}

			var clip = BuildMaterialSwapClipSequential(MapWalkClipName, mapMats, MapFlipBookFps, loop: true);
			var clipPath = $"{MapGeneratedRoot}/{ClipsRel}/{MapWalkClipName}.anim";
			AssetDatabase.CreateAsset(clip, clipPath);
			AssetDatabase.SaveAssets();
			var clipAsset = AssetDatabase.LoadAssetAtPath<AnimationClip>(clipPath);
			if (clipAsset == null)
				throw new InvalidOperationException("Failed to load saved map clip at " + clipPath);
			var animatorController = CreateOrReplaceMapAnimatorController(clipAsset);
			AssetDatabase.SaveAssets();

			var quadMaterial = mapMats[0];
			var existingAsset = AssetDatabase.LoadAssetAtPath<GameObject>(MapPrefabPath);
			if (existingAsset != null)
			{
				var mapRoot = PrefabUtility.LoadPrefabContents(MapPrefabPath);
				try
				{
					EnsureMapPrefabBillboardStructure(mapRoot, quadMaterial);
					WireMapAnimator(mapRoot, animatorController);
					PrefabUtility.SaveAsPrefabAsset(mapRoot, MapPrefabPath);
				}
				finally
				{
					PrefabUtility.UnloadPrefabContents(mapRoot);
				}
			}
			else
			{
				var mapRoot = new GameObject("map");
				try
				{
					EnsureMapPrefabBillboardStructure(mapRoot, quadMaterial);
					WireMapAnimator(mapRoot, animatorController);
					PrefabUtility.SaveAsPrefabAsset(mapRoot, MapPrefabPath);
				}
				finally
				{
					UnityEngine.Object.DestroyImmediate(mapRoot);
				}
			}

			AssetDatabase.SaveAssets();
			Debug.Log(
				"EsquireBillboardAnimatorBuild: map prefab → "
				+ MapPrefabPath
				+ " ("
				+ mapMats.Count
				+ " frame materials, controller "
				+ MapAnimatorControllerPath
				+ ").");
		}

		static string ResolveMapFramesFolder()
		{
			if (AssetDatabase.IsValidFolder(MapFramesFolder))
				return MapFramesFolder;
			Debug.LogWarning(
				"EsquireBillboardAnimatorBuild: MapFramesFolder missing ("
				+ MapFramesFolder
				+ "). Using battle FramesFolder for map — extract the adventure-map creature DEF to MapFramesFolder for correct map art.");
			if (!AssetDatabase.IsValidFolder(FramesFolder))
				throw new InvalidOperationException("Map frames missing and battle FramesFolder invalid: " + FramesFolder);
			return FramesFolder;
		}

		static List<Material> MaterialsForRelativeFramePathsMap(
			Material template,
			List<string> relativePaths,
			string framesDir,
			ref int matCounter,
			Dictionary<string, Material> matCache)
		{
			var parent = Path.GetDirectoryName(framesDir.Replace('\\', '/').TrimEnd('/'))?.Replace('\\', '/');
			if (string.IsNullOrEmpty(parent))
				throw new InvalidOperationException("Invalid map frames folder: " + framesDir);

			var list = new List<Material>(relativePaths.Count);
			foreach (var rel in relativePaths)
			{
				var assetPath = $"{parent}/{rel}";
				if (!matCache.TryGetValue(assetPath, out var mat))
				{
					var tex = FirstTexture2DAtPath(assetPath);
					if (tex == null)
						throw new InvalidOperationException(
							"EsquireBillboardAnimatorBuild: missing texture for map defextract frame: " + assetPath);
					mat = new Material(template);
					mat.name = $"map_frame_{matCounter:000}";
					mat.SetTexture("_MainTex", tex);
					var matPath = $"{MapGeneratedRoot}/{MaterialsRel}/map_frame_{matCounter:000}.mat";
					matCounter++;
					AssetDatabase.CreateAsset(mat, matPath);
					matCache[assetPath] = mat;
				}

				list.Add(mat);
			}

			return list;
		}

		static List<Texture2D> LoadOrderedTexturesFromFolder(string folder)
		{
			var list = new List<(string path, Texture2D tex)>();
			foreach (var guid in AssetDatabase.FindAssets("", new[] { folder }))
			{
				var path = AssetDatabase.GUIDToAssetPath(guid);
				if (!path.EndsWith(".png", StringComparison.OrdinalIgnoreCase))
					continue;
				var tex = FirstTexture2DAtPath(path);
				if (tex != null)
					list.Add((path, tex));
			}

			return list
				.OrderBy(x => x.path, StringComparer.OrdinalIgnoreCase)
				.Select(x => x.tex)
				.ToList();
		}

		static List<Material> BuildMapMaterialsFromTextures(Material template, List<Texture2D> textures)
		{
			var list = new List<Material>(textures.Count);
			for (var i = 0; i < textures.Count; i++)
			{
				var mat = new Material(template);
				mat.name = $"map_frame_{i:000}";
				mat.SetTexture("_MainTex", textures[i]);
				var path = $"{MapGeneratedRoot}/{MaterialsRel}/map_frame_{i:000}.mat";
				AssetDatabase.CreateAsset(mat, path);
				list.Add(mat);
			}

			AssetDatabase.SaveAssets();
			return list;
		}

		static AnimatorController CreateOrReplaceMapAnimatorController(AnimationClip walkClip)
		{
			if (walkClip == null)
				throw new ArgumentNullException(nameof(walkClip));
			var controller = AnimatorController.CreateAnimatorControllerAtPath(MapAnimatorControllerPath);
			var rootStateMachine = controller.layers[0].stateMachine;
			var state = rootStateMachine.AddState(MapWalkClipName);
			state.motion = walkClip;
			rootStateMachine.defaultState = state;
			EditorUtility.SetDirty(controller);
			return controller;
		}

		static void WireMapAnimator(GameObject mapRoot, RuntimeAnimatorController controller)
		{
			if (mapRoot == null || controller == null)
				return;
			var anim = mapRoot.GetComponent<Animator>();
			if (anim == null)
				anim = mapRoot.AddComponent<Animator>();
			anim.runtimeAnimatorController = controller;
			anim.applyRootMotion = false;
			anim.cullingMode = AnimatorCullingMode.AlwaysAnimate;
		}

		static void SaveClip(AnimationClip clip)
		{
			var path = $"{GeneratedRoot}/{ClipsRel}/{clip.name}.anim";
			AssetDatabase.CreateAsset(clip, path);
		}

		static List<Texture2D> LoadOrderedFrameTextures()
		{
			var list = new List<(string path, Texture2D tex)>();
			foreach (var guid in AssetDatabase.FindAssets("", new[] { FramesFolder }))
			{
				var path = AssetDatabase.GUIDToAssetPath(guid);
				if (!path.EndsWith(".png", StringComparison.OrdinalIgnoreCase))
					continue;
				var tex = FirstTexture2DAtPath(path);
				if (tex != null)
					list.Add((path, tex));
			}
			return list
				.OrderBy(x => x.path, StringComparer.OrdinalIgnoreCase)
				.Select(x => x.tex)
				.ToList();
		}

		static Texture2D FirstTexture2DAtPath(string assetPath)
		{
			foreach (var o in AssetDatabase.LoadAllAssetsAtPath(assetPath))
				if (o is Texture2D t)
					return t;
			return null;
		}

		static List<Material> BuildFrameMaterials(Material template, List<Texture2D> textures)
		{
			var list = new List<Material>();
			for (var i = 0; i < textures.Count; i++)
			{
				var mat = new Material(template);
				mat.name = $"esquire_frame_{i:00}";
				mat.SetTexture("_MainTex", textures[i]);
				var path = $"{GeneratedRoot}/{MaterialsRel}/esquire_frame_{i:00}.mat";
				AssetDatabase.CreateAsset(mat, path);
				list.Add(mat);
			}
			AssetDatabase.SaveAssets();
			return list;
		}

		static string GuessDefExtractJsonAssetPath() => GuessDefExtractJsonAssetPathForFolder(FramesFolder);

		static string GuessDefExtractJsonAssetPathForFolder(string framesFolder)
		{
			if (string.IsNullOrEmpty(framesFolder))
				return null;
			var frames = framesFolder.Replace('\\', '/').TrimEnd('/');
			var parent = Path.GetDirectoryName(frames)?.Replace('\\', '/');
			if (string.IsNullOrEmpty(parent))
				return null;
			var dirLeaf = Path.GetFileName(frames);
			var baseName = Path.GetFileNameWithoutExtension(dirLeaf);
			return $"{parent}/{baseName}.json";
		}

		static string SummarizeManifestGroups(DefExtractManifest manifest)
		{
			if (manifest?.sequences == null || manifest.sequences.Length == 0)
				return "(none)";
			var ids = manifest.sequences
				.Where(s => s != null && s.frames != null && s.frames.Length > 0)
				.Select(s => s.group)
				.Distinct()
				.OrderBy(g => g);
			return string.Join(", ", ids);
		}

		/// <summary>
		/// Adventure-only .def exports (e.g. HotA <c>AvWPike.def</c>) often contain a single group (movement).
		/// Battle clips need the full creature DEF (e.g. <c>PIKEMAN.DEF</c>).
		/// </summary>
		static bool ManifestCoversBattleClips(DefExtractManifest manifest, out string presentSummary)
		{
			presentSummary = SummarizeManifestGroups(manifest);
			if (manifest?.sequences == null)
				return false;
			var withFrames = new HashSet<int>();
			foreach (var s in manifest.sequences)
				if (s != null && s.frames != null && s.frames.Length > 0)
					withFrames.Add(s.group);
			var attack = withFrames.Contains(GroupAttackUp)
				|| withFrames.Contains(GroupAttackFront)
				|| withFrames.Contains(GroupAttackDown);
			return withFrames.Contains(GroupIdle)
				&& withFrames.Contains(GroupMovement)
				&& withFrames.Contains(GroupHitted)
				&& withFrames.Contains(GroupDeath)
				&& attack;
		}

		static string AssetPathToFilesystemPath(string assetPath)
		{
			assetPath = assetPath.Replace('\\', '/');
			if (!assetPath.StartsWith("Assets/", StringComparison.OrdinalIgnoreCase))
				throw new InvalidOperationException("Expected Assets/ path: " + assetPath);
			var tail = assetPath.Substring("Assets/".Length);
			return Path.Combine(Application.dataPath, tail);
		}

		static bool TryLoadDefExtractManifest(out DefExtractManifest manifest, out string assetPath) =>
			TryLoadDefExtractManifestForFolder(FramesFolder, out manifest, out assetPath);

		static bool TryLoadDefExtractManifestForFolder(string framesFolder, out DefExtractManifest manifest, out string assetPath)
		{
			manifest = null;
			assetPath = GuessDefExtractJsonAssetPathForFolder(framesFolder);
			if (string.IsNullOrEmpty(assetPath))
				return false;
			var fsPath = AssetPathToFilesystemPath(assetPath);
			if (!File.Exists(fsPath))
				return false;
			string text;
			try
			{
				text = File.ReadAllText(fsPath);
			}
			catch (Exception ex)
			{
				Debug.LogWarning("EsquireBillboardAnimatorBuild: could not read defextract JSON: " + ex.Message);
				return false;
			}

			try
			{
				manifest = JsonUtility.FromJson<DefExtractManifest>(text);
			}
			catch (Exception ex)
			{
				Debug.LogWarning("EsquireBillboardAnimatorBuild: failed to parse defextract JSON: " + ex.Message);
				return false;
			}

			if (manifest?.sequences == null || manifest.sequences.Length == 0)
				return false;
			return true;
		}

		static List<string> GetRelativeFramePathsForGroup(DefExtractManifest manifest, int groupId)
		{
			foreach (var seq in manifest.sequences)
			{
				if (seq == null || seq.frames == null)
					continue;
				if (seq.group != groupId)
					continue;
				return seq.frames
					.Where(f => !string.IsNullOrWhiteSpace(f))
					.Select(f => f.Replace('\\', '/'))
					.ToList();
			}

			return new List<string>();
		}

		static List<Material> MaterialsForRelativeFramePaths(
			Material template,
			List<string> relativePaths,
			ref int matCounter,
			Dictionary<string, Material> matCache)
		{
			var parent = Path.GetDirectoryName(FramesFolder.Replace('\\', '/'))?.Replace('\\', '/');
			if (string.IsNullOrEmpty(parent))
				throw new InvalidOperationException("Invalid FramesFolder: " + FramesFolder);

			var list = new List<Material>(relativePaths.Count);
			foreach (var rel in relativePaths)
			{
				var assetPath = $"{parent}/{rel}";
				if (!matCache.TryGetValue(assetPath, out var mat))
				{
					var tex = FirstTexture2DAtPath(assetPath);
					if (tex == null)
						throw new InvalidOperationException(
							"EsquireBillboardAnimatorBuild: missing texture for defextract frame: " + assetPath);
					mat = new Material(template);
					mat.name = $"esquire_frame_{matCounter:000}";
					mat.SetTexture("_MainTex", tex);
					var matPath = $"{GeneratedRoot}/{MaterialsRel}/esquire_frame_{matCounter:000}.mat";
					matCounter++;
					AssetDatabase.CreateAsset(mat, matPath);
					matCache[assetPath] = mat;
				}

				list.Add(mat);
			}

			return list;
		}

		static AnimationClip BuildClipFromManifestGroup(
			string clipName,
			DefExtractManifest manifest,
			int groupId,
			float fps,
			bool loop,
			Material template,
			ref int matCounter,
			Dictionary<string, Material> matCache,
			StringBuilder logGroups)
		{
			var relFrames = GetRelativeFramePathsForGroup(manifest, groupId);
			if (relFrames.Count == 0)
				throw new InvalidOperationException(
					"EsquireBillboardAnimatorBuild: clip '"
					+ clipName
					+ "' — DEF group "
					+ groupId
					+ " has no frames. Re-export the battle .def or fix FramesFolder / JSON.");
			logGroups.Append("  ")
				.Append(clipName)
				.Append(" ← group ")
				.Append(groupId)
				.Append(" (")
				.Append(relFrames.Count)
				.Append(" frames)")
				.AppendLine();
			var mats = MaterialsForRelativeFramePaths(template, relFrames, ref matCounter, matCache);
			return BuildMaterialSwapClipSequential(clipName, mats, fps, loop);
		}

		static AnimationClip BuildClipFromManifestAttack(
			string clipName,
			DefExtractManifest manifest,
			float fps,
			Material template,
			ref int matCounter,
			Dictionary<string, Material> matCache,
			StringBuilder logGroups)
		{
			var tryGroups = new[] { GroupAttackFront, GroupAttackUp, GroupAttackDown };
			for (var gi = 0; gi < tryGroups.Length; gi++)
			{
				var g = tryGroups[gi];
				var relFrames = GetRelativeFramePathsForGroup(manifest, g);
				if (relFrames.Count == 0)
					continue;
				logGroups.Append("  ")
					.Append(clipName)
					.Append(" ← group ")
					.Append(g)
					.Append(" (")
					.Append(relFrames.Count)
					.Append(" frames)");
				if (gi > 0)
					logGroups.Append(" [fallback: group ").Append(GroupAttackFront).Append(" empty]");
				logGroups.AppendLine();
				var mats = MaterialsForRelativeFramePaths(template, relFrames, ref matCounter, matCache);
				return BuildMaterialSwapClipSequential(clipName, mats, fps, loop: false);
			}

			throw new InvalidOperationException(
				"EsquireBillboardAnimatorBuild: clip '"
				+ clipName
				+ "' — no frames in melee attack groups "
				+ GroupAttackUp
				+ ","
				+ GroupAttackFront
				+ ","
				+ GroupAttackDown
				+ ".");
		}

		/// <summary>Swap MeshRenderer shared material slot 0 per frame (Sprites/Default + _MainTex).</summary>
		static AnimationClip BuildMaterialSwapClipSequential(string clipName, IList<Material> mats, float fps, bool loop)
		{
			if (mats == null || mats.Count == 0)
				throw new InvalidOperationException("EsquireBillboardAnimatorBuild: clip '" + clipName + "' has no keyframes.");

			var n = mats.Count;
			var dt = 1f / fps;
			var keys = new ObjectReferenceKeyframe[n];
			for (var i = 0; i < n; i++)
			{
				keys[i] = new ObjectReferenceKeyframe
				{
					time = i * dt,
					value = mats[i]
				};
			}

			var clip = new AnimationClip { name = clipName };
			clip.frameRate = fps;
			var binding = EditorCurveBinding.PPtrCurve(
				QuadRendererPath,
				typeof(MeshRenderer),
				"m_Materials.Array.data[0]");
			AnimationUtility.SetObjectReferenceCurve(clip, binding, keys);

			var settings = AnimationUtility.GetAnimationClipSettings(clip);
			settings.loopTime = loop;
			AnimationUtility.SetAnimationClipSettings(clip, settings);

			EditorUtility.SetDirty(clip);
			return clip;
		}

		static AnimationClip BuildMaterialSwapClip(
			string clipName,
			Material[] all,
			int start,
			int length,
			float fps,
			bool loop)
		{
			length = Mathf.Clamp(length, 1, all.Length - start);
			var mats = new Material[length];
			Array.Copy(all, start, mats, 0, length);
			return BuildMaterialSwapClipSequential(clipName, mats, fps, loop);
		}

		/// <summary>
		/// Every PNG under <see cref="FramesFolder"/>: Default texture for <see cref="MeshRenderer"/> + <c>_MainTex</c>,
		/// point filter, no mipmaps, alpha as transparency — deterministic batch output (matches proposed pipeline).
		/// </summary>
		static void ApplyBattleFramePngImportSettings() => ApplyFolderPngMeshBillboardImport(FramesFolder);

		static void ApplyFolderPngMeshBillboardImport(string folder)
		{
			if (!AssetDatabase.IsValidFolder(folder))
			{
				Debug.LogWarning("EsquireBillboardAnimatorBuild: skip PNG import — folder missing: " + folder);
				return;
			}

			var touched = 0;
			foreach (var guid in AssetDatabase.FindAssets("", new[] { folder }))
			{
				var path = AssetDatabase.GUIDToAssetPath(guid);
				if (!path.EndsWith(".png", StringComparison.OrdinalIgnoreCase))
					continue;
				if (!(AssetImporter.GetAtPath(path) is TextureImporter importer))
					continue;
				ConfigureImporterForMeshBillboardFrame(importer);
				importer.SaveAndReimport();
				touched++;
			}

			Debug.Log(
				"EsquireBillboardAnimatorBuild: reimported "
				+ touched
				+ " frame PNG(s) in "
				+ folder
				+ " with mesh-billboard import defaults.");
		}

		static void ConfigureImporterForMeshBillboardFrame(TextureImporter importer)
		{
			importer.textureType = TextureImporterType.Default;
			importer.textureShape = TextureImporterShape.Texture2D;
			importer.sRGBTexture = true;
			importer.alphaSource = TextureImporterAlphaSource.FromInput;
			importer.alphaIsTransparency = true;
			importer.mipmapEnabled = false;
			importer.filterMode = FilterMode.Point;
			importer.wrapMode = TextureWrapMode.Clamp;
			importer.npotScale = TextureImporterNPOTScale.None;
			var plat = importer.GetDefaultPlatformTextureSettings();
			plat.textureCompression = TextureImporterCompression.Uncompressed;
			plat.crunchedCompression = false;
			importer.SetPlatformTextureSettings(plat);
		}

		static void ApplyBattleQuadAuthoringDefaults(GameObject battlePrefabRoot)
		{
			if (battlePrefabRoot == null)
				return;
			var quad = battlePrefabRoot.transform.Find(QuadRendererPath);
			if (quad == null)
			{
				Debug.LogWarning(
					"EsquireBillboardAnimatorBuild: "
					+ BattlePrefabPath
					+ " missing child '"
					+ QuadRendererPath
					+ "' — quad scale not applied.");
				return;
			}

			quad.localPosition = ComputeBattleQuadLocalPosition();
			quad.localScale = new Vector3(BattleQuadLocalScaleX, BattleQuadLocalScaleY, BattleQuadLocalScaleZ);
		}

		static Vector3 ComputeBattleQuadLocalPosition() =>
			new Vector3(
				BattleQuadLocalPositionX,
				BattleQuadLocalPositionY + BattleQuadLocalPositionExtraY,
				0f);

		static Mesh s_cachedBuiltinQuadMesh;

		static Mesh GetOrCreateBuiltinQuadMesh()
		{
			if (s_cachedBuiltinQuadMesh != null)
				return s_cachedBuiltinQuadMesh;
			var temp = GameObject.CreatePrimitive(PrimitiveType.Quad);
			s_cachedBuiltinQuadMesh = temp.GetComponent<MeshFilter>().sharedMesh;
			UnityEngine.Object.DestroyImmediate(temp);
			return s_cachedBuiltinQuadMesh;
		}

		static void EnsureMapPrefabBillboardStructure(GameObject root, Material quadMaterial)
		{
			if (root == null || quadMaterial == null)
				return;

			foreach (var sr in root.GetComponentsInChildren<SpriteRenderer>(true))
				UnityEngine.Object.DestroyImmediate(sr, true);

			Transform billboard = root.transform.Find("billboard");
			if (billboard == null)
			{
				var bgo = new GameObject("billboard");
				bgo.transform.SetParent(root.transform, false);
				billboard = bgo.transform;
			}

			var quadT = billboard.Find("quad");
			GameObject quadGo;
			if (quadT == null)
			{
				quadGo = new GameObject("quad");
				quadGo.transform.SetParent(billboard, false);
			}
			else
			{
				quadGo = quadT.gameObject;
			}

			var mf = quadGo.GetComponent<MeshFilter>();
			if (mf == null)
				mf = quadGo.AddComponent<MeshFilter>();
			var mr = quadGo.GetComponent<MeshRenderer>();
			if (mr == null)
				mr = quadGo.AddComponent<MeshRenderer>();
			mf.sharedMesh = GetOrCreateBuiltinQuadMesh();
			mr.sharedMaterial = quadMaterial;

			quadGo.transform.localRotation = Quaternion.identity;
			quadGo.transform.localPosition = new Vector3(MapQuadLocalPositionX, MapQuadLocalPositionY, 0f);
			quadGo.transform.localScale = new Vector3(MapQuadLocalScaleX, MapQuadLocalScaleY, MapQuadLocalScaleZ);
		}

		static void EnsureFolder(string path)
		{
			if (AssetDatabase.IsValidFolder(path))
				return;
			var parent = Path.GetDirectoryName(path)?.Replace('\\', '/');
			var name = Path.GetFileName(path);
			if (!string.IsNullOrEmpty(parent) && !AssetDatabase.IsValidFolder(parent))
				EnsureFolder(parent);
			AssetDatabase.CreateFolder(parent ?? "Assets", name);
		}

		static void ClearSubfolders(params string[] folders)
		{
			foreach (var folder in folders)
			{
				if (!AssetDatabase.IsValidFolder(folder))
					continue;
				foreach (var guid in AssetDatabase.FindAssets("", new[] { folder }))
				{
					var p = AssetDatabase.GUIDToAssetPath(guid);
					AssetDatabase.DeleteAsset(p);
				}
			}
			AssetDatabase.SaveAssets();
		}
	}
}
