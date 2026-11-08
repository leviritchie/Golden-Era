# RAG Chunk: olden-era-playtest/110-map-billboards-fog

Current best adventure-map visual path: native shell + static `MeshRenderer` billboard + sanitized `Hex/Lit` material + native renderer flags + disk-loaded HoMM3 texture.

Avoid `Sprites/Default` as the primary map solution, per-instance fog polling, runtime squad mirror components, generic `GetComponents<T>` loops in injected components, renderer transplant experiments, and shared material mutation.

Material sanitizer: `EsquirePikemanVisuals.CreateSanitizedHexLitMapBillboardMaterial`. It forces alpha/dither keywords, assigns texture slots, resets tiling/offset, clears unsafe maps, and strips `HEX_BLEND_INTO_TERRAIN_POSITION` and `HEX_BLEND_INTO_TERRAIN_COLOR` for upright HoMM3 billboards.

Stronghold town note: a bare `Shader.Find("Hex/Lit")` material made the town invisible while hover still worked. A loaded unit-style Hex/Lit donor restored visibility but did not remove the town bottom distortion. The current fix pads the town texture with 96 transparent bottom pixels while keeping the visible content anchored; the town casts shadows again but does not receive shadows or dynamic occlusion.

Verify clear terrain, fog, black shroud, occlusion, outline, shadow, texture identity, and no log churn.
