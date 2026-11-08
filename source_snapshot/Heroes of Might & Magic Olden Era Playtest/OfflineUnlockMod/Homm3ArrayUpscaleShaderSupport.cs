using System;
using System.Collections.Generic;
using System.IO;
using BepInEx;
using BepInEx.Logging;
using UnityEngine;

namespace OfflineUnlockMod;

internal static class Homm3ArrayUpscaleShaderSupport
{
	const string EnableFlagName = "homm3_array_upscale_shader.flag";
	const string DiagnosticFlagName = "homm3_array_upscale_shader_diag.flag";
	const string BundleName = "homm3_array_upscale_shader";
	const string BaseShaderName = "OldenEra/Homm3/BillboardArray";
	const string UpscaleShaderName = "OldenEra/Homm3/BillboardArrayUpscale";

	static readonly int MainTexArrayId = Shader.PropertyToID("_MainTexArray");
	static readonly int MainTexArray1Id = Shader.PropertyToID("_MainTexArray1");
	static readonly int MainTexArray2Id = Shader.PropertyToID("_MainTexArray2");
	static readonly int MainTexArray3Id = Shader.PropertyToID("_MainTexArray3");
	static readonly int SourceTexelSizeId = Shader.PropertyToID("_Homm3UpscaleSourceTexelSize");
	static readonly int StrengthId = Shader.PropertyToID("_Homm3UpscaleStrength");
	static readonly HashSet<int> AppliedMaterialIds = new();

	static AssetBundle _bundle;
	static Shader _shader;
	static bool _loadAttempted;
	static float _nextLoadAttemptAt;
	static bool _warnedMissingBundle;
	static bool _warnedInvalidBundle;
	static int _diagRemaining = 12;

	internal static bool Enabled => Homm3DiagnosticFlags.IsEnabled(EnableFlagName);

	internal static bool IsArrayBillboardShader(string shaderName) =>
		string.Equals(shaderName, BaseShaderName, StringComparison.Ordinal)
		|| string.Equals(shaderName, UpscaleShaderName, StringComparison.Ordinal);

	internal static bool IsArrayBillboardMaterial(Material material) =>
		material && material.shader && IsArrayBillboardShader(material.shader.name);

	internal static void TryApply(Renderer renderer, ManualLogSource log)
	{
		if (!Enabled || !renderer)
			return;
		var current = renderer.sharedMaterial;
		if (!current || !current.shader || !IsArrayBillboardShader(current.shader.name))
			return;
		var shader = ResolveShader(log);
		if (!shader)
			return;

		if (!string.Equals(current.shader.name, UpscaleShaderName, StringComparison.Ordinal))
		{
			var clone = new Material(current)
			{
				name = (current.name ?? "homm3_array") + "_upscale"
			};
			clone.shader = shader;
			ApplyMaterial(renderer, clone);
			current = clone;
		}

		ConfigureMaterial(current);
		var id = current.GetInstanceID();
		if (AppliedMaterialIds.Add(id))
			LogDiag(log, "applied shader to renderer '" + (renderer.name ?? "?") + "' material='" + (current.name ?? "?") + "'.");
	}

	static void ApplyMaterial(Renderer renderer, Material material)
	{
		try
		{
			var materials = renderer.sharedMaterials;
			if (materials != null && materials.Length > 0)
			{
				materials[0] = material;
				renderer.sharedMaterials = materials;
				return;
			}
		}
		catch
		{
		}
		renderer.sharedMaterial = material;
	}

	static void ConfigureMaterial(Material material)
	{
		if (!material)
			return;
		if (material.HasProperty(StrengthId))
			material.SetFloat(StrengthId, 0.65f);
		if (!material.HasProperty(SourceTexelSizeId))
			return;
		var source = FirstArrayTexture(material);
		if (!source)
			return;
		var width = Mathf.Max(1, source.width);
		var height = Mathf.Max(1, source.height);
		material.SetVector(SourceTexelSizeId, new Vector4(1f / width, 1f / height, width, height));
	}

