// Option D prototype: Texture2DArray battle billboards (h3_gnoll, h3_lizardman).
// Deploy shader: tools/homm3_import/build_homm3_array_prototype.cmd copies unity_shaders → Assets/Shaders.

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Globalization;
using System.Text;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

namespace OldenEra.Homm3Import
{
	[Serializable]
	sealed class Homm3BattleArrayGroupDef
	{
		public int group;
		public int startIndex;
		public int length;
	}

	[Serializable]
	sealed class Homm3BattleArrayClipDef
	{
		public string name;
		public int[] indices;
		public float fps;
		public int loop;
		public int attackBaseGroup = -1;
	}

	[Serializable]
	sealed class Homm3BattleArrayManifestData
	{
		public string unitSid;
		public int frameCount;
		public int arrayChunkSize;
		public int arrayCount;
		public int baseAttackGroup;
		public Homm3BattleArrayGroupDef[] attackGroups;
		public Homm3BattleArrayClipDef[] clips;
	}

	public static partial class Homm3BillboardAnimatorBuild
	{
		const string ArrayRel = "Array";
		const string ArrayManifestFileName = "array_battle_manifest.json";
		const string ArrayTextureAssetName = "battle_frames_array.asset";
		const string ArrayMaterialAssetName = "battle_array.mat";
		const string ArrayShaderPath = "Assets/Shaders/Homm3BillboardArray.shader";
		const string ArrayTimingChildName = "__homm3_array_timing";
		const int MaxTexture2DArraySlices = 2048;
		static TextureFormat BattleArrayStoredFormat =>
			SystemInfo.SupportsTextureFormat(TextureFormat.BC7) ? TextureFormat.BC7 : TextureFormat.DXT5;
		static readonly string[] ArrayTexturePropertyNames =
		{
			"_MainTexArray",
			"_MainTexArray1",
			"_MainTexArray2",
			"_MainTexArray3",
		};

		static bool UseBattleTexture2DArray() =>
			_authoring != null && (_authoring.battleTexture2DArray != 0 || s_forceBattleTexture2DArray);

