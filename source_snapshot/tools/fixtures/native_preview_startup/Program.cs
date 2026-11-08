using System.Runtime.ExceptionServices;
using System.Text.Json;

namespace OfflineUnlockMod;

internal static class Program
{
	private static int Main()
	{
		var cases = new (string Name, Action Run)[]
		{
			("outside scope is untouched", OutsideScopeIsUntouched),
			("matching demand protects reentry", MatchingDemandProtectsReentry),
			("foreign demand does not enter", ForeignDemandDoesNotEnter),
			("nested owners restore correctly", NestedOwnersRestore),
			("same-owner nesting targets nearest warmup", SameOwnerNestingTargetsNearestWarmup),
			("normal and exception cleanup", CleanupRestoresPriorScope),
			("thread isolation and wrong-thread exit", ThreadIsolationAndWrongThreadExit),
			("invalid keys and out-of-order exit", InvalidKeysAndOutOfOrderExit),
			("settings parser decodes names and enforces boolean types", SettingsParserDecodesNamesAndEnforcesBooleanTypes),
			("settings parser rejects ambiguous and malformed JSON", SettingsParserRejectsAmbiguousAndMalformedJson),
			("settings merge preserves unrelated values", SettingsMergePreservesUnrelatedValues),
			("settings merge fails closed", SettingsMergeFailsClosed),
		};

		foreach (var (name, run) in cases)
		{
			try
			{
				run();
				Console.WriteLine("PASS " + name);
			}
			catch (Exception ex)
			{
				Console.Error.WriteLine("FAIL " + name + ": " + ex);
				return 1;
			}
		}

		Console.WriteLine("NativePreviewStartupScope fixture: OK (12 cases)");
		return 0;
	}

	private static void OutsideScopeIsUntouched()
	{
		Check.False(NativePreviewStartupScope.IsActive, "scope unexpectedly active");
		Check.Null(NativePreviewStartupScope.EnterDemand(11), "demand entered without a warmup");
		Check.False(NativePreviewStartupScope.TryDefer(11), "deferred without a warmup");
		NativePreviewStartupScope.Exit(null);
		Check.False(NativePreviewStartupScope.IsActive, "null exit changed scope state");
	}



	private static void MatchingDemandProtectsReentry()
	{
		var warmup = NativePreviewStartupScope.EnterWarmup(21);
		Check.Null(warmup.Previous, "warmup must begin without a prior frame");
		Check.Equal(21L, warmup.OwnerKey, "warmup owner");
		Check.False(warmup.IsDemand, "warmup marked as demand");
		Check.Equal(0, warmup.DeferredCount, "initial deferred count");
		Check.True(NativePreviewStartupScope.IsActive, "warmup is not active");
		NativePreviewStartupScope.Exit(null);
		Check.True(NativePreviewStartupScope.IsActive, "null exit changed the active warmup");
		Check.True(NativePreviewStartupScope.TryDefer(21), "same-owner warmup did not defer");
		Check.Equal(1, warmup.DeferredCount, "same-owner deferred count");
		Check.False(NativePreviewStartupScope.TryDefer(22), "foreign owner was deferred");
		Check.Equal(1, warmup.DeferredCount, "foreign owner changed deferred count");

		var demand = NativePreviewStartupScope.EnterDemand(21);
		Check.NotNull(demand, "matching demand did not enter");
		Check.True(demand.IsDemand, "demand frame not marked");
		Check.Same(warmup, demand.Previous, "demand previous frame");
		Check.Null(NativePreviewStartupScope.EnterDemand(21), "same-owner demand reentered");
		Check.False(NativePreviewStartupScope.TryDefer(21), "demand reentry was deferred");
		Check.Equal(1, warmup.DeferredCount, "demand reentry changed deferred count");
		NativePreviewStartupScope.Exit(demand);
		Check.True(NativePreviewStartupScope.IsActive, "demand exit did not restore warmup");
		Check.True(NativePreviewStartupScope.TryDefer(21), "warmup did not resume after demand");
		Check.Equal(2, warmup.DeferredCount, "deferred count after demand restore");
		NativePreviewStartupScope.Exit(warmup);
		Check.False(NativePreviewStartupScope.IsActive, "warmup exit did not clear scope");
	}

