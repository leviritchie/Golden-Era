using System;
using System.Windows.Forms;

namespace OldenAiSim.Gui
{
	internal static class Program
	{
		[STAThread]
		private static void Main()
		{
			ApplicationConfiguration.Initialize();
			Application.Run(new MainForm());
		}
	}
}