		static void RebuildBattleTexture2DArray(
			DefExtractManifest manifest,
			Material template,
			AnimatorController baseController)
		{
			var framesRoot = FramesFolder;
			var pathToGlobalIndex = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
			var globalPaths = new List<string>();

			int IndexFor(string rel)
			{
				rel = rel?.Replace('\\', '/');
				if (string.IsNullOrEmpty(rel))
					throw new InvalidOperationException("Empty frame path in manifest.");
				if (!pathToGlobalIndex.TryGetValue(rel, out var idx))
				{
					idx = globalPaths.Count;
					globalPaths.Add(rel);
					pathToGlobalIndex[rel] = idx;
				}
				return idx;
			}

			void TouchGroup(int groupId)
			{
				foreach (var rel in GetExistingRelativeFramePathsForGroup(manifest, groupId))
					IndexFor(rel);
			}

			TouchGroup(GroupIdle);
			TouchGroup(GroupMovement);
			TouchGroup(GroupMouseOver);
			TouchGroup(GroupHitted);
			TouchGroup(GroupDeath);
			foreach (var g in MeleeAttackGroupPreference)
				TouchGroup(g);
			foreach (var g in ShootAttackGroupPreference)
				TouchGroup(g);
			TouchGroup(GroupTeleportLeave);
			TouchGroup(GroupTeleportArrive);

			if (globalPaths.Count == 0)
				throw new InvalidOperationException("Texture2DArray battle build: no frames indexed for " + _authoring.unitSid);

			var arrayFolder = $"{GeneratedRoot}/{ArrayRel}";
			EnsureFolder(arrayFolder);
			if (AssetDatabase.IsValidFolder($"{GeneratedRoot}/{MaterialsRel}"))
				ClearSubfolders($"{GeneratedRoot}/{MaterialsRel}");
			ClearSubfolders($"{GeneratedRoot}/{ClipsRel}", arrayFolder);

			var matAssetPath = $"{arrayFolder}/{ArrayMaterialAssetName}";
			var manifestPath = $"{GeneratedRoot}/{ArrayManifestFileName}";

			foreach (var asset in AssetDatabase.FindAssets("t:Texture2DArray", new[] { arrayFolder }))
			{
				var path = AssetDatabase.GUIDToAssetPath(asset);
				if (!string.IsNullOrEmpty(path))
					AssetDatabase.DeleteAsset(path);
			}
			if (AssetDatabase.LoadAssetAtPath<Material>(matAssetPath))
				AssetDatabase.DeleteAsset(matAssetPath);
			if (AssetDatabase.LoadAssetAtPath<TextAsset>(manifestPath))
				AssetDatabase.DeleteAsset(manifestPath);

			var textures = LoadTexturesForRelativePaths(globalPaths);
			List<Texture2DArray> arrayChunks;
			try
			{
				arrayChunks = BuildTexture2DArrayAssetsChunked(textures, arrayFolder);
			}
			finally
			{
				ReleaseTransientBattleSourceTextures(textures);
			}
			if (arrayChunks.Count > ArrayTexturePropertyNames.Length)
				throw new InvalidOperationException(
					"Texture2DArray battle build: "
					+ textures.Count
					+ " frames need "
					+ arrayChunks.Count
					+ " arrays (max "
					+ ArrayTexturePropertyNames.Length
					+ " supported).");

			var arrayShader = Shader.Find("OldenEra/Homm3/BillboardArray");
			if (arrayShader == null)
				throw new InvalidOperationException(
					"Shader OldenEra/Homm3/BillboardArray missing. Run build_homm3_array_prototype.cmd to copy Homm3BillboardArray.shader into Assets/Shaders.");

			var arrayMaterial = new Material(arrayShader);
			arrayMaterial.name = "homm3_battle_array";
			arrayMaterial.SetFloat("_ArraySliceSize", MaxTexture2DArraySlices);
			for (var i = 0; i < arrayChunks.Count; i++)
				arrayMaterial.SetTexture(ArrayTexturePropertyNames[i], arrayChunks[i]);
			AssetDatabase.CreateAsset(arrayMaterial, matAssetPath);

			var attackGroups = BuildAttackGroupDefs(manifest, pathToGlobalIndex);
			var baseAttackGroup = ResolveBaseAttackGroupForManifest(manifest);
			var manifestData = new Homm3BattleArrayManifestData
			{
				unitSid = _authoring.unitSid,
				frameCount = globalPaths.Count,
				arrayChunkSize = MaxTexture2DArraySlices,
				arrayCount = arrayChunks.Count,
				baseAttackGroup = baseAttackGroup,
				attackGroups = attackGroups.ToArray()
			};

			var generatedByName = new Dictionary<string, AnimationClip>(StringComparer.Ordinal);
			var logGroups = new StringBuilder();
			logGroups.AppendLine("Homm3BillboardAnimatorBuild: Texture2DArray battle path for " + _authoring.unitSid);

			manifestData.clips = new[]
			{
				BuildArrayClipDef("22.Idle", manifest, GroupIdle, FlipBookFps, true, -1, pathToGlobalIndex, generatedByName, logGroups),
				BuildArrayClipDefMovement("01.Walk", manifest, FlipBookFps, true, pathToGlobalIndex, generatedByName, logGroups),
				BuildArrayClipDefAttack("14.Attack", manifest, FlipBookFps, baseAttackGroup, pathToGlobalIndex, generatedByName, logGroups),
				BuildArrayClipDef("20.Damage", manifest, GroupHitted, FlipBookFps, false, -1, pathToGlobalIndex, generatedByName, logGroups),
				BuildArrayClipDef("21.Death", manifest, GroupDeath, DeathClipFps, false, -1, pathToGlobalIndex, generatedByName, logGroups)
			};

			var meleeAlt = BuildArrayMeleeAlternativeClipDef(manifest, FlipBookFps, pathToGlobalIndex, generatedByName, logGroups);
			if (meleeAlt != null)
			{
				var list = manifestData.clips.ToList();
				list.Add(meleeAlt);
				manifestData.clips = list.ToArray();
			}

			if (ShouldUseTeleportDiveMovement(_authoring.unitSid, manifest))
			{
				var list = manifestData.clips.ToList();
				list.Add(BuildArrayClipDef("10.Tp_Start", manifest, GroupTeleportLeave, FlipBookFps, false, -1, pathToGlobalIndex, generatedByName, logGroups));
				list.Add(BuildArrayClipDef("11.Tp_End", manifest, GroupTeleportArrive, FlipBookFps, false, -1, pathToGlobalIndex, generatedByName, logGroups));
				list.Add(BuildArrayClipDef("12.Tp_Ability_Start", manifest, GroupTeleportLeave, FlipBookFps, false, -1, pathToGlobalIndex, generatedByName, logGroups));
				list.Add(BuildArrayClipDef("13.Tp_Ability_End", manifest, GroupTeleportArrive, FlipBookFps, false, -1, pathToGlobalIndex, generatedByName, logGroups));
				manifestData.clips = list.ToArray();
			}

			Debug.Log(logGroups.ToString().TrimEnd());

			var json = JsonUtility.ToJson(manifestData, true);
			var projectRoot = Path.GetDirectoryName(Application.dataPath) ?? "";
			var manifestFullPath = Path.Combine(projectRoot, manifestPath.Replace('/', Path.DirectorySeparatorChar));
			Directory.CreateDirectory(Path.GetDirectoryName(manifestFullPath) ?? projectRoot);
			File.WriteAllText(manifestFullPath, json);
			AssetDatabase.ImportAsset(manifestPath, ImportAssetOptions.ForceUpdate);
			CopyArrayManifestToOfflineLab(manifestFullPath);

			ApplyAnimatorOverrideController(baseController, generatedByName);
			AssignArrayMaterialToBattlePrefab(arrayMaterial);

			Debug.Log(
				"Homm3BillboardAnimatorBuild: Texture2DArray battle build complete sid="
				+ _authoring.unitSid
				+ " frames="
				+ globalPaths.Count
				+ " arrays="
				+ arrayChunks.Count);
		}

