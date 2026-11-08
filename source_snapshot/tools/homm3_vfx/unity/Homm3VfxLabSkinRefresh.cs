// HOMM3_VFX_LAB_GENERATED: managed by tools/homm3_vfx/build_vfx_lab.py. Lab-only helper, not a delivery component.
// The Unity preview harness samples a clip and renders several poses inside one editor frame. Skinned meshes
// otherwise keep the pose skinned for the first render, so the lab prefab forces per-render matrix updates.
using UnityEngine;

namespace OldenEra.Homm3Vfx
{
    [ExecuteAlways]
    public sealed class Homm3VfxLabSkinRefresh : MonoBehaviour
    {
        private void OnEnable()
        {
            foreach (SkinnedMeshRenderer skin in GetComponentsInChildren<SkinnedMeshRenderer>(true))
                skin.forceMatrixRecalculationPerRender = true;
        }
    }
}
