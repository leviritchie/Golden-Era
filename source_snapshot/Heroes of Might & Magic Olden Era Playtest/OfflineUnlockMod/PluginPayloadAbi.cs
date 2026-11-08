namespace OfflineUnlockMod;

// Payload compatibility versions (docs/plugin_payload_abi.md). Delivery and runtime records pin the
// version of the surface they depend on instead of this DLL's sha256, so an unrelated plugin deploy
// no longer invalidates them. The build emits these values into OfflineUnlockMod.payload_abi.json next
// to the deployed DLL (tools/plugin_payload_abi/payload_abi.py emit), together with that DLL's sha256.
//
// Bump a version only when a change alters what a record of that surface depends on: the catalog or
// table schema the plugin reads, the bundle/prefab conventions it expects, the shader or node names it
// looks up. Then acknowledge it (payload_abi.py ack <surface>) and rebuild the records of that surface.
// The reader files of each surface are listed in tools/plugin_payload_abi/surfaces.json; the build warns
// when one of them changed since its last acknowledgement.
internal static class PluginPayloadAbi
{
    // def_retarget / mocap owned-skinned unit bundles in homm3_bundles: homm3_import.json bindings,
    // owned-skinned prefab layout, __homm3_vfx_* node names, homm3_mesh_fx catalog + vanilla-style FX.
    public const int UnitBundleContractVersion = 1;

    // full-3D town scenes: homm3_town_scene_meshes/scene3d/<town>/catalog.json schema (fullScene3d,
    // clothLook, waterLook, skyLook, building picking) and the bundle shaders it names.
    // v2 (2026-10-01): the reader parses clothLook (flag-wave cloth pieces) and skyLook (continuous panorama with
    // _TimeOffset); a catalog shipping either needs v2 (validate_town_scene3d_contract TOWN_SCENE_KEY_MIN).
    public const int TownSceneContractVersion = 2;
}
