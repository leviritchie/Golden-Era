using System;

namespace OfflineUnlockMod;

/// <summary>Runtime manifest for Texture2DArray battle billboards (Option D prototype).</summary>
[Serializable]
public sealed class Homm3BattleArrayGroupDef
{
	public int group;
	public int startIndex;
	public int length;
}

[Serializable]
public sealed class Homm3BattleArrayClipDef
{
	public string name;
	public int[] indices;
	public float fps;
	public int loop;
	/// <summary>DEF attack group used when clip was authored; -1 if not directional.</summary>
	public int attackBaseGroup = -1;
}

[Serializable]
public sealed class Homm3BattleArrayManifestData
{
	public string unitSid;
	public int frameCount;
	public int arrayChunkSize = 2048;
	public int arrayCount = 1;
	public int baseAttackGroup;
	public Homm3BattleArrayGroupDef[] attackGroups;
	public Homm3BattleArrayClipDef[] clips;
}
