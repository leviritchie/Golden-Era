// Lane B (HoMM3 lab): deploy with tools/homm3_import/build_homm3_units.cmd → xcopy into <Unity>/Assets/Editor/
// Batch: -executeMethod OldenEra.Homm3Import.Homm3BillboardAnimatorBuild.RebuildFromBatch
//   -homm3UnitSid <folder under Assets/CustomUnits/homm3_lab/>  OR  -homm3AuthoringPath <path/to/authoring.json>

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

namespace OldenEra.Homm3Import
{
	public static partial class Homm3BillboardAnimatorBuild
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

		[Serializable]
		class Homm3UnitBundleManifestJson
		{
			public Homm3UnitBundleEntryJson[] units;
		}

		[Serializable]
		class Homm3UnitBundleEntryJson
		{
			public string unitSid;
		}

		/// <summary>Per-creature authoring beside <c>Assets/CustomUnits/homm3_lab/&lt;unitSid&gt;/authoring.json</c> (JsonUtility fields).</summary>
		[Serializable]
		class Homm3LabAuthoringJson
		{
			public string unitSid;
			public string framesFolder;
			public string templateMaterialPath;
			/// <summary>Optional: <c>Hex/Lit</c> material (duplicate/strip game map donor in Unity). When set, map flip-book materials clone this instead of <c>templateMaterialPath</c> (battle; often <c>Sprites/Default</c>).</summary>
			public string mapTemplateMaterialPath;
			public string battlePrefabPath;
			public string mapPrefabPath;
			public string mapFramesFolder;
			public string generatedRoot;
			public string mapGeneratedRoot;
			public string mapAnimatorControllerPath;
			public string referenceControllerPath;
			public string overrideOutputPath;
			public string legacyFlatControllerPath;
			public string battleAttackFamily;
			public float mapFlipBookFps;
			public float flipBookFps;
			public float deathClipFps;
			public float battleQuadLocalScaleX;
			public float battleQuadLocalScaleY;
			public float battleQuadLocalScaleZ;
			public float battleQuadLocalPositionX;
			public float battleQuadLocalPositionY;
			public float battleQuadLocalPositionExtraY;
			public float mapQuadLocalScaleX;
			public float mapQuadLocalScaleY;
			public float mapQuadLocalScaleZ;
			public float mapQuadLocalPositionX;
			public float mapQuadLocalPositionY;
			public string generatedClipNamesCsv;
			/// <summary>Option D prototype: Texture2DArray battle path (1 = enabled).</summary>
			public int battleTexture2DArray;
			/// <summary>Texture2DArray adventure-map path (1 = enabled; uses extracted_map + MapIdle timing).</summary>
			public int mapTexture2DArray;
		}

		static Homm3LabAuthoringJson _authoring;
		static string[] s_generatedClipNames;
		static bool s_forceBattleTexture2DArray;

		const string MaterialsRel = "Materials";
		const string ClipsRel = "Clips";
		const string QuadRendererPath = "billboard/quad";
		const string MapWalkClipName = "MapIdle";
		const string ProjectileClipName = "Projectile";

		static string FramesFolder => Req(_authoring.framesFolder);
		static string TemplateMaterialPath => Req(_authoring.templateMaterialPath);
		static string MapTemplateMaterialPath =>
			string.IsNullOrWhiteSpace(_authoring.mapTemplateMaterialPath)
				? null
				: _authoring.mapTemplateMaterialPath.Trim().Replace('\\', '/');
		static string BattlePrefabPath => Req(_authoring.battlePrefabPath);
		static string MapPrefabPath => Req(_authoring.mapPrefabPath);
		static string MapFramesFolder => _authoring.mapFramesFolder ?? "";
		static string MapGeneratedRoot => Req(_authoring.mapGeneratedRoot);
		static string MapAnimatorControllerPath => Req(_authoring.mapAnimatorControllerPath);
		static float MapFlipBookFps => _authoring.mapFlipBookFps > 0 ? _authoring.mapFlipBookFps : 10f;
		static string GeneratedRoot => Req(_authoring.generatedRoot);
		static string UnitRoot => Path.GetDirectoryName(BattlePrefabPath)?.Replace('\\', '/');
		static string ProjectilePrefabPath => $"{UnitRoot}/projectiles/homm3_{_authoring.unitSid}_projectile.prefab";
		static string ProjectileGeneratedRoot => $"{UnitRoot}/Generated/Projectiles";
		static string ProjectileControllerPath => $"{ProjectileGeneratedRoot}/Homm3Projectile.controller";
		static string ReferenceControllerPath => Req(_authoring.referenceControllerPath);
		static string OverrideOutputPath => Req(_authoring.overrideOutputPath);
		static string LegacyFlatControllerPath => string.IsNullOrEmpty(_authoring.legacyFlatControllerPath) ? null : _authoring.legacyFlatControllerPath;
		static float FlipBookFps => ResolveBattlePlaybackFps();
		static float DeathClipFps => ResolveBattleDeathPlaybackFps();
		static float BattleQuadLocalScaleX => _authoring.battleQuadLocalScaleX > 0 ? _authoring.battleQuadLocalScaleX : 13.5f;
		static float BattleQuadLocalScaleY => _authoring.battleQuadLocalScaleY > 0 ? _authoring.battleQuadLocalScaleY : 12f;
		static float BattleQuadLocalScaleZ => _authoring.battleQuadLocalScaleZ > 0 ? _authoring.battleQuadLocalScaleZ : 1f;
		static float BattleQuadLocalPositionX => _authoring.battleQuadLocalPositionX;
		static float BattleQuadLocalPositionY => _authoring.battleQuadLocalPositionY;
		static float BattleQuadLocalPositionExtraY => _authoring.battleQuadLocalPositionExtraY;
		static float MapQuadLocalScaleX => _authoring.mapQuadLocalScaleX > 0 ? _authoring.mapQuadLocalScaleX : 16f;
		static float MapQuadLocalScaleY => _authoring.mapQuadLocalScaleY > 0 ? _authoring.mapQuadLocalScaleY : 16f;
		static float MapQuadLocalScaleZ => _authoring.mapQuadLocalScaleZ > 0 ? _authoring.mapQuadLocalScaleZ : 1f;
		static float MapQuadLocalPositionX => _authoring.mapQuadLocalPositionX != 0 ? _authoring.mapQuadLocalPositionX : 1.45f;
		static float MapQuadLocalPositionY => _authoring.mapQuadLocalPositionY != 0 ? _authoring.mapQuadLocalPositionY : 2.45f;
		static string BattleAttackFamily => string.IsNullOrWhiteSpace(_authoring.battleAttackFamily)
			? "auto"
			: _authoring.battleAttackFamily.Trim().ToLowerInvariant();