		static List<Texture2DArray> BuildTexture2DArrayAssetsChunked(
			List<Texture2D> textures,
			string arrayFolder)
		{
			var chunks = new List<Texture2DArray>();
			for (var start = 0; start < textures.Count; start += MaxTexture2DArraySlices)
			{
				var count = Mathf.Min(MaxTexture2DArraySlices, textures.Count - start);
				var slice = textures.GetRange(start, count);
				var assetPath = $"{arrayFolder}/battle_frames_array_{chunks.Count}.asset";
				chunks.Add(BuildTexture2DArrayAsset(slice, assetPath));
			}
			return chunks;
		}

		static List<Texture2D> LoadTexturesForRelativePaths(List<string> globalPaths)
		{
			var parent = Path.GetDirectoryName(FramesFolder.Replace('\\', '/'))?.Replace('\\', '/');
			if (string.IsNullOrEmpty(parent))
				throw new InvalidOperationException("Invalid FramesFolder: " + FramesFolder);
			var list = new List<Texture2D>(globalPaths.Count);
			foreach (var rel in globalPaths)
			{
				var tex = FirstTexture2DAtPath($"{parent}/{rel}");
				if (tex == null)
					throw new InvalidOperationException("Texture2DArray build: missing texture at " + parent + "/" + rel);
				list.Add(tex);
			}
			return list;
		}

		static List<string> GetExistingRelativeFramePathsForGroup(DefExtractManifest manifest, int groupId)
		{
			var parent = Path.GetDirectoryName(FramesFolder.Replace('\\', '/'))?.Replace('\\', '/');
			if (string.IsNullOrEmpty(parent))
				throw new InvalidOperationException("Invalid FramesFolder: " + FramesFolder);
			return GetRelativeFramePathsForGroup(manifest, groupId)
				.Select(p => p?.Replace('\\', '/'))
				.Where(p => !string.IsNullOrEmpty(p) && FirstTexture2DAtPath($"{parent}/{p}") != null)
				.ToList();
		}

		static void ReleaseTransientBattleSourceTextures(List<Texture2D> textures)
		{
			if (textures == null)
				return;
			foreach (var tex in textures)
			{
				if (tex == null)
					continue;
				// Only destroy textures we created for disk-load; AssetDatabase textures must stay.
				if (!string.IsNullOrEmpty(AssetDatabase.GetAssetPath(tex)))
					continue;
				UnityEngine.Object.DestroyImmediate(tex);
			}
			textures.Clear();
		}

