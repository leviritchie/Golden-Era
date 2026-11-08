// HOMM3_VFX_LAB_GENERATED: managed by tools/homm3_vfx/vanilla_style_lab.py. Lab only, not a game shader.
// Restricted replica of the active install's magic/Water_fire_stylized no-fog DXBC pass (PS program 14).
// MaterialCache refuses every material except the pinned Water_aqualotl_04_vfx and Naiad_water_06_vfx
// configurations. Cbuffer/property mapping and particle UV packing are inferred from the installed pass
// metadata and vertex streams; OLD | NEW | VANILLA rendering must still be judged visually.
Shader "Hidden/Homm3Vfx/WaterFireStylizedReplica" {
    Properties {
        _Texture1 ("Water texture", 2D) = "white" {}
        _TextureSample0 ("Dissolve noise", 2D) = "white" {}
        _maskmove2 ("Moving mask noise", 2D) = "white" {}
        _mask ("Water mask", 2D) = "white" {}
        _Tilingtexture1 ("", Vector) = (1,1,0,0)
        _maskmove2tiling ("", Vector) = (1,1,0,0)
        _Dissolvetiling ("", Vector) = (1,1,0,0)
        _Dissolveoffset ("", Vector) = (0,1,0,0)
        _Timemask ("", Float) = 0
        _minsmoothetexture ("", Float) = 0
        _maxsmoothetexture ("", Float) = 1
        _minsmootheopacity ("", Float) = 0
        _maxsmootheopacity ("", Float) = 1
        _smotheminmaskmovelerp ("", Float) = 0
        _smoothemaxmaskmovelerp ("", Float) = 1
        _Maskssmoothemin ("", Float) = 0
        _Maskssmoothemax ("", Float) = 1
        _Multiplymasks ("", Float) = 1
        _multiplytexture ("", Float) = 1
        _Opacitystandartworld2 ("", Float) = 0
        _Worldmultiply ("", Float) = 1
        _float1 ("", Float) = 1
        _Dissolveclampmin ("", Float) = 0
        _Dissolveclampmax ("", Float) = 1
        _Dissolvefloat ("", Float) = 2
        _Dissolvedivide ("", Float) = 3
        _Dissolvecoloroffon ("", Float) = 0
        _Dissolvecolor ("", Color) = (0,0,0,1)
        _HexFade ("", Float) = 0
        _LabTime ("", Float) = 0
    }
    SubShader {
        Tags { "Queue"="Transparent" "RenderType"="Transparent" "IgnoreProjector"="True" }
        Pass {
            Blend SrcAlpha OneMinusSrcAlpha
            Cull Off
            ZWrite Off
            ZTest LEqual
            CGPROGRAM
            #pragma target 3.0
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"

            sampler2D _Texture1, _TextureSample0, _maskmove2, _mask;
            float4 _Tilingtexture1, _maskmove2tiling, _Dissolvetiling, _Dissolveoffset, _mask_ST, _Dissolvecolor;
            float _Timemask, _minsmoothetexture, _maxsmoothetexture, _minsmootheopacity, _maxsmootheopacity;
            float _smotheminmaskmovelerp, _smoothemaxmaskmovelerp, _Maskssmoothemin, _Maskssmoothemax;
            float _Multiplymasks, _multiplytexture, _Opacitystandartworld2, _Worldmultiply, _float1;
            float _Dissolveclampmin, _Dissolveclampmax, _Dissolvefloat, _Dissolvedivide;
            float _Dissolvecoloroffon, _HexFade, _LabTime;

            struct VI { float4 pos : POSITION; float4 col : COLOR; float4 uv : TEXCOORD0; float4 custom1 : TEXCOORD1; };
            struct VO {
                float4 pos : SV_POSITION; float4 col : COLOR;
                float4 uv : TEXCOORD0; float2 maskUv : TEXCOORD1;
                float2 dissolveUv : TEXCOORD2; float worldY : TEXCOORD3;
            };
            float smooth_signed(float lo, float hi, float x) {
                float t = saturate((x - lo) / (hi - lo));
                return t * t * (3.0 - 2.0 * t);
            }
            float3 smooth_rgb(float lo, float hi, float3 x) {
                float3 t = saturate((x - lo) / (hi - lo));
                return t * t * (3.0 - 2.0 * t);
            }
            VO vert(VI i) {
                VO o;
                float3 world = mul(unity_ObjectToWorld, i.pos).xyz;
                o.pos = mul(UNITY_MATRIX_VP, float4(world, 1));
                o.worldY = world.y;
                o.col = i.col;
                // Installed stream: TEXCOORD0.xy=UV, zw=UV2; TEXCOORD1=Custom1.
                // _Offsettexture1/2 are serialized but absent from this pass's DXBC path.
                o.uv.xy = i.uv.xy * _Tilingtexture1.xy + i.uv.zw + _Tilingtexture1.zw;
                o.uv.zw = i.uv.xy * _maskmove2tiling.xy + i.uv.zw + _Tilingtexture1.zw;
                o.maskUv = i.uv.xy * _mask_ST.xy + _mask_ST.zw;
                o.dissolveUv = i.custom1.xy * _Dissolvetiling.xy + _LabTime * _Timemask * _Dissolveoffset.xy;
                return o;
            }
            float4 frag(VO i) : SV_Target {
                float4 baseTex = tex2D(_Texture1, i.uv.xy);
                float3 baseSmooth = smooth_rgb(_minsmoothetexture, _maxsmoothetexture, baseTex.rgb);
                float3 baseColor = baseSmooth * i.col.rgb * _multiplytexture;
                float moving = tex2D(_maskmove2, i.uv.zw).r;
                // Naiad_water_06_vfx deliberately reverses these bounds; do not sort them.
                float movement = smooth_signed(_smotheminmaskmovelerp, _smoothemaxmaskmovelerp, moving);
                float mask = tex2D(_mask, i.maskUv).r;
                float alpha = i.col.a * _Multiplymasks *
                    smooth_signed(_minsmootheopacity, _maxsmootheopacity, baseTex.a) *
                    smooth_signed(_Maskssmoothemin, _Maskssmoothemax, mask * movement);
                alpha *= lerp(_float1, i.worldY * _Worldmultiply, _Opacitystandartworld2);
                clip(alpha <= 0.0 ? -1.0 : 1.0);

                float3 rgb = baseColor;
                if (_Dissolvecoloroffon > 0.5) {
                    float3 noise = tex2D(_TextureSample0, i.dissolveUv).rgb;
                    float3 gate = step(clamp(noise, _Dissolveclampmin, _Dissolveclampmax), _Dissolvefloat);
                    float3 edge = gate - step(noise, _Dissolvefloat / _Dissolvedivide);
                    float3 q = lerp(baseSmooth, _Dissolvecolor.rgb, edge);
                    rgb = baseColor * (1.0 + (gate + edge) * q - baseColor);
                }
                return float4(rgb, saturate(alpha) * (1.0 - _HexFade));
            }
            ENDCG
        }
    }
}