		static string[] GeneratedClipNames => s_generatedClipNames ?? throw new InvalidOperationException("Homm3Lab: clip names not initialized");

		static string Req(string s)
		{
			if (string.IsNullOrWhiteSpace(s))
				throw new InvalidOperationException("Homm3Lab authoring.json missing a required path field.");
			return s.Trim().Replace('\\', '/');
		}

		/// <summary>Map frames use authoring <c>mapTemplateMaterialPath</c> when set; otherwise battle <c>templateMaterialPath</c>.</summary>
		static Material LoadMapBillboardTemplateMaterial()
		{
			var mapPath = MapTemplateMaterialPath;
			if (!string.IsNullOrEmpty(mapPath))
			{
				var mapMat = AssetDatabase.LoadAssetAtPath<Material>(mapPath);
				if (mapMat == null)
					throw new InvalidOperationException("mapTemplateMaterialPath material missing: " + mapPath);
				Debug.Log(
					"Homm3BillboardAnimatorBuild: map frame materials use mapTemplateMaterialPath → "
					+ mapPath
					+ " (shader="
					+ (mapMat.shader ? mapMat.shader.name : "?")
					+ ").");
				return mapMat;
			}

			var battle = AssetDatabase.LoadAssetAtPath<Material>(TemplateMaterialPath);
			if (battle == null)
				throw new InvalidOperationException("Template material missing: " + TemplateMaterialPath);
			Debug.Log(
				"Homm3BillboardAnimatorBuild: map frames use battle templateMaterialPath (set mapTemplateMaterialPath for Hex/Lit at bake time).");
			return battle;
		}

		// HoMM3 / VCMI creature DEF group ids — https://vcmi.eu/modders/Animation_Format/
		const int GroupMovement = 0;
		const int GroupMouseOver = 1;
		const int GroupIdle = 2;
		const int GroupHitted = 3;
		const int GroupDeath = 5;
		const int GroupAttackUp = 11;
		const int GroupAttackFront = 12;
		const int GroupAttackDown = 13;
		const int GroupProjectileUp = 14;
		const int GroupProjectileFront = 15;
		const int GroupProjectileDown = 16;
		const int GroupTeleportLeave = 20;
		const int GroupTeleportArrive = 21;
		static readonly int[] MovementGroupPreference = { GroupMovement, GroupMouseOver, GroupIdle };
		static readonly int[] MeleeAttackGroupPreference = { GroupAttackFront, GroupAttackUp, GroupAttackDown };
		static readonly int[] ShootAttackGroupPreference = { GroupProjectileFront, GroupProjectileUp, GroupProjectileDown };
		static readonly HashSet<string> TeleportDiveMovementUnitSids = new(StringComparer.Ordinal)
		{
			"hota_cove_nymph",
			"hota_cove_oceanid",
			"hota_cove_nereid",
		};

		static bool s_applyBattleQuadDefaultsThisRun;

		/// <summary>Folders whose battle/map PNGs already have mesh-billboard import settings (skip per-file reimport).</summary>
		static readonly HashSet<string> s_meshBillboardImportConfiguredFolders =
			new HashSet<string>(StringComparer.OrdinalIgnoreCase);

		[MenuItem("Olden Era/Homm3 Lab/Rebuild billboard (use batch -homm3UnitSid)")]
		public static void RebuildMenu()
		{
			Debug.LogWarning(
				"Homm3BillboardAnimatorBuild: use tools/homm3_import/build_homm3_units.cmd or Unity batch with "
				+ "-homm3UnitSid <id> (authoring.json under Assets/CustomUnits/homm3_lab/<id>/).");
		}

		[MenuItem("Olden Era/Homm3 Lab/Rebuild map mesh (use batch)")]
		public static void RebuildMapMenu() =>
			Debug.LogWarning("Homm3BillboardAnimatorBuild: map rebuild runs from batch after battle rebuild (RebuildFromBatch).");

		[MenuItem("Olden Era/Homm3 Lab/Apply battle quad defaults (use batch)")]
		public static void ApplyQuadDefaultsMenu() =>
			Debug.LogWarning("Homm3BillboardAnimatorBuild: quad defaults are applied when RebuildFromBatch runs with authoring.json.");

		static void LoadAuthoringJsonFile(string jsonPath)
		{
			var json = File.ReadAllText(jsonPath);
			_authoring = JsonUtility.FromJson<Homm3LabAuthoringJson>(json);
			if (_authoring == null)
				throw new InvalidOperationException("Homm3Lab: failed to parse authoring JSON: " + jsonPath);

			if (string.IsNullOrEmpty(_authoring.generatedClipNamesCsv))
				s_generatedClipNames = new[] { "22.Idle", "01.Walk", "14.Attack", "20.Damage", "21.Death" };
			else
				s_generatedClipNames = _authoring.generatedClipNamesCsv
					.Split(',')
					.Select(x => x.Trim())
					.Where(x => x.Length > 0)
					.ToArray();
			if (s_generatedClipNames.Length == 0)
				throw new InvalidOperationException("Homm3Lab: generatedClipNamesCsv produced no clip names.");

			if (_authoring.battleQuadLocalPositionX == 0f && _authoring.battleQuadLocalPositionY == 0f)
			{
				_authoring.battleQuadLocalPositionX = 0.75f;
				_authoring.battleQuadLocalPositionY = 2.01f;
			}
		}