	private static void ForeignDemandDoesNotEnter()
	{
		var warmup = NativePreviewStartupScope.EnterWarmup(31);
		Check.Null(NativePreviewStartupScope.EnterDemand(32), "foreign demand entered");
		Check.True(NativePreviewStartupScope.IsActive, "foreign demand changed active warmup");
		Check.Equal(0, warmup.DeferredCount, "foreign demand changed deferred count");
		NativePreviewStartupScope.Exit(warmup);
	}

	private static void NestedOwnersRestore()
	{
		var outer = NativePreviewStartupScope.EnterWarmup(41);
		var inner = NativePreviewStartupScope.EnterWarmup(42);
		Check.Same(outer, inner.Previous, "nested previous frame");
		Check.True(NativePreviewStartupScope.TryDefer(41), "outer owner was not found below inner owner");
		Check.True(NativePreviewStartupScope.TryDefer(42), "inner owner did not defer");
		Check.Equal(1, outer.DeferredCount, "outer owner count");
		Check.Equal(1, inner.DeferredCount, "inner owner count");
		var outerDemand = NativePreviewStartupScope.EnterDemand(41);
		Check.NotNull(outerDemand, "outer demand was not found below another owner");
		Check.Same(inner, outerDemand.Previous, "nested cross-owner demand previous frame");
		Check.False(NativePreviewStartupScope.TryDefer(41), "matching nested demand allowed reentry");
		NativePreviewStartupScope.Exit(outerDemand);
		NativePreviewStartupScope.Exit(inner);
		Check.True(NativePreviewStartupScope.IsActive, "inner exit did not restore outer");
		Check.False(NativePreviewStartupScope.TryDefer(42), "exited owner still deferred");
		Check.True(NativePreviewStartupScope.TryDefer(41), "restored outer owner did not defer");
		Check.Equal(2, outer.DeferredCount, "restored outer count");
		NativePreviewStartupScope.Exit(outer);
		Check.False(NativePreviewStartupScope.IsActive, "outer exit did not clear scope");
	}

	private static void SameOwnerNestingTargetsNearestWarmup()
	{
		var outer = NativePreviewStartupScope.EnterWarmup(51);
		var inner = NativePreviewStartupScope.EnterWarmup(51);
		Check.True(NativePreviewStartupScope.TryDefer(51), "nested same owner did not defer");
		Check.Equal(0, outer.DeferredCount, "nested same-owner defer skipped nearest frame");
		Check.Equal(1, inner.DeferredCount, "nested same-owner defer did not target nearest frame");
		NativePreviewStartupScope.Exit(inner);
		Check.True(NativePreviewStartupScope.TryDefer(51), "outer same-owner warmup did not resume");
		Check.Equal(1, outer.DeferredCount, "outer same-owner count");
		NativePreviewStartupScope.Exit(outer);
	}

	private static void CleanupRestoresPriorScope()
	{
		var outer = NativePreviewStartupScope.EnterWarmup(61);
		var inner = NativePreviewStartupScope.EnterWarmup(62);
		try
		{
			throw new FixtureException();
		}
		catch (FixtureException)
		{
		}
		finally
		{
			NativePreviewStartupScope.Exit(inner);
		}
		Check.True(NativePreviewStartupScope.IsActive, "exception cleanup did not restore outer");
		NativePreviewStartupScope.Exit(outer);
		Check.False(NativePreviewStartupScope.IsActive, "normal cleanup did not clear scope");
	}