		static Texture2DArray BuildTexture2DArrayAsset(List<Texture2D> textures, string assetPath)
		{
			var srcW = 0;
			var srcH = 0;
			foreach (var tex in textures)
			{
				srcW = Mathf.Max(srcW, tex.width);
				srcH = Mathf.Max(srcH, tex.height);
			}
			if (srcW <= 0 || srcH <= 0)
				throw new InvalidOperationException("Texture2DArray build: invalid texture dimensions.");

			// BC7/DXT require dimensions that are multiples of 4. Round up and blit-scale every
			// frame into the padded size (sub-1% stretch); UVs stay 0..1 so no runtime change.
			var storedFormat = BattleArrayStoredFormat;
			var blockCompressed = storedFormat != TextureFormat.RGBA32;
			var w = blockCompressed ? RoundUpToMultiple(srcW, 4) : srcW;
			var h = blockCompressed ? RoundUpToMultiple(srcH, 4) : srcH;

			// EditorUtility.CompressTexture only accepts Texture2D, so compress each slice
			// as a Texture2D and CopyTexture (compressed->compressed) into a BC7/DXT5 array.
			var totalSw = System.Diagnostics.Stopwatch.StartNew();
			long compressMs = 0;
			var array = new Texture2DArray(w, h, textures.Count, storedFormat, false, false);
			array.filterMode = FilterMode.Point;
			array.wrapMode = TextureWrapMode.Clamp;
			for (var i = 0; i < textures.Count; i++)
			{
				var slice = CreateReadableRgbaSlice(textures[i], w, h, out var ownsSlice);
				try
				{
					if (blockCompressed)
					{
						var compressSw = System.Diagnostics.Stopwatch.StartNew();
						EditorUtility.CompressTexture(slice, storedFormat, TextureCompressionQuality.Normal);
						compressMs += compressSw.ElapsedMilliseconds;
						// SetPixelData copies the compressed bytes into the array's CPU buffer so
						// CreateAsset serializes real image data. Graphics.CopyTexture is GPU-only and
						// left the serialized .asset empty -> units rendered as white quads.
						var raw = slice.GetRawTextureData<byte>();
						array.SetPixelData(raw, 0, i);
					}
					else
					{
						// RGBA32 fallback (no BC7/DXT5 support): also use SetPixelData so the
						// array's CPU buffer is populated. Graphics.CopyTexture is GPU-only and
						// would serialize empty slices, reproducing the white-quad bug.
						var raw = slice.GetRawTextureData<byte>();
						array.SetPixelData(raw, 0, i);
					}
				}
				finally
				{
					if (ownsSlice)
						UnityEngine.Object.DestroyImmediate(slice);
				}
			}
			// makeNoLongerReadable:false so CreateAsset serializes the array's pixel data.
			// Passing true here discarded the CPU buffer and made units render as white quads.
			array.Apply(false, false);
			var packMs = totalSw.ElapsedMilliseconds;
			totalSw.Restart();
			AssetDatabase.CreateAsset(array, assetPath);
			var createAssetMs = totalSw.ElapsedMilliseconds;
			var projectRoot = Path.GetDirectoryName(Application.dataPath) ?? "";
			var fsPath = Path.Combine(projectRoot, assetPath.Replace('/', Path.DirectorySeparatorChar));
			long assetBytes = 0;
			if (File.Exists(fsPath))
				assetBytes = new FileInfo(fsPath).Length;
			UnityEngine.Debug.Log(
				"HOMM3_ARRAY_BUILD_PROFILE"
				+ " path="
				+ assetPath
				+ " frames="
				+ textures.Count
				+ " size="
				+ w
				+ "x"
				+ h
				+ " format="
				+ storedFormat
				+ " packMs="
				+ packMs
				+ " compressMs="
				+ compressMs
				+ " createAssetMs="
				+ createAssetMs
				+ " assetBytes="
				+ assetBytes);
			return array;
		}

		static int RoundUpToMultiple(int value, int multiple) =>
			multiple <= 1 ? value : ((value + multiple - 1) / multiple) * multiple;

		/// <summary>
		/// Owned, readable RGBA32 copy of <paramref name="source"/> sized to <paramref name="w"/>×<paramref name="h"/>.
		/// Never mutates the imported PNG asset (EditorUtility.CompressTexture edits in place).
		/// </summary>
		static Texture2D CreateReadableRgbaSlice(Texture2D source, int w, int h, out bool owns)
		{
			owns = true;
			// CPU-only path. The build runs under `-batchmode -nographics`, where Graphics.Blit /
			// ReadPixels / GPU CopyTexture have no graphics device and return empty data — which
			// BC7-compresses to white quads. Decode the PNG on the CPU and pad with SetPixels32 so
			// the slice is correct without any GPU operation.
			var srcPixels = LoadSourcePixelsCpu(source, out var srcW, out var srcH);
			var dst = new Color32[w * h]; // default Color32 is (0,0,0,0) — transparent padding.
			if (srcPixels != null)
			{
				var copyW = Mathf.Min(srcW, w);
				var copyH = Mathf.Min(srcH, h);
				// Unity Color32 buffers are bottom-up row-major; copy into the bottom-left so any
				// width/height padding lands on the top/right edge (UVs stay 0..1, sub-1% stretch).
				for (var y = 0; y < copyH; y++)
				{
					var srcRow = y * srcW;
					var dstRow = y * w;
					for (var x = 0; x < copyW; x++)
						dst[dstRow + x] = srcPixels[srcRow + x];
				}
			}
			var temp = new Texture2D(w, h, TextureFormat.RGBA32, false);
			temp.SetPixels32(dst);
			temp.Apply(false, false);
			return temp;
		}

