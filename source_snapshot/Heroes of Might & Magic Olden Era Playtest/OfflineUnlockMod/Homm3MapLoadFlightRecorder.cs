using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading;
using BepInEx;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace OfflineUnlockMod;

internal static class Homm3MapLoadFlightRecorder
{
	internal const string FlagFileName = "homm3_map_load_flight_recorder.flag";
	internal const string DisableUnitViewMapSwapsFlag = "homm3_diag_disable_unitview_map_swaps.flag";
	internal const string DisableMapArrayPilotsFlag = "homm3_diag_disable_map_array_pilots.flag";
	internal const string DisableNativeShellTransplantFlag = "homm3_diag_disable_native_shell_transplant.flag";
	internal const string DisableCustomBiomeRegistrationFlag = "homm3_diag_disable_custom_biome_registration.flag";
	internal const string DisableTerrainRendererRegistrationFlag = "homm3_diag_disable_terrain_renderer_registration.flag";
	internal const string DisableTerrainSoundRegistrationFlag = "homm3_diag_disable_terrain_sound_registration.flag";
	internal const string DisableTownDwellingBillboardsFlag = "homm3_diag_disable_town_dwelling_billboards.flag";
	internal const string DisableMapSquadVisualControllerFlag = "homm3_diag_disable_map_squad_visual_controller.flag";
	internal const string UnitViewVanillaShellOnlyFlag = "homm3_diag_unitview_vanilla_shell_only.flag";
	internal const string UnitViewHomm3VisualOnlyFlag = "homm3_diag_unitview_homm3_visual_no_native_shell.flag";

	private static readonly object Sync = new();
	private static readonly Stopwatch Clock = Stopwatch.StartNew();
	private static string _path;
	private static bool _headerWritten;
	private static bool _heartbeatStarted;
	private static int _censusRemaining = 10;
	private static readonly System.Collections.Generic.HashSet<string> CensusPhases = new(StringComparer.Ordinal);

	internal static bool Enabled => Homm3DiagnosticFlags.IsEnabled(FlagFileName);
	internal static bool DisableUnitViewMapSwaps => Homm3DiagnosticFlags.IsEnabled(DisableUnitViewMapSwapsFlag);
	internal static bool DisableMapArrayPilots => Homm3DiagnosticFlags.IsEnabled(DisableMapArrayPilotsFlag);
	internal static bool DisableNativeShellTransplant => Homm3DiagnosticFlags.IsEnabled(DisableNativeShellTransplantFlag);
	internal static bool DisableCustomBiomeRegistration => Homm3DiagnosticFlags.IsEnabled(DisableCustomBiomeRegistrationFlag);
	internal static bool DisableTerrainRendererRegistration => Homm3DiagnosticFlags.IsEnabled(DisableTerrainRendererRegistrationFlag);
	internal static bool DisableTerrainSoundRegistration => Homm3DiagnosticFlags.IsEnabled(DisableTerrainSoundRegistrationFlag);
	internal static bool DisableTownDwellingBillboards => Homm3DiagnosticFlags.IsEnabled(DisableTownDwellingBillboardsFlag);
	internal static bool DisableMapSquadVisualController => Homm3DiagnosticFlags.IsEnabled(DisableMapSquadVisualControllerFlag);
	internal static bool UnitViewVanillaShellOnly => Homm3DiagnosticFlags.IsEnabled(UnitViewVanillaShellOnlyFlag);
	internal static bool UnitViewHomm3VisualOnly => Homm3DiagnosticFlags.IsEnabled(UnitViewHomm3VisualOnlyFlag);

	internal static void Mark(string phase, string detail = null, bool census = false)
	{
		if (!Enabled)
			return;
		try
		{
			EnsureHeartbeat();
			WriteLine("MARK phase=" + Q(phase) + FormatRuntime() + FormatDetail(detail));
			if (census)
				WriteCensus(phase);
		}
		catch
		{
			// Diagnostic-only path; never affect gameplay or startup.
		}
	}

	internal static void MarkGameObject(string phase, GameObject go, string detail = null, bool census = false)
	{
		if (!Enabled)
			return;
		var goDetail = "go=" + DescribeGameObject(go);
		if (!string.IsNullOrEmpty(detail))
			goDetail += " " + detail;
		Mark(phase, goDetail, census);
	}

	internal static void MarkTerrain(string phase, object renderer, Material material = null, string detail = null, bool census = false)
	{
		if (!Enabled)
			return;
		var sb = new StringBuilder();
		sb.Append("renderer=").Append(DescribeObject(renderer));
		if (material)
			sb.Append(" material=").Append(DescribeMaterial(material));
		if (!string.IsNullOrEmpty(detail))
			sb.Append(' ').Append(detail);
		Mark(phase, sb.ToString(), census);
	}

	internal static void MarkStall(float deltaSeconds)
	{
		if (!Enabled)
			return;
		Mark("frame-stall", "gapMs=" + (deltaSeconds * 1000f).ToString("0"), census: true);
	}

