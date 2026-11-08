using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>Samples a readable <see cref="Texture2D"/> from battle/map unit prefab renderers (tooltip portraits).</summary>
internal static class BattlePrefabPortraitTexture
{
	internal static Texture2D TryGetFirstTexture(GameObject root)
	{
		if (root == null)
			return null;
		foreach (var r in root.GetComponentsInChildren<Renderer>(true))
		{
			if (r == null)
				continue;
			var m = r.sharedMaterial;
			if (m == null)
				continue;
			Texture tex = null;
			try
			{
				tex = m.mainTexture;
			}
			catch
			{
				// ignored
			}

			if (tex == null && m.HasProperty("_MainTex"))
				tex = m.GetTexture("_MainTex");
			if (tex == null && m.HasProperty("_BaseMap"))
				tex = m.GetTexture("_BaseMap");
			if (tex is Texture2D t2)
				return t2;
		}

		return null;
	}
}