		/// <summary>
		/// Reads a source frame's pixels on the CPU (no GPU), so it works under -nographics.
		/// Prefers decoding the PNG bytes from disk via ImageConversion.LoadImage (always readable
		/// RGBA32, importer-independent); falls back to GetPixels32 if the asset is already readable.
		/// </summary>
		static Color32[] LoadSourcePixelsCpu(Texture2D source, out int w, out int h)
		{
			w = 0;
			h = 0;
			if (source == null)
				return null;
			var assetPath = AssetDatabase.GetAssetPath(source);
			if (!string.IsNullOrEmpty(assetPath))
			{
				var projectRoot = Path.GetDirectoryName(Application.dataPath) ?? "";
				var fsPath = Path.Combine(projectRoot, assetPath.Replace('/', Path.DirectorySeparatorChar));
				if (File.Exists(fsPath))
				{
					var bytes = File.ReadAllBytes(fsPath);
					var decoded = new Texture2D(2, 2, TextureFormat.RGBA32, false);
					try
					{
						if (ImageConversion.LoadImage(decoded, bytes, false))
						{
							w = decoded.width;
							h = decoded.height;
							return decoded.GetPixels32();
						}
					}
					finally
					{
						UnityEngine.Object.DestroyImmediate(decoded);
					}
				}
			}
			if (source.isReadable)
			{
				w = source.width;
				h = source.height;
				return source.GetPixels32();
			}
			throw new InvalidOperationException(
				"Texture2DArray build: cannot read source pixels on CPU for '"
				+ assetPath
				+ "' (not found on disk and not CPU-readable).");
		}

		static List<Homm3BattleArrayGroupDef> BuildAttackGroupDefs(
			DefExtractManifest manifest,
			Dictionary<string, int> pathToGlobalIndex)
		{
			var groups = new HashSet<int>();
			foreach (var g in MeleeAttackGroupPreference)
				groups.Add(g);
			foreach (var g in ShootAttackGroupPreference)
				groups.Add(g);
			var list = new List<Homm3BattleArrayGroupDef>();
			foreach (var groupId in groups.OrderBy(x => x))
			{
				var rel = GetExistingRelativeFramePathsForGroup(manifest, groupId);
				if (rel.Count == 0)
					continue;
				var start = pathToGlobalIndex[rel[0].Replace('\\', '/')];
				list.Add(new Homm3BattleArrayGroupDef
				{
					group = groupId,
					startIndex = start,
					length = rel.Count
				});
			}
			return list;
		}

		static int ResolveBaseAttackGroupForManifest(DefExtractManifest manifest)
		{
			var tryGroups = PreferredAttackGroupPreference(manifest, out _, out _, out _);
			foreach (var g in tryGroups)
			{
				if (GetExistingRelativeFramePathsForGroup(manifest, g).Count > 0)
					return g;
			}
			return GroupAttackFront;
		}

		static Homm3BattleArrayClipDef BuildArrayClipDef(
			string clipName,
			DefExtractManifest manifest,
			int groupId,
			float fps,
			bool loop,
			int attackBaseGroup,
			Dictionary<string, int> pathToGlobalIndex,
			Dictionary<string, AnimationClip> generatedByName,
			StringBuilder logGroups)
		{
			var relFrames = GetExistingRelativeFramePathsForGroup(manifest, groupId);
			if (relFrames.Count == 0)
				throw new InvalidOperationException("Array clip '" + clipName + "' group " + groupId + " has no frames.");
			logGroups.Append("  ").Append(clipName).Append(" ← group ").Append(groupId).Append(" (").Append(relFrames.Count).Append(" frames, array)").AppendLine();
			var indices = relFrames.Select(r => pathToGlobalIndex[r.Replace('\\', '/')]).ToArray();
			var clip = CreateArrayTimingClip(clipName, indices.Length, fps, loop);
			AssetDatabase.CreateAsset(clip, $"{GeneratedRoot}/{ClipsRel}/{clipName}.anim");
			generatedByName[clipName] = clip;
			return new Homm3BattleArrayClipDef
			{
				name = clipName,
				indices = indices,
				fps = fps,
				loop = loop ? 1 : 0,
				attackBaseGroup = attackBaseGroup
			};
		}

