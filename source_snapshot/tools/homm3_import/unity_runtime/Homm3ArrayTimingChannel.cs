using UnityEngine;

namespace OldenEra.Homm3Import
{
	/// <summary>
	/// Dummy channel for Texture2DArray timing clips. Curves target <see cref="phase"/> so animator
	/// length advances without overwriting battle quad scale (legacy clips used m_LocalScale.x = 1).
	/// Must live in a runtime assembly (not Assets/Editor) so AnimationUtility can bind clips.
	/// </summary>
	public sealed class Homm3ArrayTimingChannel : MonoBehaviour
	{
		[SerializeField]
		[HideInInspector]
		float phase;

		public float Phase => phase;
	}
}