	private static void ThreadIsolationAndWrongThreadExit()
	{
		var mainFrame = NativePreviewStartupScope.EnterWarmup(71);
		Exception workerFailure = null;
		var worker = new Thread(() =>
		{
			try
			{
				Check.False(NativePreviewStartupScope.IsActive, "worker inherited main-thread scope");
				Check.Null(NativePreviewStartupScope.EnterDemand(71), "worker entered main-thread demand");
				Check.False(NativePreviewStartupScope.TryDefer(71), "worker deferred main-thread owner");
				Check.Throws<InvalidOperationException>(() => NativePreviewStartupScope.Exit(mainFrame), "wrong-thread exit");
				var workerFrame = NativePreviewStartupScope.EnterWarmup(71);
				Check.True(NativePreviewStartupScope.TryDefer(71), "worker-local owner did not defer");
				Check.Equal(1, workerFrame.DeferredCount, "worker-local deferred count");
				NativePreviewStartupScope.Exit(workerFrame);
				Check.False(NativePreviewStartupScope.IsActive, "worker scope leaked");
			}
			catch (Exception ex)
			{
				workerFailure = ex;
			}
		}) { IsBackground = true };

		worker.Start();
		Check.True(worker.Join(TimeSpan.FromSeconds(5)), "worker did not finish within 5 seconds");
		if (workerFailure != null)
			ExceptionDispatchInfo.Capture(workerFailure).Throw();
		Check.True(NativePreviewStartupScope.IsActive, "wrong-thread exit changed main-thread state");
		Check.Equal(0, mainFrame.DeferredCount, "worker changed main-thread deferred count");
		NativePreviewStartupScope.Exit(mainFrame);
	}

	private static void InvalidKeysAndOutOfOrderExit()
	{
		Check.Throws<ArgumentException>(() => NativePreviewStartupScope.EnterWarmup(0), "zero warmup owner");
		Check.Throws<ArgumentException>(() => NativePreviewStartupScope.EnterDemand(0), "zero demand owner");
		Check.Throws<ArgumentException>(() => NativePreviewStartupScope.TryDefer(0), "zero defer owner");
		var outer = NativePreviewStartupScope.EnterWarmup(81);
		var inner = NativePreviewStartupScope.EnterWarmup(82);
		Check.Throws<InvalidOperationException>(() => NativePreviewStartupScope.Exit(outer), "out-of-order exit");
		Check.True(NativePreviewStartupScope.IsActive, "rejected out-of-order exit corrupted state");
		NativePreviewStartupScope.Exit(inner);
		NativePreviewStartupScope.Exit(outer);
		Check.False(NativePreviewStartupScope.IsActive, "valid cleanup after rejected exit failed");
	}

	private static void SettingsParserDecodesNamesAndEnforcesBooleanTypes()
	{
		const string settingName = "homm3NativePreviewStartupDeferral";
		Check.True(ManagedModSettingsJson.TryReadTopLevelBoolean(
			"{\"\\u0068omm3NativePreviewStartupDeferral\":true}", settingName,
			out var present, out var value, out var diagnostic), "escaped key parse failed: " + diagnostic);
		Check.True(present, "escaped key was not recognized");
		Check.True(value, "escaped true was not read");
		Check.Null(diagnostic, "valid escaped key returned a diagnostic");

		Check.True(ManagedModSettingsJson.TryReadTopLevelBoolean(
			"{\"HOMM3NATIVEPREVIEWSTARTUPDEFERRAL\":false}", settingName,
			out present, out value, out diagnostic), "case-insensitive key parse failed: " + diagnostic);
		Check.True(present, "case-insensitive key was not recognized");
		Check.False(value, "explicit false was not preserved");
		Check.Null(diagnostic, "valid explicit false returned a diagnostic");
		Check.True(ManagedModSettingsJson.TryReadTopLevelBoolean(
			"{\"" + settingName + "\":true,}", settingName, out present, out value, out diagnostic),
			"native-compatible trailing comma was rejected: " + diagnostic);
		Check.True(value, "trailing-comma true was not read");
		Check.True(ManagedModSettingsJson.TryReadTopLevelBoolean(
			"{/* native comment */\"" + settingName + "\":true}", settingName, out present, out value, out diagnostic),
			"native-compatible comment was rejected: " + diagnostic);
		Check.True(value, "commented true was not read");

		Check.True(ManagedModSettingsJson.TryReadTopLevelBoolean(
			"{\"unrelated\":true}", settingName, out present, out value, out diagnostic),
			"absent setting parse failed: " + diagnostic);
		Check.False(present, "absent setting reported present");
		Check.False(value, "absent setting did not default false");

		foreach (var json in new[]
		{
			"{\"" + settingName + "\":null}",
			"{\"" + settingName + "\":\"true\"}",
			"{\"" + settingName + "\":1}",
			"{\"" + settingName + "\":{}}",
			"{\"" + settingName + "\":[]}",
		})
		{
			Check.False(ManagedModSettingsJson.TryReadTopLevelBoolean(
				json, settingName, out present, out value, out diagnostic), "accepted non-boolean setting: " + json);
			Check.True(!string.IsNullOrWhiteSpace(diagnostic), "invalid setting had no diagnostic");
		}
	}

