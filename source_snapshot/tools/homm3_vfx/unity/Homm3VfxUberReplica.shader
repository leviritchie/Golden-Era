// HOMM3_VFX_LAB_GENERATED: managed by tools/homm3_vfx/vanilla_style_lab.py. Lab-only shader, not a delivery shader.
// Replica of the installed `magic/VfxUber` particle shader, read from its DXBC
// (artifacts/vanilla_vfx_style/vfxuber_ps/{ps_longest,vs_longest}.txt, static-bytecode, cbuffer slots mapped to
// property names by inference):
//   vertex    position pushed toward the camera by _CameraOffset (keyword _ACTIVE_CAMERA_OFFSET_ON)
//             noiseUV1 = (uv + custom.xy) * _Texture_ST  + frac(time * (_xSpeed01, _ySpeed01))
//             noiseUV2 = (uv + custom.zw) * _Texture2_ST + frac(time * (_xSpeed02, _ySpeed02))
//             maskUV   = uv * _Mask_ST
//   fragment  a   = smoothstep(_Min, _Max, min(n1, n2) * mask)       (n2 = 1 without _TWO_TEXTURES)
//             k   = a * _Multiply
//             rgb = k * lerp(k, _Color.rgb, _Lerp) * vcol.rgb * vcol.a^2
//             A   = k * lerp(k, _Color.a,  _Lerp) * vcol.a^2 * _Blend
//   blend     One OneMinusSrcAlpha (premultiplied; _Blend 0 = additive)
// Omitted: fog-of-war discard/desaturation, the world-height and radial fades, the ray V fades, the UV-derivative
// shift. `custom` is the particle Custom1 + Custom2 streams (the lab sets them from the recipe's CustomData module).
Shader "Hidden/Homm3Vfx/VfxUberReplica" {
    Properties {
        _Texture ("Noise 1", 2D) = "white" {}
        _Texture2 ("Noise 2", 2D) = "white" {}
        _Mask ("Mask", 2D) = "white" {}
        _Color ("Color (HDR)", Color) = (1,1,1,1)
        _Min ("Min", Float) = 0
        _Max ("Max", Float) = 1
        _Lerp ("Lerp", Float) = 1
        _Multiply ("Multiply", Float) = 1
        _Blend ("Blend", Float) = 1
        _CameraOffset ("Camera offset", Float) = 0
        _xSpeed01 ("", Float) = 0
        _ySpeed01 ("", Float) = 0
        _xSpeed02 ("", Float) = 0
        _ySpeed02 ("", Float) = 0
        _LabTime ("Lab time (s)", Float) = 0
        [Toggle] _UseTwo ("Two textures", Float) = 0
        [Toggle] _UseCamOffset ("Camera offset on", Float) = 0
    }
    SubShader {
        Tags { "Queue"="Transparent" "RenderType"="Transparent" "IgnoreProjector"="True" }
        Pass {
            Blend One OneMinusSrcAlpha
            ZWrite Off
            Cull Off
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"
            sampler2D _Texture, _Texture2, _Mask;
            float4 _Texture_ST, _Texture2_ST, _Mask_ST;
            float4 _Color;
            float _Min, _Max, _Lerp, _Multiply, _Blend, _CameraOffset;
            float _xSpeed01, _ySpeed01, _xSpeed02, _ySpeed02, _LabTime, _UseTwo, _UseCamOffset;
            struct VI { float4 pos : POSITION; float4 col : COLOR; float4 uv : TEXCOORD0; float4 c1 : TEXCOORD1; float4 c2 : TEXCOORD2; };
            struct VO { float4 pos : SV_POSITION; float4 col : COLOR; float4 n : TEXCOORD0; float2 m : TEXCOORD1; };
            VO vert(VI i) {
                VO o;
                float3 w = mul(unity_ObjectToWorld, float4(i.pos.xyz, 1)).xyz;
                if (_UseCamOffset > 0.5) {
                    float3 toCam = unity_OrthoParams.w > 0.5 ? -UNITY_MATRIX_V[2].xyz : normalize(_WorldSpaceCameraPos - w);
                    w += toCam * _CameraOffset;
                }
                o.pos = mul(UNITY_MATRIX_VP, float4(w, 1));
                o.col = i.col;
                float4 c = i.c1 + i.c2;
                float t = _LabTime;
                o.n.xy = (i.uv.xy + c.xy) * _Texture_ST.xy + _Texture_ST.zw + frac(t * float2(_xSpeed01, _ySpeed01));
                o.n.zw = (i.uv.xy + c.zw) * _Texture2_ST.xy + _Texture2_ST.zw + frac(t * float2(_xSpeed02, _ySpeed02));
                o.m = i.uv.xy * _Mask_ST.xy + _Mask_ST.zw;
                return o;
            }
            float4 frag(VO i) : SV_Target {
                float n1 = tex2D(_Texture, i.n.xy).r;
                float n2 = _UseTwo > 0.5 ? tex2D(_Texture2, i.n.zw).r : 1.0;
                float m = tex2D(_Mask, i.m).r;
                float a = smoothstep(_Min, max(_Max, _Min + 1e-4), min(n1, n2) * m);
                float k = a * _Multiply;
                float va2 = i.col.a * i.col.a;
                float3 rgb = k * lerp(k.xxx, _Color.rgb, _Lerp) * i.col.rgb * va2;
                float A = k * lerp(k, _Color.a, _Lerp) * va2 * _Blend;
                return float4(rgb, saturate(A));
            }
            ENDCG
        }
    }
}