		static bool CommandLineEnablesBattleTexture2DArray(string[] args)
		{
			for (var i = 0; i < args.Length; i++)
			{
				if (args[i] == "-homm3BattleTexture2DArray")
				{
					if (i + 1 >= args.Length)
						return true;
					var value = args[i + 1]?.Trim();
					return string.IsNullOrEmpty(value)
					       || value == "1"
					       || value.Equals("true", StringComparison.OrdinalIgnoreCase)
					       || value.Equals("yes", StringComparison.OrdinalIgnoreCase);
				}
			}
			var env = Environment.GetEnvironmentVariable("HOMM3_BATTLE_TEXTURE_ARRAY");
			return env == "1"
			       || string.Equals(env, "true", StringComparison.OrdinalIgnoreCase)
			       || string.Equals(env, "yes", StringComparison.OrdinalIgnoreCase);
		}

		static void LoadAuthoringFromCommandLine()
		{
			var args = UnityQueueArgs();
			s_forceBattleTexture2DArray = CommandLineEnablesBattleTexture2DArray(args);
			string sid = null;
			string authoringFs = null;
			for (var i = 0; i < args.Length - 1; i++)
			{
				if (args[i] == "-homm3UnitSid")
					sid = args[i + 1];
				if (args[i] == "-homm3AuthoringPath")
					authoringFs = args[i + 1];
			}

			string jsonPath = null;
			if (!string.IsNullOrEmpty(authoringFs))
			{
				jsonPath = Path.GetFullPath(authoringFs);
				if (!File.Exists(jsonPath))
					throw new InvalidOperationException("Homm3Lab authoring not found: " + jsonPath);
			}
			else if (!string.IsNullOrEmpty(sid))
			{
				jsonPath = Path.Combine(Application.dataPath, "CustomUnits", "homm3_lab", sid.Trim(), "authoring.json");
				if (!File.Exists(jsonPath))
					throw new InvalidOperationException("Homm3Lab authoring not found: " + jsonPath);
			}
			else
				throw new InvalidOperationException(
					"Homm3BillboardAnimatorBuild: pass -homm3UnitSid <folder> or -homm3AuthoringPath <authoring.json>.");

			LoadAuthoringJsonFile(jsonPath);
		}

		public static void RebuildFromBatch()
		{
			try
			{
				LoadAuthoringFromCommandLine();
				s_applyBattleQuadDefaultsThisRun = true;
				Rebuild();
				Debug.Log("Homm3BillboardAnimatorBuild: completed for unitSid=" + (_authoring.unitSid ?? "?") + ".");
			}
			catch (Exception ex)
			{
				Debug.LogError("Homm3BillboardAnimatorBuild failed: " + ex);
				UnityQueueExit(1);
				throw;
			}
			finally
			{
				s_applyBattleQuadDefaultsThisRun = false;
			}
		}

