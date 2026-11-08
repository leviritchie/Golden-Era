// Canonical copy for git. Deploy to: <UnityProject>/Assets/Editor/AnimatorStringHashReport.cs
// Batch: Unity.exe -batchmode -quit -nographics -projectPath <UnityProject> -executeMethod OldenEra.ReferenceTools.AnimatorStringHashReport.DumpFromCommandLine -logFile <path>
// Menu: Olden Era / Reference / Dump Animator StringToHash (battle params)
using System.IO;
using System.Text;
using UnityEditor;
using UnityEngine;

namespace OldenEra.ReferenceTools
{
	public static class AnimatorStringHashReport
	{
		/// <summary>Parameter <c>m_Name</c> values from <c>Assets/CustomUnits/esquire/Reference/StockEsquireBattle.controller</c> (<c>_Battle_Unit_Anim_ctrl_v2</c>).</summary>
		static readonly string[] StockBattleUnitParameterNames =
		{
			"move", "moveAbility", "teleport", "teleportAbility", "fly", "flyAbility",
			"rotateLeft", "rotateRight", "battleSpeed", "rareIdle", "attack", "damage",
			"isDead", "die", "victory", "attackVariant", "revive", "stanceIn", "stanceOut",
			"battleSlowIdle",
		};

		/// <summary>Names used in OfflineUnlockMod <c>EsquireBattleAudioPlayer</c> / <c>HintForId</c> (verify against stock).</summary>
		static readonly string[] LegacyModHintNames =
		{
			"Attack", "Hit", "Death", "Die", "IsMoving", "Speed", "State", "highlightState",
			"ActionType", "direction", "yMove", "Idle",
		};

		[MenuItem("Olden Era/Reference/Dump Animator StringToHash (battle params)")]
		public static void DumpFromMenu() => DumpCore(writeFile: false);

		public static void DumpFromCommandLine()
		{
			DumpCore(writeFile: true);
			EditorApplication.Exit(0);
		}

		static void DumpCore(bool writeFile)
		{
			var sb = new StringBuilder(4096);
			void Line(string s)
			{
				Debug.Log(s);
				sb.AppendLine(s);
			}

			Line("# Animator.StringToHash report");
			Line("# Unity: " + Application.unityVersion);
			Line("# project: " + Application.dataPath);
			Line("# columns: kind\tname\tint32\thex8");
			Line("");
			Line("## Stock _Battle_Unit_Anim_ctrl_v2 parameters (from Reference/StockEsquireBattle.controller)");
			foreach (var n in StockBattleUnitParameterNames)
			{
				var h = Animator.StringToHash(n);
				Line("param\t" + n + "\t" + h + "\t" + unchecked((uint)h).ToString("X8"));
			}

			Line("");
			Line("## Legacy / mod HintForId-style names (may NOT match stock controller)");
			foreach (var n in LegacyModHintNames)
			{
				var h = Animator.StringToHash(n);
				Line("legacy\t" + n + "\t" + h + "\t" + unchecked((uint)h).ToString("X8"));
			}

			if (writeFile)
			{
				var outPath = Path.Combine(Application.dataPath, "..", "AnimatorStringToHash_report.tsv");
				outPath = Path.GetFullPath(outPath);
				File.WriteAllText(outPath, sb.ToString());
				Debug.Log("Wrote " + outPath);
			}
		}
	}
}
