using System;
using System.IO;
using System.Text;
using BepInEx;

namespace OfflineUnlockMod;

/// <summary>NDJSON to <c>GameRootPath/debug-4f0ae8.log</c> (no game Newtonsoft, avoids Il2Cpp shim issues).</summary>
internal static class AgentDebugLog
{
	private const string SessionId = "4f0ae8";

	internal static void WriteJsonObject(string rawJsonObjectBody)
	{
		try
		{
			var path = Path.Combine(Paths.GameRootPath, "debug-4f0ae8.log");
			File.AppendAllText(path, rawJsonObjectBody + "\n");
		}
		catch
		{
		}
	}

	internal static void Write(string hypothesisId, string location, string message, string dataObjectJson = null)
	{
		var sb = new StringBuilder(256);
		sb.Append("{\"sessionId\":\"").Append(SessionId)
			.Append("\",\"timestamp\":").Append(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds())
			.Append(",\"runId\":\"").Append(Escape(RunId())).Append("\",\"hypothesisId\":\"")
			.Append(Escape(hypothesisId)).Append("\",\"location\":\"").Append(Escape(location))
			.Append("\",\"message\":\"").Append(Escape(message)).Append('"');
		if (dataObjectJson is { Length: > 0 })
			sb.Append(",\"data\":").Append(dataObjectJson);
		sb.Append('}');
		WriteJsonObject(sb.ToString());
	}

	private static string RunId() => Environment.GetEnvironmentVariable("DEBUG_OE_RUN_ID") ?? "pre";

	internal static string QuotedJsonString(string s) => '"' + Escape(s) + '"';

	private static string Escape(string s)
	{
		if (string.IsNullOrEmpty(s))
			return "";
		return s.Replace("\\", "\\\\", StringComparison.Ordinal)
			.Replace("\"", "\\\"", StringComparison.Ordinal)
			.Replace("\r", "\\r", StringComparison.Ordinal)
			.Replace("\n", "\\n", StringComparison.Ordinal)
			.Replace("\t", "\\t", StringComparison.Ordinal);
	}
}
