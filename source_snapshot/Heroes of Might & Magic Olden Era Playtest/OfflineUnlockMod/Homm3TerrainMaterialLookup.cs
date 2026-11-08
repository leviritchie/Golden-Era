using System;
using System.Collections.Generic;

namespace OfflineUnlockMod;

/// <summary>Replace a reused renderer's lookup from a validated, current-map snapshot.</summary>
internal static class Homm3TerrainMaterialLookup
{
    internal static void Replace(
        IReadOnlyDictionary<int, int> expected,
        int materialSlotCount,
        Action clear,
        Action<int, int> add)
    {
        if (expected == null)
            throw new ArgumentNullException(nameof(expected));
        if (clear == null)
            throw new ArgumentNullException(nameof(clear));
        if (add == null)
            throw new ArgumentNullException(nameof(add));
        if (materialSlotCount <= 0 || expected.Count == 0)
            throw new InvalidOperationException("Terrain material lookup requires a non-empty current material table.");

        // Validate before touching native state. A previous map's dictionary is not a donor for this snapshot.
        foreach (var entry in expected)
        {
            if (entry.Value < 0 || entry.Value >= materialSlotCount)
                throw new InvalidOperationException(
                    "Terrain material lookup tileCode=" + entry.Key + " has slot " + entry.Value
                    + " outside the current " + materialSlotCount + " material slots.");
        }

        clear();
        foreach (var entry in expected)
            add(entry.Key, entry.Value);
    }
}