	private static void SettingsParserRejectsAmbiguousAndMalformedJson()
	{
		const string settingName = "homm3NativePreviewStartupDeferral";
		foreach (var json in new[]
		{
			"{\"" + settingName + "\":true,\"" + settingName + "\":false}",
			"{\"" + settingName + "\":true,\"HOMM3NATIVEPREVIEWSTARTUPDEFERRAL\":false}",
			"{\"outer\":{\"" + settingName + "\":true}}",
			"{\"outer\":[{\"" + settingName + "\":true}]}",
			"{\"" + settingName + "\":true,\"outer\":{\"" + settingName + "\":false}}",
			"{",
			"{\"other\":true",
			"{\"nested\":{\"inner\":true}",
			"{\"x\":[1}}",
			"{\"text\":\"unclosed}",
			"{\"" + settingName + "\":true} trailing",
		})
		{
			Check.False(ManagedModSettingsJson.TryReadTopLevelBoolean(
				json, settingName, out _, out _, out var diagnostic), "accepted ambiguous/malformed JSON: " + json);
			Check.True(!string.IsNullOrWhiteSpace(diagnostic), "rejected JSON had no diagnostic");
		}
	}

	private static void SettingsMergePreservesUnrelatedValues()
	{
		const string existing = "{\"uiSettings\":{\"theme\":\"dark\",\"volume\":0.5},\"homm3FactionId\":\"old\",\"unrelatedArray\":[1,true,null,{\"x\":\"y\"}],\"nestedArray\":[[1,2],[\"nested\",false]],\"\\u0067reeting\":\"keep\\nstring\",\"escaped\":\"say \\\"hi\\\" { [ } ]\"}";
		const string update = "{\"HOMM3FACTIONID\":\"new\",\"featureFlag\":false}";
		Check.True(ManagedModSettingsJson.TryMergeObjects(existing, update, out var merged, out var diagnostic),
			"settings merge failed: " + diagnostic);
		Check.Null(diagnostic, "successful merge returned a diagnostic");
		using var document = JsonDocument.Parse(merged);
		var root = document.RootElement;
		Check.Equal("dark", root.GetProperty("uiSettings").GetProperty("theme").GetString(), "unrelated nested string");
		Check.Equal(0.5, root.GetProperty("uiSettings").GetProperty("volume").GetDouble(), "unrelated nested number");
		var array = root.GetProperty("unrelatedArray");
		Check.Equal(4, array.GetArrayLength(), "unrelated array length");
		Check.Equal(JsonValueKind.Null, array[2].ValueKind, "unrelated null element");
		Check.Equal("y", array[3].GetProperty("x").GetString(), "unrelated object element");
		var nestedArray = root.GetProperty("nestedArray");
		Check.Equal(2, nestedArray.GetArrayLength(), "nested array outer length");
		Check.Equal(2, nestedArray[0].GetArrayLength(), "nested numeric array length");
		Check.Equal(2, nestedArray[0][1].GetInt32(), "nested numeric value");
		Check.Equal("nested", nestedArray[1][0].GetString(), "nested string value");
		Check.False(nestedArray[1][1].GetBoolean(), "nested boolean value");
		Check.Equal("keep\nstring", root.GetProperty("greeting").GetString(), "escaped-name string content");
		Check.Equal("say \"hi\" { [ } ]", root.GetProperty("escaped").GetString(), "escaped quote and structural string content");
		Check.Equal("new", root.GetProperty("HOMM3FACTIONID").GetString(), "updated property");
		Check.Equal(1, root.EnumerateObject().Count(property => string.Equals(property.Name, "homm3FactionId", StringComparison.OrdinalIgnoreCase)),
			"case-insensitive update left duplicate property");
		Check.False(root.GetProperty("featureFlag").GetBoolean(), "explicit false update was lost");

		Check.True(ManagedModSettingsJson.TryMergeObjects(null, "{\"inheritedFlag\":true}", out merged, out diagnostic),
			"null-base merge failed: " + diagnostic);
		using var nullBaseDocument = JsonDocument.Parse(merged);
		Check.True(nullBaseDocument.RootElement.GetProperty("inheritedFlag").GetBoolean(), "null base was not treated as an empty object");

		Check.True(ManagedModSettingsJson.TryMergeObjects(
			"/* base */{\"baseFlag\":true,}", "{/* update */\"addedFlag\":false,}", out merged, out diagnostic),
			"native-compatible trailing commas were rejected during merge: " + diagnostic);
		using var trailingCommaDocument = JsonDocument.Parse(merged);
		Check.True(trailingCommaDocument.RootElement.GetProperty("baseFlag").GetBoolean(), "trailing-comma base value was lost");
		Check.False(trailingCommaDocument.RootElement.GetProperty("addedFlag").GetBoolean(), "trailing-comma update value was lost");
	}