	private static void WriteCensus(string phase)
	{
		if (_censusRemaining <= 0)
			return;
		if (!CensusPhases.Add(phase ?? ""))
			return;
		_censusRemaining--;
		var renderers = Resources.FindObjectsOfTypeAll<Renderer>();
		var total = 0;
		var enabled = 0;
		var mesh = 0;
		var skinned = 0;
		var hexLit = 0;
		var terrainMap = 0;
		var billboardArray = 0;
		var textureArrays = 0;
		var homm3Shells = 0;
		var arrayBridges = 0;
		var transplantSyncs = 0;
		var scannedMaterials = 0;
		foreach (var r in renderers)
		{
			if (!r)
				continue;
			total++;
			if (r.enabled && !r.forceRenderingOff)
				enabled++;
			if (r is MeshRenderer)
				mesh++;
			else if (r is SkinnedMeshRenderer)
				skinned++;
			var rootName = r.transform?.root ? r.transform.root.name : null;
			if (string.Equals(rootName, "map_native_shell", StringComparison.Ordinal)
			    || string.Equals(rootName, "homm3_map_visual", StringComparison.Ordinal))
				homm3Shells++;
			Material[] materials;
			try { materials = r.sharedMaterials; }
			catch { materials = Array.Empty<Material>(); }
			foreach (var m in materials)
			{
				if (!m)
					continue;
				scannedMaterials++;
				var shaderName = m.shader ? m.shader.name ?? "" : "";
				if (string.Equals(shaderName, "Hex/Lit", StringComparison.Ordinal))
					hexLit++;
				else if (string.Equals(shaderName, "Hex/TerrainMap", StringComparison.Ordinal))
					terrainMap++;
				else if (string.Equals(shaderName, "OldenEra/Homm3/BillboardArray", StringComparison.Ordinal))
					billboardArray++;
				if (HasTextureArray(m))
					textureArrays++;
			}
		}

		try { arrayBridges = Resources.FindObjectsOfTypeAll<Homm3MapArraySliceHexLitBridge>().Length; } catch { }
		try { transplantSyncs = Resources.FindObjectsOfTypeAll<Homm3NativeShellRendererTransplantSync>().Length; } catch { }

		WriteLine(
			"CENSUS phase=" + Q(phase)
			+ FormatRuntime()
			+ " renderers=" + total
			+ " enabled=" + enabled
			+ " mesh=" + mesh
			+ " skinned=" + skinned
			+ " materials=" + scannedMaterials
			+ " hexLit=" + hexLit
			+ " terrainMap=" + terrainMap
			+ " billboardArray=" + billboardArray
			+ " materialsWithTextureArray=" + textureArrays
			+ " homm3ShellRendererRoots=" + homm3Shells
			+ " arrayBridges=" + arrayBridges
			+ " transplantSyncs=" + transplantSyncs);
	}

	private static bool HasTextureArray(Material material)
	{
		if (!material)
			return false;
		var names = new[] { "_MainTexArray", "_MainTexArray0", "_MainTexArray1", "_Textures" };
		foreach (var name in names)
		{
			try
			{
				if (material.HasProperty(name) && material.GetTexture(name) is Texture2DArray)
					return true;
			}
			catch { }
		}
		return false;
	}

	private static void EnsureHeartbeat()
	{
		if (_heartbeatStarted)
			return;
		_heartbeatStarted = true;
		var thread = new Thread(HeartbeatLoop) { IsBackground = true, Name = "HOMM3 map-load flight recorder" };
		thread.Start();
	}

	private static void HeartbeatLoop()
	{
		while (true)
		{
			try
			{
				WriteLine("HEARTBEAT" + FormatRuntimeNoUnity());
			}
			catch { }
			Thread.Sleep(1000);
		}
	}

	private static void WriteLine(string line)
	{
		lock (Sync)
		{
			if (string.IsNullOrEmpty(_path))
				_path = Path.Combine(Paths.PluginPath, "OfflineUnlockMod", "map_load_flight_recorder.log");
			var dir = Path.GetDirectoryName(_path);
			if (!string.IsNullOrEmpty(dir))
				Directory.CreateDirectory(dir);
			if (!_headerWritten)
			{
				File.AppendAllText(_path, "=== map load flight recorder start " + DateTime.Now.ToString("O") + " ===" + Environment.NewLine);
				_headerWritten = true;
			}
			File.AppendAllText(_path, line + Environment.NewLine);
		}
	}

	private static string FormatRuntime()
	{
		var scene = SceneManager.GetActiveScene();
		return FormatRuntimeNoUnity()
		       + " frame=" + Time.frameCount
		       + " realtime=" + Time.realtimeSinceStartup.ToString("0.000")
		       + " scene=" + Q(scene.IsValid() ? scene.name : "?");
	}

	private static string FormatRuntimeNoUnity()
	{
		return " tMs=" + Clock.ElapsedMilliseconds + " utc=" + Q(DateTime.UtcNow.ToString("O"));
	}

	private static string FormatDetail(string detail)
	{
		return string.IsNullOrEmpty(detail) ? "" : " detail=" + Q(detail);
	}

	private static string DescribeGameObject(GameObject go)
	{
		if (!go)
			return "(null)";
		return Q((go.name ?? "?") + " activeSelf=" + go.activeSelf + " activeInHierarchy=" + go.activeInHierarchy + " path=" + GetPath(go.transform));
	}

	private static string DescribeObject(object obj)
	{
		if (obj == null)
			return "(null)";
		return Q(obj.GetType().FullName ?? obj.GetType().Name);
	}

	private static string DescribeMaterial(Material material)
	{
		if (!material)
			return "(null)";
		var shader = material.shader ? material.shader.name : "?";
		return Q((material.name ?? "?") + "/" + shader + "/queue=" + material.renderQueue);
	}

	private static string GetPath(Transform t)
	{
		if (!t)
			return "?";
		var sb = new StringBuilder(t.name ?? "?");
		for (var cur = t.parent; cur; cur = cur.parent)
			sb.Insert(0, (cur.name ?? "?") + "/");
		return sb.ToString();
	}

	private static string Q(string s)
	{
		if (s == null)
			return "\"\"";
		return "\"" + s.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", " ").Replace("\n", " ") + "\"";
	}
}
