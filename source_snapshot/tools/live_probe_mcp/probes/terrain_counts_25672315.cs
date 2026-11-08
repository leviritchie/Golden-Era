using System;
using System.Globalization;
using Hex.Render;
using UnityEngine;
using UnityEngine.SceneManagement;

public static class TerrainCountsProbe25672315
{
	// Dispatch only after observed map readiness; this is not an ff-boundary sample.
	public static string Run()
	{
		var scene = SceneManager.GetActiveScene();
		var terrain = SoTerrainMaterial.instance;
		if (terrain == null)
			throw new InvalidOperationException("SoTerrainMaterial.instance is null.");
		var biomes = terrain.biomes;
		if (biomes == null)
			throw new InvalidOperationException("SoTerrainMaterial.instance.biomes is null.");

		var biomParams = Shader.GetGlobalVectorArray("Terrain_BiomParams");
		var tilings = Shader.GetGlobalVectorArray("Terrain_Tilings");
		var heightmapScales = Shader.GetGlobalVectorArray("Terrain_HeightmapScales");
		if (biomParams == null || tilings == null || heightmapScales == null)
			throw new InvalidOperationException("One or more terrain global vector arrays are unset.");

		// Singleton rows do not establish the active-map set or shader index domain.
		return string.Concat(
			"sample=late",
			";frame=", Time.frameCount.ToString(CultureInfo.InvariantCulture),
			";scene=", scene.name ?? "",
			";singletonBiomeRows=", biomes.Length.ToString(CultureInfo.InvariantCulture),
			";Terrain_BiomParams=", biomParams.Length.ToString(CultureInfo.InvariantCulture),
			";Terrain_Tilings=", tilings.Length.ToString(CultureInfo.InvariantCulture),
			";Terrain_HeightmapScales=", heightmapScales.Length.ToString(CultureInfo.InvariantCulture));
	}
}