		static Homm3BattleArrayClipDef BuildArrayClipDefMovement(
			string clipName,
			DefExtractManifest manifest,
			float fps,
			bool loop,
			Dictionary<string, int> pathToGlobalIndex,
			Dictionary<string, AnimationClip> generatedByName,
			StringBuilder logGroups)
		{
			List<string> relFrames;
			int groupId;
			if (GetExistingRelativeFramePathsForGroup(manifest, GroupMovement).Count > 0)
			{
				relFrames = GetExistingRelativeFramePathsForGroup(manifest, GroupMovement);
				groupId = GroupMovement;
			}
			else
			{
				relFrames = GetExistingRelativeFramePathsForGroup(manifest, GroupMouseOver);
				groupId = GroupMouseOver;
			}
			if (relFrames.Count == 0)
				relFrames = GetExistingRelativeFramePathsForGroup(manifest, GroupIdle);
			if (relFrames.Count == 0)
				throw new InvalidOperationException("Array movement clip has no frames.");
			logGroups.Append("  ").Append(clipName).Append(" ← group ").Append(groupId).Append(" (").Append(relFrames.Count).Append(" frames, array)").AppendLine();
			var indices = relFrames.Select(r => pathToGlobalIndex[r.Replace('\\', '/')]).ToArray();
			var clip = CreateArrayTimingClip(clipName, indices.Length, fps, loop);
			AssetDatabase.CreateAsset(clip, $"{GeneratedRoot}/{ClipsRel}/{clipName}.anim");
			generatedByName[clipName] = clip;
			return new Homm3BattleArrayClipDef { name = clipName, indices = indices, fps = fps, loop = loop ? 1 : 0, attackBaseGroup = -1 };
		}

		static Homm3BattleArrayClipDef BuildArrayClipDefAttack(
			string clipName,
			DefExtractManifest manifest,
			float fps,
			int attackBaseGroup,
			Dictionary<string, int> pathToGlobalIndex,
			Dictionary<string, AnimationClip> generatedByName,
			StringBuilder logGroups)
		{
			var relFrames = GetExistingRelativeFramePathsForGroup(manifest, attackBaseGroup);
			if (relFrames.Count == 0)
				throw new InvalidOperationException("Array attack clip missing group " + attackBaseGroup);
			logGroups.Append("  ").Append(clipName).Append(" ← group ").Append(attackBaseGroup).Append(" (").Append(relFrames.Count).Append(" frames, array)").AppendLine();
			var indices = relFrames.Select(r => pathToGlobalIndex[r.Replace('\\', '/')]).ToArray();
			var clip = CreateArrayTimingClip(clipName, indices.Length, fps, false);
			AssetDatabase.CreateAsset(clip, $"{GeneratedRoot}/{ClipsRel}/{clipName}.anim");
			generatedByName[clipName] = clip;
			return new Homm3BattleArrayClipDef
			{
				name = clipName,
				indices = indices,
				fps = fps,
				loop = 0,
				attackBaseGroup = attackBaseGroup
			};
		}

		static Homm3BattleArrayClipDef BuildArrayMeleeAlternativeClipDef(
			DefExtractManifest manifest,
			float fps,
			Dictionary<string, int> pathToGlobalIndex,
			Dictionary<string, AnimationClip> generatedByName,
			StringBuilder logGroups)
		{
			if (!ManifestHasGroupFrames(manifest, ShootAttackGroupPreference)
			    || !ManifestHasGroupFrames(manifest, MeleeAttackGroupPreference))
				return null;
			for (var gi = 0; gi < MeleeAttackGroupPreference.Length; gi++)
			{
				var g = MeleeAttackGroupPreference[gi];
				var relFrames = GetExistingRelativeFramePathsForGroup(manifest, g);
				if (relFrames.Count == 0)
					continue;
				logGroups.Append("  15.Skill_1 ← group ").Append(g).Append(" (").Append(relFrames.Count).Append(" frames, array)").AppendLine();
				var indices = relFrames.Select(r => pathToGlobalIndex[r.Replace('\\', '/')]).ToArray();
				var clip = CreateArrayTimingClip("15.Skill_1", indices.Length, fps, false);
				AssetDatabase.CreateAsset(clip, $"{GeneratedRoot}/{ClipsRel}/15.Skill_1.anim");
				generatedByName["15.Skill_1"] = clip;
				return new Homm3BattleArrayClipDef
				{
					name = "15.Skill_1",
					indices = indices,
					fps = fps,
					loop = 0,
					attackBaseGroup = g
				};
			}
			return null;
		}

