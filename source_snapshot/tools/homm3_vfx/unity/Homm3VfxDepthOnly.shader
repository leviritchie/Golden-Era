// HOMM3_VFX_LAB_GENERATED: managed by tools/homm3_vfx/titan_light_lab.py. Lab-only: writes depth, no colour,
// so the unit occludes its own VFX in the FX-only pass.
Shader "Hidden/Homm3Vfx/DepthOnly" {
    SubShader {
        Tags { "RenderType"="Opaque" "Queue"="Geometry" }
        Pass {
            Cull Off
            ZWrite On
            ColorMask 0
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"
            float4 vert(float4 pos : POSITION) : SV_POSITION { return UnityObjectToClipPos(pos.xyz); }
            float4 frag() : SV_Target { return 0; }
            ENDCG
        }
    }
}
