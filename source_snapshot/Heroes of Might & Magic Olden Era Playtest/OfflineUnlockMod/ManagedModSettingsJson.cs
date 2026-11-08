using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.Json;

namespace OfflineUnlockMod;

internal static class ManagedModSettingsJson
{
	private const int MaxDocumentBytes = 1_048_576;
	private const int MaxDepth = 64;
	private static readonly JsonDocumentOptions DocumentOptions = new JsonDocumentOptions
	{
		AllowTrailingCommas = true,
		CommentHandling = JsonCommentHandling.Skip,
		MaxDepth = MaxDepth,
	};

	internal static bool TryReadTopLevelBoolean(
		string json,
		string propertyName,
		out bool present,
		out bool value,
		out string diagnostic)
	{
		present = false;
		value = false;
		diagnostic = null;
		if (string.IsNullOrEmpty(propertyName))
		{
			diagnostic = "The requested JSON property name was empty.";
			return false;
		}
		if (json == null)
			return true;
		if (!TryParseObject(json, out var document, out diagnostic))
			return false;

		using (document)
		{
			JsonProperty? setting = null;
			foreach (var property in document.RootElement.EnumerateObject())
			{
				if (!string.Equals(property.Name, propertyName, StringComparison.OrdinalIgnoreCase))
					continue;
				if (setting.HasValue)
				{
					diagnostic = "Top-level JSON property " + propertyName + " appears more than once.";
					return false;
				}
				setting = property;
			}

			foreach (var property in document.RootElement.EnumerateObject())
			{
				if (ContainsNestedProperty(property.Value, propertyName))
				{
					diagnostic = "JSON property " + propertyName + " must not appear below the top level.";
					return false;
				}
			}

			if (!setting.HasValue)
				return true;
			present = true;
			if (setting.Value.Value.ValueKind != JsonValueKind.True && setting.Value.Value.ValueKind != JsonValueKind.False)
			{
				diagnostic = "Top-level JSON property " + propertyName + " must be a boolean.";
				return false;
			}
			value = setting.Value.Value.GetBoolean();
			return true;
		}
	}

	internal static bool TryMergeObjects(
		string existingJson,
		string updateJson,
		out string mergedJson,
		out string diagnostic)
	{
		mergedJson = null;
		diagnostic = null;
		JsonDocument existing;
		if (!TryParseObject(existingJson ?? "{}", out existing, out diagnostic))
			return false;
		using (existing)
		{
			if (!TryParseObject(updateJson, out var updateDocument, out diagnostic))
				return false;
			using (updateDocument)
			{
				var updates = new List<JsonProperty>();
				var updateNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
				foreach (var update in updateDocument.RootElement.EnumerateObject())
				{
					if (!updateNames.Add(update.Name))
					{
						diagnostic = "Update JSON contains duplicate property " + update.Name + ".";
						return false;
					}
					updates.Add(update);
				}

				try
				{
					using var stream = new MemoryStream();
					using (var writer = new Utf8JsonWriter(stream, new JsonWriterOptions { Indented = true }))
					{
						writer.WriteStartObject();
						foreach (var property in existing.RootElement.EnumerateObject())
						{
							if (!updateNames.Contains(property.Name))
								property.WriteTo(writer);
						}
						foreach (var property in updates)
							property.WriteTo(writer);
						writer.WriteEndObject();
					}
					if (stream.Length > MaxDocumentBytes)
					{
						diagnostic = "Merged JSON exceeds the " + MaxDocumentBytes + " byte settings limit.";
						return false;
					}
					mergedJson = Encoding.UTF8.GetString(stream.ToArray());
					return true;
				}
				catch (Exception ex)
				{
					diagnostic = "Could not serialize merged JSON settings: " + ex.GetType().Name + ": " + ex.Message;
					return false;
				}
			}
		}
	}

	private static bool ContainsNestedProperty(JsonElement value, string propertyName)
	{
		if (value.ValueKind == JsonValueKind.Object)
		{
			foreach (var property in value.EnumerateObject())
			{
				if (string.Equals(property.Name, propertyName, StringComparison.OrdinalIgnoreCase)
				    || ContainsNestedProperty(property.Value, propertyName))
					return true;
			}
		}
		else if (value.ValueKind == JsonValueKind.Array)
		{
			foreach (var item in value.EnumerateArray())
			{
				if (ContainsNestedProperty(item, propertyName))
					return true;
			}
		}
		return false;
	}

	private static bool TryParseObject(string json, out JsonDocument document, out string diagnostic)
	{
		document = null;
		diagnostic = null;
		if (string.IsNullOrEmpty(json))
		{
			diagnostic = "JSON input was empty; an existing settings file is not treated as a missing file.";
			return false;
		}

		try
		{
			if (Encoding.UTF8.GetByteCount(json) > MaxDocumentBytes)
			{
				diagnostic = "JSON input exceeds the " + MaxDocumentBytes + " byte settings limit.";
				return false;
			}
			document = JsonDocument.Parse(json, DocumentOptions);
			if (document.RootElement.ValueKind == JsonValueKind.Object)
				return true;
			document.Dispose();
			document = null;
			diagnostic = "JSON root must be an object.";
			return false;
		}
		catch (Exception ex)
		{
			document?.Dispose();
			document = null;
			diagnostic = "Invalid or over-quota JSON: " + ex.GetType().Name + ": " + ex.Message;
			return false;
		}
	}
}