		static AnimationClip CreateArrayTimingClip(string clipName, int frameCount, float fps, bool loop)
		{
			var duration = frameCount <= 1 ? 1f / Mathf.Max(1f, fps) : (frameCount - 1) / Mathf.Max(1f, fps);
			var clip = new AnimationClip { name = clipName, frameRate = Mathf.Max(1f, fps) };
			// Animate an invisible built-in Transform child for clip timing. AssetBundles cannot resolve
			// editor-project MonoBehaviours in the IL2CPP game, and missing scripts invalidate controllers.
			var curve = AnimationCurve.Linear(0f, 0f, duration, 1f);
			var binding = EditorCurveBinding.FloatCurve(ArrayTimingChildName, typeof(Transform), "m_LocalPosition.x");
			AnimationUtility.SetEditorCurve(clip, binding, curve);
			var settings = AnimationUtility.GetAnimationClipSettings(clip);
			settings.loopTime = loop;
			AnimationUtility.SetAnimationClipSettings(clip, settings);
			return clip;
		}

		static void ApplyAnimatorOverrideController(AnimatorController baseController, Dictionary<string, AnimationClip> generatedByName)
		{
			var overrideController = new AnimatorOverrideController();
			AssetDatabase.CreateAsset(overrideController, OverrideOutputPath);
			overrideController.runtimeAnimatorController = baseController;
			EditorUtility.SetDirty(overrideController);
			AssetDatabase.SaveAssets();
			var overrides = new List<KeyValuePair<AnimationClip, AnimationClip>>();
			overrideController.GetOverrides(overrides);
			var replaced = 0;
			for (var i = 0; i < overrides.Count; i++)
			{
				var orig = overrides[i].Key;
				if (orig == null)
					continue;
				if (!TryResolveArrayOverrideClip(orig, generatedByName, out var replacement) || replacement == null)
					continue;
				overrides[i] = new KeyValuePair<AnimationClip, AnimationClip>(orig, replacement);
				replaced++;
			}
			overrideController.ApplyOverrides(overrides);
			EditorUtility.SetDirty(overrideController);
		}

		static bool TryResolveArrayOverrideClip(
			AnimationClip original,
			Dictionary<string, AnimationClip> generatedByName,
			out AnimationClip replacement)
		{
			replacement = null;
			if (!original || generatedByName == null)
				return false;
			if (generatedByName.TryGetValue(original.name, out replacement) && replacement)
				return true;
			var n = original.name.ToLowerInvariant();
			if ((n.Contains("fly")
			     || n.Contains("walk")
			     || n.Contains("move")
			     || n.Contains("run")
			     || n.Contains("teleport")
			     || n.Contains("tp_start")
			     || n.Contains("tp_end")
			     || n.Contains("tp_ability"))
			    && generatedByName.TryGetValue("01.Walk", out replacement)
			    && replacement)
				return true;
			if ((n.Contains("attack") || n.Contains("atk") || n.Contains("shoot"))
			    && generatedByName.TryGetValue("14.Attack", out replacement)
			    && replacement)
				return true;
			if ((n.Contains("damage") || n.Contains("hit") || n.Contains("wound") || n.Contains("wnce"))
			    && generatedByName.TryGetValue("20.Damage", out replacement)
			    && replacement)
				return true;
			if ((n.Contains("death") || n.Contains("die"))
			    && generatedByName.TryGetValue("21.Death", out replacement)
			    && replacement)
				return true;
			if (generatedByName.TryGetValue("22.Idle", out replacement) && replacement)
				return true;
			return false;
		}

		static void AssignArrayMaterialToBattlePrefab(Material arrayMaterial)
		{
			var battle = AssetDatabase.LoadAssetAtPath<GameObject>(BattlePrefabPath);
			if (battle == null)
				throw new InvalidOperationException("battle.prefab missing: " + BattlePrefabPath);
			if (s_applyBattleQuadDefaultsThisRun)
				ApplyBattleQuadAuthoringDefaults(battle);
			var quad = battle.transform.Find(QuadRendererPath);
			if (quad == null)
				throw new InvalidOperationException("battle.prefab missing " + QuadRendererPath);
			var renderer = quad.GetComponent<MeshRenderer>();
			if (renderer == null)
				throw new InvalidOperationException("battle quad missing MeshRenderer.");
			renderer.sharedMaterial = arrayMaterial;
			var animator = battle.GetComponent<Animator>();
			if (animator == null)
				throw new InvalidOperationException("Animator missing on battle.prefab root.");
			RemoveArrayTimingChannelIfPresent(battle);
			EnsureArrayTimingChild(battle);
			var finalOverride = AssetDatabase.LoadAssetAtPath<AnimatorOverrideController>(OverrideOutputPath);
			if (finalOverride == null)
				throw new InvalidOperationException("Override controller missing at " + OverrideOutputPath);
			animator.runtimeAnimatorController = finalOverride;
			animator.applyRootMotion = false;
			EditorUtility.SetDirty(battle);
			PrefabUtility.SavePrefabAsset(battle);
		}

