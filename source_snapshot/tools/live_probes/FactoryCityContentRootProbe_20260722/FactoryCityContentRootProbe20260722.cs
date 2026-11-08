using System;
using Hex.Session.City;
using UnityEngine;

public static class FactoryCityContentRootProbe20260722
{
	public static string Run()
	{
		var managers = UnityEngine.Object.FindObjectsOfType<BhBuildingsManager>(true);
		BhBuildingsManager manager = null;
		for (var i = 0; i < managers.Length; i++)
		{
			var candidate = managers[i];
			if (candidate != null
				&& candidate.gameObject != null
				&& candidate.gameObject.scene.IsValid()
				&& string.Equals(candidate.gameObject.scene.name, "cityFactory", StringComparison.Ordinal))
			{
				if (manager != null)
					throw new InvalidOperationException("Multiple BhBuildingsManager instances found in cityFactory.");
				manager = candidate;
			}
		}

		if (manager == null)
			throw new InvalidOperationException("BhBuildingsManager not found in cityFactory.");

		var root = manager.transform.root.gameObject;
		var before = CountActiveBuildings(root);
		var wasActive = root.activeSelf;
		if (!wasActive)
			root.SetActive(true);
		var after = CountActiveBuildings(root);

		return "{"
			+ "\"root\":\"" + Escape(root.name) + "\""
			+ ",\"wasActiveSelf\":" + (wasActive ? "true" : "false")
			+ ",\"isActiveSelf\":" + (root.activeSelf ? "true" : "false")
			+ ",\"isActiveInHierarchy\":" + (root.activeInHierarchy ? "true" : "false")
			+ ",\"activeBuildingsBefore\":" + before
			+ ",\"activeBuildingsAfter\":" + after
			+ "}";
	}

	private static int CountActiveBuildings(GameObject root)
	{
		var buildings = root.GetComponentsInChildren<BhBuilding>(true);
		var count = 0;
		for (var i = 0; i < buildings.Length; i++)
		{
			var building = buildings[i];
			if (building != null && building.gameObject != null && building.gameObject.activeInHierarchy)
				count++;
		}
		return count;
	}

	private static string Escape(string value)
	{
		return (value ?? "").Replace("\\", "\\\\").Replace("\"", "\\\"");
	}
}