	private static void SettingsMergeFailsClosed()
	{
		foreach (var (existing, update) in new (string Existing, string Update)[]
		{
			("{\"valid\":true} trailing", "{\"flag\":false}"),
			("   ", "{\"flag\":false}"),
			("{\"valid\":true}", "{\"flag\":false} trailing"),
			("[]", "{\"flag\":false}"),
			("{}", "{\"flag\":true,\"FLAG\":false}"),
			("{}", "{\"dupe\":true,\"\\u0064upe\":false}"),
		})
		{
			Check.False(ManagedModSettingsJson.TryMergeObjects(existing, update, out var merged, out var diagnostic),
				"accepted malformed/non-object/duplicate update input");
			Check.Null(merged, "failed merge returned partial output");
			Check.True(!string.IsNullOrWhiteSpace(diagnostic), "failed merge had no diagnostic");
		}

		const int maxDocumentBytes = 1_048_576;
		const string nearLimitPrefix = "{\"padding\":\"";
		const string nearLimitSuffix = "\"}";
		var nearLimitExisting = nearLimitPrefix
			+ new string('a', maxDocumentBytes - nearLimitPrefix.Length - nearLimitSuffix.Length - 6)
			+ nearLimitSuffix;
		Check.Equal(maxDocumentBytes - 6, System.Text.Encoding.UTF8.GetByteCount(nearLimitExisting),
			"valid near-limit input byte count");
		Check.False(ManagedModSettingsJson.TryMergeObjects(nearLimitExisting, "{\"added\":false}", out var oversizedMerged, out var oversizedDiagnostic),
			"formatted merge exceeding the input byte cap was accepted");
		Check.Null(oversizedMerged, "over-limit merge returned partial output");
		Check.True(oversizedDiagnostic != null
			&& oversizedDiagnostic.Contains("exceeds", StringComparison.OrdinalIgnoreCase)
			&& oversizedDiagnostic.Contains("limit", StringComparison.OrdinalIgnoreCase),
			"over-limit merge did not report the output size limit");
	}

	private sealed class FixtureException : Exception { }

	private static class Check
	{
		internal static void True(bool value, string message)
		{
			if (!value)
				throw new InvalidOperationException(message);
		}

		internal static void False(bool value, string message) => True(!value, message);

		internal static void Null(object value, string message) => True(value == null, message);

		internal static void NotNull(object value, string message) => True(value != null, message);

		internal static void Same(object expected, object actual, string message)
		{
			if (!ReferenceEquals(expected, actual))
				throw new InvalidOperationException(message);
		}

		internal static void Equal<T>(T expected, T actual, string message)
		{
			if (!Equals(expected, actual))
				throw new InvalidOperationException(message + $" (expected {expected}, actual {actual})");
		}

		internal static void Throws<T>(Action action, string message) where T : Exception
		{
			try
			{
				action();
			}
			catch (T)
			{
				return;
			}
			throw new InvalidOperationException(message + " was accepted");
		}
	}
}