	static Texture2DArray FirstArrayTexture(Material material)
	{
		if (!material)
			return null;
		var texture = GetArrayTexture(material, MainTexArrayId);
		if (texture)
			return texture;
		texture = GetArrayTexture(material, MainTexArray1Id);
		if (texture)
			return texture;
		texture = GetArrayTexture(material, MainTexArray2Id);
		if (texture)
			return texture;
		return GetArrayTexture(material, MainTexArray3Id);
	}

	static Texture2DArray GetArrayTexture(Material material, int propertyId)
	{
		try
		{
			return material.HasProperty(propertyId) ? material.GetTexture(propertyId) as Texture2DArray : null;
		}
		catch
		{
			return null;
		}
	}

	static Shader ResolveShader(ManualLogSource log)
	{
		if (_shader)
			return _shader;
		if (_loadAttempted && Time.realtimeSinceStartup < _nextLoadAttemptAt)
			return null;
		_loadAttempted = true;
		_nextLoadAttemptAt = Time.realtimeSinceStartup + 5f;

		var path = ResolveBundlePath();
		if (string.IsNullOrEmpty(path))
		{
			WarnOnce(log, ref _warnedMissingBundle, "enabled but bundle '" + BundleName + "' was not found; leaving base array shader unchanged.");
			return null;
		}

		try
		{
			_bundle = AssetBundle.LoadFromFile(path);
			if (!_bundle)
			{
				WarnOnce(log, ref _warnedInvalidBundle, "AssetBundle.LoadFromFile returned null for " + path + "; leaving base array shader unchanged.");
				return null;
			}

			_shader = LoadShaderFromBundle(_bundle);
			if (!_shader)
				WarnOnce(log, ref _warnedInvalidBundle, "shader '" + UpscaleShaderName + "' missing from " + path + "; leaving base array shader unchanged.");
			else
				LogDiag(log, "loaded shader bundle " + path + ".");
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3 array upscale shader: load failed: " + ex.Message);
		}
		return _shader;
	}

	static Shader LoadShaderFromBundle(AssetBundle bundle)
	{
		if (!bundle)
			return null;
		try
		{
			var shader = bundle.LoadAsset<Shader>("assets/shaders/homm3billboardarrayupscale.shader");
			if (shader && string.Equals(shader.name, UpscaleShaderName, StringComparison.Ordinal))
				return shader;
			foreach (var name in bundle.GetAllAssetNames())
			{
				if (string.IsNullOrEmpty(name))
					continue;
				if (name.EndsWith(".shader", StringComparison.OrdinalIgnoreCase))
				{
					shader = bundle.LoadAsset<Shader>(name);
					if (shader && string.Equals(shader.name, UpscaleShaderName, StringComparison.Ordinal))
						return shader;
				}
				if (name.EndsWith(".mat", StringComparison.OrdinalIgnoreCase))
				{
					var material = bundle.LoadAsset<Material>(name);
					if (material && material.shader && string.Equals(material.shader.name, UpscaleShaderName, StringComparison.Ordinal))
						return material.shader;
				}
			}
		}
		catch
		{
		}
		return null;
	}

	static string ResolveBundlePath()
	{
		var candidates = new[]
		{
			Path.Combine(Paths.PluginPath, "OfflineUnlockMod", BundleName),
			Path.Combine(Paths.PluginPath, "OfflineUnlockMod", "homm3_bundles", BundleName),
			Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", BundleName),
			Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", "homm3_bundles", BundleName),
		};
		for (var i = 0; i < candidates.Length; i++)
		{
			if (File.Exists(candidates[i]))
				return candidates[i];
		}
		return null;
	}

	static void LogDiag(ManualLogSource log, string message)
	{
		if (_diagRemaining <= 0 || !Homm3DiagnosticFlags.IsEnabled(DiagnosticFlagName))
			return;
		_diagRemaining--;
		log?.LogInfo("Homm3 array upscale shader: " + message);
	}

	static void WarnOnce(ManualLogSource log, ref bool warned, string message)
	{
		if (warned)
			return;
		warned = true;
		log?.LogWarning("Homm3 array upscale shader: " + message);
	}
}