		public static void RebuildAllFromManifest()
		{
			try
			{
				s_forceBattleTexture2DArray = CommandLineEnablesBattleTexture2DArray(UnityQueueArgs());
				var args = UnityQueueArgs();
				string manifestFs = null;
				string unitListFs = null;
				for (var i = 0; i < args.Length - 1; i++)
				{
					if (args[i] == "-manifestPath")
						manifestFs = args[i + 1];
					if (args[i] == "-homm3UnitListPath")
						unitListFs = args[i + 1];
				}

				if (string.IsNullOrWhiteSpace(manifestFs))
					throw new InvalidOperationException("Homm3BillboardAnimatorBuild: pass -manifestPath for RebuildAllFromManifest.");

				var manifestPath = Path.GetFullPath(manifestFs);
				var manifest = JsonUtility.FromJson<Homm3UnitBundleManifestJson>(File.ReadAllText(manifestPath));
				if (manifest?.units == null || manifest.units.Length == 0)
					throw new InvalidOperationException("Homm3BillboardAnimatorBuild: manifest has no units: " + manifestPath);

				HashSet<string> unitFilter = null;
				if (!string.IsNullOrWhiteSpace(unitListFs))
				{
					var unitListPath = Path.GetFullPath(unitListFs.Trim().Trim('"'));
					unitFilter = new HashSet<string>(
						File.ReadAllLines(unitListPath)
							.Select(x => x.Trim())
							.Where(x => x.Length > 0 && !x.StartsWith("#", StringComparison.Ordinal)),
						StringComparer.OrdinalIgnoreCase);
					Debug.Log(
						"Homm3BillboardAnimatorBuild: unit filter "
						+ unitFilter.Count
						+ " entries from "
						+ unitListPath
						+ (unitFilter.Contains("temple_griffon") ? " (includes temple_griffon)" : " (excludes temple_griffon)"));
				}
				else
				{
					Debug.LogWarning(
						"Homm3BillboardAnimatorBuild: no -homm3UnitListPath; rebuilding all manifest units.");
				}

				var rebuilt = 0;
				var rebuildOrdinal = 0;
				s_applyBattleQuadDefaultsThisRun = true;
				foreach (var entry in manifest.units)
				{
					var sid = entry?.unitSid?.Trim();
					if (string.IsNullOrEmpty(sid))
						continue;
					if (unitFilter != null && !unitFilter.Contains(sid))
						continue;
					var authoringPath = Path.Combine(Application.dataPath, "CustomUnits", "homm3_lab", sid, "authoring.json");
					if (!File.Exists(authoringPath))
					{
						Debug.LogWarning("Homm3BillboardAnimatorBuild: skip missing authoring for " + sid + ": " + authoringPath);
						continue;
					}

					rebuildOrdinal++;
					var unitSw = System.Diagnostics.Stopwatch.StartNew();
					Debug.Log(
						"Homm3BillboardAnimatorBuild: RebuildAllFromManifest ["
						+ rebuildOrdinal
						+ "] unitSid="
						+ sid);
					LoadAuthoringJsonFile(authoringPath);
					Rebuild();
					rebuilt++;
					Debug.Log(
						"Homm3BillboardAnimatorBuild: RebuildAllFromManifest ["
						+ rebuildOrdinal
						+ "] unitSid="
						+ sid
						+ " done in "
						+ unitSw.Elapsed.TotalSeconds.ToString("F1")
						+ "s");
					Resources.UnloadUnusedAssets();
				}

				if (rebuilt == 0)
					throw new InvalidOperationException("Homm3BillboardAnimatorBuild: rebuilt zero units from manifest.");
				Debug.Log("Homm3BillboardAnimatorBuild: RebuildAllFromManifest completed for " + rebuilt + " unit(s).");
			}
			catch (Exception ex)
			{
				Debug.LogError("Homm3BillboardAnimatorBuild failed: " + ex);
				UnityQueueExit(1);
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
			if (ApplyBattleFramePngImportSettings())
				AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
			var template = AssetDatabase.LoadAssetAtPath<Material>(TemplateMaterialPath);
			if (template == null)
				throw new InvalidOperationException("Template material missing: " + TemplateMaterialPath);

			var baseController = AssetDatabase.LoadAssetAtPath<AnimatorController>(ReferenceControllerPath);
			if (baseController == null)
				throw new InvalidOperationException(
					"Missing stock AnimatorController for GUI parity. Export via AssetRipper / AssetStudio to:\n  "
					+ ReferenceControllerPath
					+ "\nSee tools/custom_prefab_pipeline/unity_editor/StockEsquireBattle_IMPORT.txt (same process for other units).");

			var genParent = Path.GetDirectoryName(GeneratedRoot.Replace('\\', '/'))?.Replace('\\', '/');
			if (!string.IsNullOrEmpty(genParent))
				EnsureFolder(genParent);
			EnsureFolder(GeneratedRoot);
			EnsureFolder($"{GeneratedRoot}/{MaterialsRel}");
			EnsureFolder($"{GeneratedRoot}/{ClipsRel}");

			ClearSubfolders($"{GeneratedRoot}/{MaterialsRel}", $"{GeneratedRoot}/{ClipsRel}");
			if (AssetDatabase.LoadAssetAtPath<AnimatorOverrideController>(OverrideOutputPath))
				AssetDatabase.DeleteAsset(OverrideOutputPath);
			if (!string.IsNullOrEmpty(LegacyFlatControllerPath)
			    && AssetDatabase.LoadAssetAtPath<AnimatorController>(LegacyFlatControllerPath))
				AssetDatabase.DeleteAsset(LegacyFlatControllerPath);

			AnimationClip idleClip, moveClip, attackClip, hitClip, deathClip, meleeAltAttackClip = null;
			var teleportClips = new List<AnimationClip>();

			DefExtractManifest manifest = null;
			string manifestJsonPath = null;
			var manifestGroupSummary = "";
			var haveDefExtractJson = TryLoadDefExtractManifest(out manifest, out manifestJsonPath);
			var useDefExtractGroups = haveDefExtractJson && ManifestCoversBattleClips(manifest, out manifestGroupSummary);

			if (useDefExtractGroups && UseBattleTexture2DArray())
			{
				RebuildBattleTexture2DArray(manifest, template, baseController);
				RebuildMapMeshBillboard();
				RebuildProjectilePrefab(manifest, template);
				AssetDatabase.SaveAssets();
				AssetDatabase.Refresh();
				return;
			}

			if (useDefExtractGroups)
			{
				var matCache = new Dictionary<string, Material>(StringComparer.OrdinalIgnoreCase);
				var matCounter = 0;
				var logGroups = new StringBuilder();
				logGroups.Append("Homm3BillboardAnimatorBuild: using defextract manifest ").Append(manifestJsonPath).AppendLine();

				idleClip = BuildClipFromManifestGroup(
					"22.Idle", manifest, GroupIdle, FlipBookFps, loop: true, template, ref matCounter, matCache, logGroups);
				moveClip = BuildClipFromManifestMovement(
					"01.Walk", manifest, FlipBookFps, loop: true, template, ref matCounter, matCache, logGroups, _authoring.unitSid);
				if (ShouldUseTeleportDiveMovement(_authoring.unitSid, manifest))
				{
					teleportClips.Add(BuildClipFromManifestGroup(
						"10.Tp_Start", manifest, GroupTeleportLeave, FlipBookFps, loop: false, template, ref matCounter, matCache, logGroups));
					teleportClips.Add(BuildClipFromManifestGroup(
						"11.Tp_End", manifest, GroupTeleportArrive, FlipBookFps, loop: false, template, ref matCounter, matCache, logGroups));
					teleportClips.Add(BuildClipFromManifestGroup(
						"12.Tp_Ability_Start", manifest, GroupTeleportLeave, FlipBookFps, loop: false, template, ref matCounter, matCache, logGroups));
					teleportClips.Add(BuildClipFromManifestGroup(
						"13.Tp_Ability_End", manifest, GroupTeleportArrive, FlipBookFps, loop: false, template, ref matCounter, matCache, logGroups));
				}
				attackClip = BuildClipFromManifestAttack(
					"14.Attack", manifest, FlipBookFps, template, ref matCounter, matCache, logGroups);
				meleeAltAttackClip = BuildClipFromManifestMeleeAlternativeAttack(
					manifest, FlipBookFps, template, ref matCounter, matCache, logGroups);
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
						"Homm3BillboardAnimatorBuild: defextract JSON found at "
						+ manifestJsonPath
						+ " but it does not include all battle groups (need idle=2, hitted=3, death=5, "
						+ "and at least one melee or shooter attack group: "
						+ GroupAttackUp
						+ "/"
						+ GroupAttackFront
						+ "/"
						+ GroupAttackDown
						+ " or "
						+ GroupProjectileUp
						+ "/"
						+ GroupProjectileFront
						+ "/"
						+ GroupProjectileDown
						+ " with frames). Groups present in file: "
						+ manifestGroupSummary
						+ ". This often means the source was an adventure-map .def (e.g. AvWPike.def) rather than "
						+ "the battle creature DEF. Re-extract from PIKEMAN.DEF (or your mod’s battle equivalent). "
						+ "Falling back to legacy flat-folder slices.");
				}
				else
				{
					Debug.LogWarning(
						"Homm3BillboardAnimatorBuild: no defextract JSON beside frames folder (expected "
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
			if (meleeAltAttackClip != null)
				SaveClip(meleeAltAttackClip);
			foreach (var teleportClip in teleportClips)
				SaveClip(teleportClip);
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
					Debug.LogWarning("Homm3BillboardAnimatorBuild: expected generated clip missing: " + clipPath);
			}
			if (meleeAltAttackClip != null)
			{
				var clipPath = $"{GeneratedRoot}/{ClipsRel}/{meleeAltAttackClip.name}.anim";
				var c = AssetDatabase.LoadAssetAtPath<AnimationClip>(clipPath);
				if (c != null)
					generatedByName[meleeAltAttackClip.name] = c;
				else
					Debug.LogWarning("Homm3BillboardAnimatorBuild: expected generated melee alternative clip missing: " + clipPath);
			}
			foreach (var teleportClip in teleportClips)
			{
				var clipPath = $"{GeneratedRoot}/{ClipsRel}/{teleportClip.name}.anim";
				var c = AssetDatabase.LoadAssetAtPath<AnimationClip>(clipPath);
				if (c != null)
					generatedByName[teleportClip.name] = c;
				else
					Debug.LogWarning("Homm3BillboardAnimatorBuild: expected generated teleport clip missing: " + clipPath);
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
				var replacement = ResolveGeneratedOverrideClip(orig.name, generatedByName);
				if (replacement == null)
				{
					if (warnedMissing.Add(orig.name))
						Debug.LogWarning(
							"Homm3BillboardAnimatorBuild: no generated flip-book fallback for stock clip '"
							+ orig.name
							+ "' - override left empty.");
					continue;
				}

				overrides[i] = new KeyValuePair<AnimationClip, AnimationClip>(orig, replacement);
				replaced++;
			}

			overrideController.ApplyOverrides(overrides);
			EditorUtility.SetDirty(overrideController);
			AssetDatabase.SaveAssets();

			Debug.Log(
				"Homm3BillboardAnimatorBuild: AnimatorOverrideController applied "
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
					"Homm3BillboardAnimatorBuild: applied battle quad defaults (batch) localScale=("
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
			RebuildProjectilePrefab(manifest, template);

			AssetDatabase.SaveAssets();
			AssetDatabase.Refresh();
		}

		static void RebuildProjectilePrefab(DefExtractManifest manifest, Material template)
		{
			if (manifest == null || template == null || string.IsNullOrEmpty(UnitRoot))
				return;
			var tryGroups = new[] { GroupProjectileFront, GroupProjectileUp, GroupProjectileDown };
			List<string> relFrames = null;
			var group = 0;
			foreach (var g in tryGroups)
			{
				var rel = GetRelativeFramePathsForGroup(manifest, g);
				if (rel.Count == 0)
					continue;
				relFrames = rel;
				group = g;
				break;
			}

			if (relFrames == null || relFrames.Count == 0)
			{
				Debug.Log("Homm3BillboardAnimatorBuild: no projectile DEF groups 14/15/16 for " + _authoring.unitSid + "; projectile prefab skipped.");
				return;
			}

			EnsureFolder($"{UnitRoot}/projectiles");
			EnsureFolder(ProjectileGeneratedRoot);
			EnsureFolder($"{ProjectileGeneratedRoot}/{MaterialsRel}");
			EnsureFolder($"{ProjectileGeneratedRoot}/{ClipsRel}");
			ClearSubfolders($"{ProjectileGeneratedRoot}/{MaterialsRel}", $"{ProjectileGeneratedRoot}/{ClipsRel}");
			if (AssetDatabase.LoadAssetAtPath<AnimatorController>(ProjectileControllerPath))
				AssetDatabase.DeleteAsset(ProjectileControllerPath);

			var matCache = new Dictionary<string, Material>(StringComparer.OrdinalIgnoreCase);
			var matCounter = 0;
			var mats = MaterialsForRelativeFramePathsAtRoot(
				template,
				relFrames,
				ProjectileGeneratedRoot,
				"projectile_frame",
				ref matCounter,
				matCache);
			var clip = BuildMaterialSwapClipSequential(ProjectileClipName, mats, FlipBookFps, loop: true);
			var clipPath = $"{ProjectileGeneratedRoot}/{ClipsRel}/{ProjectileClipName}.anim";
			AssetDatabase.CreateAsset(clip, clipPath);
			AssetDatabase.SaveAssets();
			var clipAsset = AssetDatabase.LoadAssetAtPath<AnimationClip>(clipPath);
			var controller = AnimatorController.CreateAnimatorControllerAtPath(ProjectileControllerPath);
			var state = controller.layers[0].stateMachine.AddState(ProjectileClipName);
			state.motion = clipAsset;
			controller.layers[0].stateMachine.defaultState = state;

			var root = new GameObject("homm3_" + _authoring.unitSid + "_projectile");
			try
			{
				var billboard = new GameObject("billboard");
				billboard.transform.SetParent(root.transform, false);
				var quad = new GameObject("quad");
				quad.transform.SetParent(billboard.transform, false);
				var mf = quad.AddComponent<MeshFilter>();
				var mr = quad.AddComponent<MeshRenderer>();
				mf.sharedMesh = GetOrCreateBuiltinQuadMesh();
				mr.sharedMaterial = mats[0];
				quad.transform.localRotation = Quaternion.identity;
				quad.transform.localPosition = Vector3.zero;
				quad.transform.localScale = new Vector3(4f, 4f, 1f);

				var animator = root.AddComponent<Animator>();
				animator.runtimeAnimatorController = controller;
				animator.applyRootMotion = false;
				PrefabUtility.SaveAsPrefabAsset(root, ProjectilePrefabPath);
			}
			finally
			{
				UnityEngine.Object.DestroyImmediate(root);
			}

			Debug.Log(
				"Homm3BillboardAnimatorBuild: projectile prefab -> "
				+ ProjectilePrefabPath
				+ " from DEF group "
				+ group
				+ " ("
				+ mats.Count
				+ " frame materials).");
		}

		static AnimationClip ResolveGeneratedOverrideClip(string stockClipName, Dictionary<string, AnimationClip> generatedByName)
		{
			if (string.IsNullOrEmpty(stockClipName) || generatedByName == null)
				return null;
			if (generatedByName.TryGetValue(stockClipName, out var exact))
				return exact;

			var n = stockClipName.ToLowerInvariant();
			if ((n.Contains("walk")
			     || n.Contains("move")
			     || n.Contains("run")
			     || n.Contains("fly")
			     || n.Contains("teleport")
			     || n.Contains("tp_start")
			     || n.Contains("tp_end")
			     || n.Contains("tp_ability"))
			    && generatedByName.TryGetValue("01.Walk", out var walk))
				return walk;
			if (IsStockAttackVariantClipName(n)
			    && generatedByName.TryGetValue("14.Attack", out var attack))
				return attack;
			if ((n.Contains("damage") || n.Contains("hit") || n.Contains("wound") || n.Contains("wnce"))
			    && generatedByName.TryGetValue("20.Damage", out var damage))
				return damage;
			if (IsStockDeathClipName(n)
			    && generatedByName.TryGetValue("21.Death", out var death))
				return death;
			if (generatedByName.TryGetValue("22.Idle", out var idle))
				return idle;
			return null;
		}

		static bool IsStockAttackVariantClipName(string lowerName)
		{
			if (lowerName.Contains("attack") || lowerName.Contains("atk") || lowerName.Contains("shoot"))
				return true;
			for (var i = 1; i <= 5; i++)
			{
				var token = "skill_" + i;
				if (lowerName == token || lowerName.EndsWith("." + token) || lowerName.Contains("/" + token))
					return true;
			}
			return false;
		}

		static bool IsStockDeathClipName(string lowerName)
		{
			return lowerName.Contains("death")
				|| lowerName.Contains("dead")
				|| lowerName == "die"
				|| lowerName.EndsWith(".die")
				|| lowerName.Contains("_die")
				|| lowerName.Contains("-die");
		}

		/// <summary>
		/// (Re)author <c>map.prefab</c> as <c>billboard/quad</c> + <see cref="MeshRenderer"/> flip-book + minimal <see cref="Animator"/>.
		/// Uses <see cref="MapFramesFolder"/> (adventure-map DEF extract) only.
		/// Prefers DEF <b>idle</b> (group 2) so the map does not play the battle <b>walk</b> cycle; only uses movement (group 0) if idle is absent.
		/// </summary>
		public static void RebuildMapMeshBillboard()
		{
			if (UseMapTexture2DArray())
			{
				RebuildMapTexture2DArray();
				return;
			}

			var framesRoot = ResolveMapFramesFolder();
			if (ApplyFolderPngMeshBillboardImport(framesRoot))
				AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);

			var template = LoadMapBillboardTemplateMaterial();

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
						"Homm3BillboardAnimatorBuild: map flip-book from defextract "
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
					"Homm3BillboardAnimatorBuild: map used flat PNG order ("
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
				"Homm3BillboardAnimatorBuild: map prefab → "
				+ MapPrefabPath
				+ " ("
				+ mapMats.Count
				+ " frame materials, controller "
				+ MapAnimatorControllerPath
				+ ").");
		}

