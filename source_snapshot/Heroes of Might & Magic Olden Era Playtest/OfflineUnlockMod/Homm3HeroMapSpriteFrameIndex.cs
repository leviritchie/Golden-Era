using System;
using System.Collections.Generic;
using System.IO;

namespace OfflineUnlockMod
{
	internal sealed class Homm3HeroMapSpriteFrameIndex
	{
		private readonly Dictionary<string, string> _pathsByFrameStem;

		private Homm3HeroMapSpriteFrameIndex(Dictionary<string, string> pathsByFrameStem)
		{
			_pathsByFrameStem = pathsByFrameStem;
		}

		internal static bool TryCreate(string root, out Homm3HeroMapSpriteFrameIndex index, out string error)
		{
			index = null;
			error = null;
			if (string.IsNullOrWhiteSpace(root))
			{
				error = "sprite root is empty";
				return false;
			}
			if (!Directory.Exists(root))
			{
				error = "sprite root does not exist";
				return false;
			}

			try
			{
				var files = new List<string>(Directory.GetFiles(root, "*.png", SearchOption.AllDirectories));
				files.Sort(ComparePaths);
				var pathsByFrameStem = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
				for (var i = 0; i < files.Count; i++)
				{
					var stem = Path.GetFileNameWithoutExtension(files[i]);
					if (!IsCanonicalFrameStem(stem) || pathsByFrameStem.ContainsKey(stem))
						continue;
					pathsByFrameStem.Add(stem, files[i]);
				}
				index = new Homm3HeroMapSpriteFrameIndex(pathsByFrameStem);
				return true;
			}
			catch (Exception ex)
			{
				error = ex.GetType().Name + ": " + ex.Message;
				return false;
			}
		}

		internal bool TryGetFrame(int group, int frame, out string path)
		{
			var stem = group.ToString("00") + "_" + frame.ToString("00");
			return _pathsByFrameStem.TryGetValue(stem, out path);
		}

		private static int ComparePaths(string left, string right)
		{
			var comparison = StringComparer.OrdinalIgnoreCase.Compare(left, right);
			return comparison != 0 ? comparison : StringComparer.Ordinal.Compare(left, right);
		}

		private static bool IsCanonicalFrameStem(string stem)
		{
			return stem != null
				&& stem.Length == 5
				&& IsAsciiDigit(stem[0])
				&& IsAsciiDigit(stem[1])
				&& stem[2] == '_'
				&& IsAsciiDigit(stem[3])
				&& IsAsciiDigit(stem[4]);
		}

		private static bool IsAsciiDigit(char value)
		{
			return value >= '0' && value <= '9';
		}
	}
}
