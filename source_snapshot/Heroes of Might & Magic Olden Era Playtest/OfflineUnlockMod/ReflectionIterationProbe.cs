using System.IO;

namespace OfflineUnlockMod;

/// <summary>
/// Optional reflection dump used by custom unit view routing. No-op when not needed.
/// </summary>
internal static class ReflectionIterationProbe
{
	internal static void TryWrite(string directory)
	{
		_ = directory;
	}
}