		static void EnsureArrayTimingChild(GameObject battle)
		{
			var existing = battle.transform.Find(ArrayTimingChildName);
			if (existing != null)
				return;
			var child = new GameObject(ArrayTimingChildName);
			child.transform.SetParent(battle.transform, false);
			child.transform.localPosition = Vector3.zero;
			child.transform.localRotation = Quaternion.identity;
			child.transform.localScale = Vector3.one;
		}

		static void RemoveArrayTimingChannelIfPresent(GameObject battle)
		{
			var channels = battle.GetComponents<Homm3ArrayTimingChannel>();
			if (channels == null)
				return;
			for (var i = 0; i < channels.Length; i++)
			{
				if (channels[i] != null)
					UnityEngine.Object.DestroyImmediate(channels[i], true);
			}
		}

		static float ResolveBattlePlaybackFps()
		{
			if (_authoring == null)
				return 60f;
			var fromRife = TryReadRifeTargetFpsForAuthoringUnit(_authoring.unitSid);
			if (fromRife > 0f)
				return fromRife;
			if (_authoring.flipBookFps > 0f)
				return _authoring.flipBookFps;
			return 60f;
		}

		static float ResolveBattleDeathPlaybackFps()
		{
			var playback = ResolveBattlePlaybackFps();
			if (_authoring == null)
				return playback;
			if (_authoring.deathClipFps > 0f
			    && Mathf.Abs(_authoring.deathClipFps - _authoring.flipBookFps) < 0.01f)
				return playback;
			if (_authoring.deathClipFps > 0f)
				return _authoring.deathClipFps;
			return playback;
		}

		static float TryReadRifeTargetFpsForAuthoringUnit(string unitSid)
		{
			if (string.IsNullOrEmpty(unitSid))
				return 0f;
			// .rife120_done.json `targetFps` is the source of truth for playback FPS and must win over a
			// possibly-stale authoring.flipBookFps. Check the mirrored Unity lab first (where frames live in
			// THIS project), then the source-plugin layouts. The old single path assumed the OfflineUnlockMod
			// folder sat under the Unity project root, which is false for V:\homm3_unity_work — so it always
			// fell back to stale authoring fps and baked timing clips at the wrong rate.
			var projectRoot = Path.GetDirectoryName(Application.dataPath) ?? "";
			var repoRoot = Path.GetFullPath(Path.Combine(Application.dataPath, "..", ".."));
			var candidates = new[]
			{
				Path.Combine(Application.dataPath, "CustomUnits", "homm3_lab", unitSid, "extracted_battle", ".rife120_done.json"),
				Path.Combine(projectRoot, "Heroes of Might & Magic Olden Era Playtest", "OfflineUnlockMod", "homm3_lab", unitSid, "extracted_battle", ".rife120_done.json"),
				Path.Combine(repoRoot, "Heroes of Might & Magic Olden Era Playtest", "OfflineUnlockMod", "homm3_lab", unitSid, "extracted_battle", ".rife120_done.json")
			};
			foreach (var path in candidates)
			{
				if (!File.Exists(path))
					continue;
				try
				{
					var root = JObject.Parse(File.ReadAllText(path));
					if (root["targetFps"] != null
					    && float.TryParse(root["targetFps"].ToString(), NumberStyles.Float, CultureInfo.InvariantCulture, out var top)
					    && top > 0f)
						return top;
				}
				catch
				{
					// Try the next candidate location.
				}
			}
			return 0f;
		}

		static void CopyArrayManifestToOfflineLab(string manifestFullPath)
		{
			if (string.IsNullOrEmpty(_authoring?.unitSid) || !File.Exists(manifestFullPath))
				return;
			var repoRoot = Path.GetFullPath(Path.Combine(Application.dataPath, "..", ".."));
			var offlineRoot = Path.Combine(
				repoRoot,
				"Heroes of Might & Magic Olden Era Playtest",
				"OfflineUnlockMod",
				"homm3_lab",
				_authoring.unitSid,
				"Generated",
				"BillboardAnim");
			Directory.CreateDirectory(offlineRoot);
			File.Copy(manifestFullPath, Path.Combine(offlineRoot, ArrayManifestFileName), overwrite: true);
		}
	}
}