		static string ResolveMapFramesFolder()
		{
			var map = MapFramesFolder;
			var normalizedMap = string.IsNullOrEmpty(map) ? null : map.Trim().Replace('\\', '/');
			if (string.IsNullOrEmpty(normalizedMap) || !AssetDatabase.IsValidFolder(normalizedMap) || !normalizedMap.Contains("/extracted_map/"))
			{
				throw new InvalidOperationException(
					"Homm3BillboardAnimatorBuild: MapFramesFolder missing or invalid ("
					+ map
					+ "). Adventure-map billboards must use extracted_map assets; rebuild extraction instead of falling back to battle frames.");
			}
			return normalizedMap;
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
							"Homm3BillboardAnimatorBuild: missing texture for map defextract frame: " + assetPath);
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
				mat.name = $"homm3_frame_{i:00}";
				mat.SetTexture("_MainTex", textures[i]);
				var path = $"{GeneratedRoot}/{MaterialsRel}/homm3_frame_{i:00}.mat";
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
			var attack = ManifestHasGroupFrames(withFrames, MeleeAttackGroupPreference)
				|| ManifestHasGroupFrames(withFrames, ShootAttackGroupPreference);
			return withFrames.Contains(GroupIdle)
				&& withFrames.Contains(GroupHitted)
				&& withFrames.Contains(GroupDeath)
				&& attack;
		}

		static bool ManifestHasGroupFrames(HashSet<int> withFrames, int[] groups)
		{
			if (withFrames == null || groups == null)
				return false;
			for (var i = 0; i < groups.Length; i++)
				if (withFrames.Contains(groups[i]))
					return true;
			return false;
		}

		static bool ManifestHasGroupFrames(DefExtractManifest manifest, int[] groups)
		{
			if (manifest?.sequences == null || groups == null)
				return false;
			foreach (var s in manifest.sequences)
			{
				if (s == null || s.frames == null || s.frames.Length == 0)
					continue;
				for (var i = 0; i < groups.Length; i++)
					if (s.group == groups[i])
						return true;
			}
			return false;
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
				Debug.LogWarning("Homm3BillboardAnimatorBuild: could not read defextract JSON: " + ex.Message);
				return false;
			}

			try
			{
				manifest = JsonUtility.FromJson<DefExtractManifest>(text);
			}
			catch (Exception ex)
			{
				Debug.LogWarning("Homm3BillboardAnimatorBuild: failed to parse defextract JSON: " + ex.Message);
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
			return MaterialsForRelativeFramePathsAtRoot(
				template,
				relativePaths,
				GeneratedRoot,
				"homm3_frame",
				ref matCounter,
				matCache);
		}

		static List<Material> MaterialsForRelativeFramePathsAtRoot(
			Material template,
			List<string> relativePaths,
			string outputRoot,
			string materialPrefix,
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
							"Homm3BillboardAnimatorBuild: missing texture for defextract frame: " + assetPath);
					mat = new Material(template);
					mat.name = $"{materialPrefix}_{matCounter:000}";
					mat.SetTexture("_MainTex", tex);
					var matPath = $"{outputRoot}/{MaterialsRel}/{materialPrefix}_{matCounter:000}.mat";
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
					"Homm3BillboardAnimatorBuild: clip '"
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

		static AnimationClip BuildClipFromManifestMovement(
			string clipName,
			DefExtractManifest manifest,
			float fps,
			bool loop,
			Material template,
			ref int matCounter,
			Dictionary<string, Material> matCache,
			StringBuilder logGroups,
			string unitSid)
		{
			if (ShouldUseTeleportDiveMovement(unitSid, manifest))
			{
				var relFrames = new List<string>();
				relFrames.AddRange(GetRelativeFramePathsForGroup(manifest, GroupTeleportLeave));
				relFrames.AddRange(GetRelativeFramePathsForGroup(manifest, GroupTeleportArrive));
				logGroups.Append("  ")
					.Append(clipName)
					.Append(" <- groups ")
					.Append(GroupTeleportLeave)
					.Append("+")
					.Append(GroupTeleportArrive)
					.Append(" (")
					.Append(relFrames.Count)
					.Append(" frames) [teleport dive movement]")
					.AppendLine();
				var mats = MaterialsForRelativeFramePaths(template, relFrames, ref matCounter, matCache);
				return BuildMaterialSwapClipSequential(clipName, mats, fps, loop);
			}

			for (var i = 0; i < MovementGroupPreference.Length; i++)
			{
				var groupId = MovementGroupPreference[i];
				var relFrames = GetRelativeFramePathsForGroup(manifest, groupId);
				if (relFrames.Count == 0)
					continue;
				logGroups.Append("  ")
					.Append(clipName)
					.Append(" <- group ")
					.Append(groupId)
					.Append(" (")
					.Append(relFrames.Count)
					.Append(" frames)");
				if (i > 0)
					logGroups.Append(" [movement fallback]");
				logGroups.AppendLine();
				var mats = MaterialsForRelativeFramePaths(template, relFrames, ref matCounter, matCache);
				return BuildMaterialSwapClipSequential(clipName, mats, fps, loop);
			}

			throw new InvalidOperationException(
				"Homm3BillboardAnimatorBuild: clip '"
				+ clipName
				+ "' - no frames in movement fallback groups "
				+ GroupMovement
				+ ","
				+ GroupMouseOver
				+ ","
				+ GroupIdle
				+ ".");
		}

		static bool ShouldUseTeleportDiveMovement(string unitSid, DefExtractManifest manifest)
		{
			return !string.IsNullOrEmpty(unitSid)
				&& TeleportDiveMovementUnitSids.Contains(unitSid)
				&& GetRelativeFramePathsForGroup(manifest, GroupTeleportLeave).Count > 0
				&& GetRelativeFramePathsForGroup(manifest, GroupTeleportArrive).Count > 0;
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
			var tryGroups = PreferredAttackGroupPreference(manifest, out var familyLabel, out var fallbackGroups, out var fallbackLabel);
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
					.Append(" frames; ")
					.Append(familyLabel)
					.Append(")");
				if (gi > 0)
					logGroups.Append(" [fallback: earlier group(s) empty]");
				logGroups.AppendLine();
				var mats = MaterialsForRelativeFramePaths(template, relFrames, ref matCounter, matCache);
				return BuildMaterialSwapClipSequential(clipName, mats, fps, loop: false);
			}

			for (var gi = 0; gi < fallbackGroups.Length; gi++)
			{
				var g = fallbackGroups[gi];
				var relFrames = GetRelativeFramePathsForGroup(manifest, g);
				if (relFrames.Count == 0)
					continue;
				logGroups.Append("  ")
					.Append(clipName)
					.Append(" <- group ")
					.Append(g)
					.Append(" (")
					.Append(relFrames.Count)
					.Append(" frames; ")
					.Append(fallbackLabel)
					.Append(") [fallback family]");
				if (gi > 0)
					logGroups.Append(" [fallback: earlier group(s) empty]");
				logGroups.AppendLine();
				var mats = MaterialsForRelativeFramePaths(template, relFrames, ref matCounter, matCache);
				return BuildMaterialSwapClipSequential(clipName, mats, fps, loop: false);
			}

			throw new InvalidOperationException(
				"Homm3BillboardAnimatorBuild: clip '"
				+ clipName
				+ "' — no frames in melee attack groups "
				+ GroupAttackUp
				+ ","
				+ GroupAttackFront
				+ ","
				+ GroupAttackDown
				+ " or shooter attack groups "
				+ GroupProjectileUp
				+ ","
				+ GroupProjectileFront
				+ ","
				+ GroupProjectileDown
				+ ".");
		}

		static AnimationClip BuildClipFromManifestMeleeAlternativeAttack(
			DefExtractManifest manifest,
			float fps,
			Material template,
			ref int matCounter,
			Dictionary<string, Material> matCache,
			StringBuilder logGroups)
		{
			if (!ManifestHasGroupFrames(manifest, ShootAttackGroupPreference)
			    || !ManifestHasGroupFrames(manifest, MeleeAttackGroupPreference))
				return null;
			for (var gi = 0; gi < MeleeAttackGroupPreference.Length; gi++)
			{
				var g = MeleeAttackGroupPreference[gi];
				var relFrames = GetRelativeFramePathsForGroup(manifest, g);
				if (relFrames.Count == 0)
					continue;
				logGroups.Append("  15.Skill_1 <- group ")
					.Append(g)
					.Append(" (")
					.Append(relFrames.Count)
					.Append(" frames; melee alternative for shooter)");
				if (gi > 0)
					logGroups.Append(" [fallback: earlier group(s) empty]");
				logGroups.AppendLine();
				var mats = MaterialsForRelativeFramePaths(template, relFrames, ref matCounter, matCache);
				return BuildMaterialSwapClipSequential("15.Skill_1", mats, fps, loop: false);
			}
			return null;
		}

		static int[] PreferredAttackGroupPreference(
			DefExtractManifest manifest,
			out string familyLabel,
			out int[] fallbackGroups,
			out string fallbackLabel)
		{
			var configured = BattleAttackFamily;
			if (configured == "melee")
			{
				familyLabel = "melee";
				fallbackGroups = ShootAttackGroupPreference;
				fallbackLabel = "shoot";
				return MeleeAttackGroupPreference;
			}
			if (configured == "shoot" || configured == "ranged" || configured == "projectile")
			{
				familyLabel = "shoot";
				fallbackGroups = MeleeAttackGroupPreference;
				fallbackLabel = "melee";
				return ShootAttackGroupPreference;
			}
			if (configured != "auto")
				Debug.LogWarning("Homm3BillboardAnimatorBuild: unknown battleAttackFamily '" + configured + "'; using auto.");

			if (ManifestHasGroupFrames(manifest, ShootAttackGroupPreference))
			{
				familyLabel = "shoot(auto)";
				fallbackGroups = MeleeAttackGroupPreference;
				fallbackLabel = "melee";
				return ShootAttackGroupPreference;
			}

			familyLabel = "melee(auto)";
			fallbackGroups = ShootAttackGroupPreference;
			fallbackLabel = "shoot";
			return MeleeAttackGroupPreference;
		}

		/// <summary>Swap MeshRenderer shared material slot 0 per frame (Sprites/Default + _MainTex).</summary>
		static AnimationClip BuildMaterialSwapClipSequential(string clipName, IList<Material> mats, float fps, bool loop)
		{
			if (mats == null || mats.Count == 0)
				throw new InvalidOperationException("Homm3BillboardAnimatorBuild: clip '" + clipName + "' has no keyframes.");

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
		static bool ApplyBattleFramePngImportSettings() => ApplyFolderPngMeshBillboardImport(FramesFolder);

		/// <returns>True when at least one PNG was reimported (caller should Refresh).</returns>
		static bool ApplyFolderPngMeshBillboardImport(string folder)
		{
			folder = folder?.Replace('\\', '/').Trim();
			if (string.IsNullOrEmpty(folder) || !AssetDatabase.IsValidFolder(folder))
			{
				Debug.LogWarning("Homm3BillboardAnimatorBuild: skip PNG import — folder missing: " + folder);
				return false;
			}

			if (s_meshBillboardImportConfiguredFolders.Contains(folder))
				return false;

			var reimported = 0;
			var alreadyOk = 0;
			AssetDatabase.StartAssetEditing();
			try
			{
				foreach (var guid in AssetDatabase.FindAssets("", new[] { folder }))
				{
					var path = AssetDatabase.GUIDToAssetPath(guid);
					if (!path.EndsWith(".png", StringComparison.OrdinalIgnoreCase))
						continue;
					if (!(AssetImporter.GetAtPath(path) is TextureImporter importer))
						continue;
					if (ImporterAlreadyConfiguredForMeshBillboardFrame(importer))
					{
						alreadyOk++;
						continue;
					}

					ConfigureImporterForMeshBillboardFrame(importer);
					importer.SaveAndReimport();
					reimported++;
				}
			}
			finally
			{
				AssetDatabase.StopAssetEditing();
			}

			s_meshBillboardImportConfiguredFolders.Add(folder);
			Debug.Log(
				"Homm3BillboardAnimatorBuild: battle PNG import "
				+ folder
				+ " (reimported "
				+ reimported
				+ ", already OK "
				+ alreadyOk
				+ ")");
			return reimported > 0;
		}

		static bool ImporterAlreadyConfiguredForMeshBillboardFrame(TextureImporter importer)
		{
			if (importer.textureType != TextureImporterType.Default)
				return false;
			if (importer.textureShape != TextureImporterShape.Texture2D)
				return false;
			if (!importer.sRGBTexture)
				return false;
			if (importer.alphaSource != TextureImporterAlphaSource.FromInput)
				return false;
			if (!importer.alphaIsTransparency)
				return false;
			if (importer.mipmapEnabled)
				return false;
			if (importer.filterMode != FilterMode.Point)
				return false;
			if (importer.wrapMode != TextureWrapMode.Clamp)
				return false;
			if (importer.npotScale != TextureImporterNPOTScale.None)
				return false;
			var plat = importer.GetPlatformTextureSettings("DefaultTexturePlatform");
			if (plat == null || plat.textureCompression != TextureImporterCompression.Uncompressed)
				return false;
			return !plat.crunchedCompression;
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
					"Homm3BillboardAnimatorBuild: "
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
			mr.sharedMaterials = new[] { quadMaterial };
			EditorUtility.SetDirty(mf);
			EditorUtility.SetDirty(mr);
			EditorUtility.SetDirty(quadGo);
			EditorUtility.SetDirty(root);

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
