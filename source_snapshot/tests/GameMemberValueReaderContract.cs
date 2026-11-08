using System;
using OfflineUnlockMod;

public static class GameMemberValueReaderContract
{
	public static void Run()
	{
		ExpectValue(new AliasOrderFixture(), new[] { "Second", "First" }, "second", "alias order");
		ExpectValue(new DerivedPrivateMembersFixture(), new[] { "HiddenField" }, "private field", "private inherited field");
		ExpectValue(new DerivedPrivateMembersFixture(), new[] { "HiddenProperty" }, "private property", "private inherited property");
		ExpectValue(new DerivedHiddenFieldFixture(), new[] { "Shared" }, "base property", "property before derived field");
		ExpectValue(new DerivedFieldAfterNullPropertyFixture(), new[] { "Shared" }, "derived field", "null property falls through to field");
		ExpectValue(new DerivedFieldBeforeMethodFixture(), new[] { "Shared" }, "derived field", "field before base method");
		ExpectValue(new OverloadedMethodFixture(), new[] { "Resolve" }, "zero args", "zero-argument overload");
		ExpectValue(new DerivedIndexerMethodFixture(), new[] { "Item" }, "method", "indexer is not a readable value member");
		ExpectAmbiguousIndexerStopsFallback();
		ExpectThrowingGetterStopsFallback();
	}

	private static void ExpectValue(object target, string[] names, string expected, string label)
	{
		if (!GameMemberValueReader.TryRead(target, names, out var value, out var failure))
			throw new InvalidOperationException(label + " did not resolve: " + failure);
		if (!string.Equals(value as string, expected, StringComparison.Ordinal))
			throw new InvalidOperationException(label + " resolved '" + value + "' instead of '" + expected + "'");
	}

	private static void ExpectThrowingGetterStopsFallback()
	{
		var fixture = new DerivedThrowingGetterFixture();
		if (GameMemberValueReader.TryRead(fixture, new[] { "Poison", "Backup" }, out var value, out var failure))
			throw new InvalidOperationException("a throwing getter resolved a lower-priority member: " + value);
		if (fixture.MethodCalled || fixture.BackupRead)
			throw new InvalidOperationException("a throwing getter invoked an alternate method or alias");
		if (failure == null || failure.IndexOf("property getter failed", StringComparison.Ordinal) < 0
			|| failure.IndexOf("InvalidOperationException", StringComparison.Ordinal) < 0)
			throw new InvalidOperationException("getter failure was not reported precisely: " + failure);
	}

	private static void ExpectAmbiguousIndexerStopsFallback()
	{
		var fixture = new DerivedOverloadedIndexerFixture();
		if (GameMemberValueReader.TryRead(fixture, new[] { "Item" }, out var value, out var failure))
			throw new InvalidOperationException("an ambiguous indexer resolved a lower-priority member: " + value);
		if (fixture.MethodCalled)
			throw new InvalidOperationException("an ambiguous indexer invoked a lower-priority method");
		if (failure == null || failure.IndexOf("AmbiguousMatchException", StringComparison.Ordinal) < 0)
			throw new InvalidOperationException("ambiguous property metadata was not reported: " + failure);
	}

	private sealed class AliasOrderFixture
	{
		public string First = "first";
		public string Second = "second";
	}

	private class BasePropertyFixture
	{
		public string Shared => "base property";
	}

	private class BasePrivateMembersFixture
	{
		private string HiddenField = "private field";
		private string HiddenProperty => "private property";
		public string ReadField() => HiddenField;
	}

	private sealed class DerivedPrivateMembersFixture : BasePrivateMembersFixture { }

	private sealed class DerivedHiddenFieldFixture : BasePropertyFixture
	{
		public new string Shared = "derived field";
	}

	private class BaseNullPropertyFixture
	{
		public string Shared => null;
	}

	private sealed class DerivedFieldAfterNullPropertyFixture : BaseNullPropertyFixture
	{
		public new string Shared = "derived field";
	}

	private class BaseMethodFixture
	{
		public string Shared() => "base method";
	}

	private sealed class DerivedFieldBeforeMethodFixture : BaseMethodFixture
	{
		public new string Shared = "derived field";
	}

	private sealed class OverloadedMethodFixture
	{
		public string Resolve() => "zero args";
		public string Resolve(int ignored) => "one arg";
	}

	private class BaseIndexerFixture
	{
		public string this[int index] => "indexed";
	}

	private sealed class DerivedIndexerMethodFixture : BaseIndexerFixture
	{
		public string Item() => "method";
	}

	private class BaseOverloadedIndexerFixture
	{
		public string this[int index] => "integer indexer";
		public string this[string index] => "string indexer";
	}

	private sealed class DerivedOverloadedIndexerFixture : BaseOverloadedIndexerFixture
	{
		public bool MethodCalled;
		public string Item()
		{
			MethodCalled = true;
			return "method";
		}
	}

	private class BaseThrowingGetterFixture
	{
		public string Poison => throw new InvalidOperationException("fixture getter failure");
	}

	private sealed class DerivedThrowingGetterFixture : BaseThrowingGetterFixture
	{
		public bool MethodCalled;
		public bool BackupRead;
		public string Backup
		{
			get
			{
				BackupRead = true;
				return "backup";
			}
		}
		public new string Poison()
		{
			MethodCalled = true;
			return "method fallback";
		}
	}
}
