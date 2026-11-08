using System;
using System.Collections.Generic;
using System.Diagnostics;

namespace OfflineUnlockMod;

internal static class Program
{
	private static int Main()
	{
		var stopwatch = Stopwatch.StartNew();
		var lookup = new Dictionary<int, int>();
		var fortressNine = BuildSlots(firstTileCode: 1, count: 9);
		fortressNine[15] = 8;
		fortressNine[17] = 8;
		fortressNine[30] = 2;
		fortressNine[18] = 5;
		Replace(lookup, fortressNine, 9);
		AssertLookup(lookup, fortressNine, 9, "initial nine-slot map");

		var towerEight = BuildSlots(firstTileCode: 1, count: 8);
		towerEight[30] = towerEight[4];
		towerEight[18] = 6;
		Replace(lookup, towerEight, 8);
		AssertLookup(lookup, towerEight, 8, "nine-to-eight Tower transition");
		Assert(!lookup.ContainsKey(15) && !lookup.ContainsKey(17), "inactive custom tile keys survived Tower replacement");

		var reorderedEight = new Dictionary<int, int>();
		for (var slot = 0; slot < 8; slot++)
			reorderedEight[slot + 1] = 7 - slot;
		reorderedEight[30] = reorderedEight[5];
		reorderedEight[18] = 1;
		Replace(lookup, reorderedEight, 8);
		AssertLookup(lookup, reorderedEight, 8, "same-count slot reorder");

		var stockSeven = BuildSlots(firstTileCode: 1, count: 7);
		stockSeven[18] = 4;
		Replace(lookup, stockSeven, 7);
		AssertLookup(lookup, stockSeven, 7, "eight-to-seven stock transition");
		Assert(!lookup.ContainsKey(15) && !lookup.ContainsKey(17) && !lookup.ContainsKey(30), "inactive custom or alias key survived stock replacement");

		var plainSeven = BuildSlots(firstTileCode: 1, count: 7);
		Replace(lookup, plainSeven, 7);
		AssertLookup(lookup, plainSeven, 7, "same-count no-custom no-water map");
		Assert(!lookup.ContainsKey(18), "inactive native-water key survived a no-water map replacement");

		AssertInvalidExpectedLookupDoesNotMutate(lookup, plainSeven);
		stopwatch.Stop();
		using (var process = Process.GetCurrentProcess())
		{
			Console.WriteLine(
				"terrain material lookup fixture PASS"
				+ " elapsedMs=" + stopwatch.ElapsedMilliseconds
				+ " processPeakWorkingSetBytes=" + process.PeakWorkingSet64
				+ " measurementScope=test-process-only; SDK/build excluded");
		}
		return 0;
	}

	private static Dictionary<int, int> BuildSlots(int firstTileCode, int count)
	{
		var result = new Dictionary<int, int>();
		for (var slot = 0; slot < count; slot++)
			result[firstTileCode + slot] = slot;
		return result;
	}

	private static void Replace(Dictionary<int, int> target, IReadOnlyDictionary<int, int> expected, int slotCount)
	{
		Homm3TerrainMaterialLookup.Replace(expected, slotCount, target.Clear, target.Add);
	}

	private static void AssertLookup(
		Dictionary<int, int> actual,
		IReadOnlyDictionary<int, int> expected,
		int slotCount,
		string label)
	{
		Assert(actual.Count == expected.Count, label + ": entry count differs");
		foreach (var pair in expected)
		{
			Assert(actual.TryGetValue(pair.Key, out var slot) && slot == pair.Value,
				label + ": incorrect slot for tileCode=" + pair.Key);
		}
		foreach (var pair in actual)
			Assert(pair.Value >= 0 && pair.Value < slotCount, label + ": slot is outside the current table");
	}

	private static void AssertInvalidExpectedLookupDoesNotMutate(
		Dictionary<int, int> lookup,
		IReadOnlyDictionary<int, int> before)
	{
		var invalid = new Dictionary<int, int> { [100] = 0, [101] = 7 };
		var clearCalled = false;
		var threw = false;
		try
		{
			Homm3TerrainMaterialLookup.Replace(
				invalid,
				7,
				() =>
				{
					clearCalled = true;
					lookup.Clear();
				},
				lookup.Add);
		}
		catch (InvalidOperationException)
		{
			threw = true;
		}
		Assert(threw, "out-of-range expected slot did not throw an InvalidOperationException");
		Assert(!clearCalled, "invalid expected lookup cleared the live dictionary before validation");
		AssertLookup(lookup, before, 7, "invalid expected lookup left existing state untouched");
	}

	private static void Assert(bool condition, string message)
	{
		if (!condition)
			throw new InvalidOperationException(message);
	}
}
