// HOMM3_VFX_LAB_GENERATED: managed by tools/homm3_vfx/vanilla_style_lab.py. Lab-only shader, not a delivery shader.
// Approximate replica of the installed Amplify dissolve particle shaders `magic/test/Disappearance_01/02/03`
// (the vanilla feathers: Feathers_vfx, Morality_feather_vfx, Angel_feathers_vfx, Phoenix_rise_sparks_vfx), read from
// their DXBC pixel programs (d3dcompiler D3DDisassemble; cbuffer slots named from the pass m_NameIndices;
// 2026-09-27, static bytecode only). _Variant picks the program:
//   T = tex(uv * ST)  (1: _TextureSample5, 2/3: _Texture)      N = tex(mask noise, uv * tiling)
//       mask noise    1: _mask, tiling _Vector0.xy             2/3: _Maskdisapearence, tiling _Tilingmask.xy
//   d = Custom1.x     (ASSUMPTION: the dissolve input v1.z of the vanilla vertex layout is the particle's Custom1.x;
//                      every vanilla feather drives Custom1.x by a lifetime curve). 2/3: _Disapearence when
//                      _Disapearenceonoff != 0.
//   divide            1: _Float4    2/3: _Divide
//   a = N <= d        b = (d / divide) >= N        edge = a - b        w = 2a - b
//   M = tex(_TextureSample3 / _Mask, uv * ST); 2: smoothstep(_Float0, _Float1, M) when _Mask_smoothe != 0
//   alpha = sat(w * M * T.r * vcol.a * opacity)   (1: _Float12, 2/3: _opacity); discard alpha <= 0
//   1: rgb = sat(lerp(T, _Color3, edge) * w * (T*_Color9 + T*(_Color11 - T*_Color9)) * vcol)
//   2: rgb = w * lerp(T*_Colortexture + T*(_Colorlerp1 - T*_Colortexture), _Colorlerp2, edge) * vcol   (HDR)
//   3: rgb = w * lerp(T, _Colorlerp2, edge) * vcol                                                       (HDR)
// Omitted: _HexFade (fog of war). Blend SrcAlpha OneMinusSrcAlpha as the originals; alpha written premultiplied-
// compatible (One OneMinusSrcAlpha) so the lab's readback composites like the VfxUber replica.
Shader "Hidden/Homm3Vfx/DisappearanceReplica" {
    Properties {
        _Variant ("Variant (1,2,3)", Float) = 2
        _TextureSample5 ("T (01)", 2D) = "white" {}
        _mask ("Noise (01)", 2D) = "white" {}
        _TextureSample3 ("Mask (01)", 2D) = "white" {}
        _Texture ("T (02/03)", 2D) = "white" {}
        _Maskdisapearence ("Noise (02/03)", 2D) = "white" {}
        _Mask ("Mask (02/03)", 2D) = "white" {}
        _Color3 ("Edge (01)", Color) = (1,1,1,1)
        _Color9 ("C9 (01)", Color) = (1,1,1,1)
        _Color11 ("C11 (01)", Color) = (1,1,1,1)
        _Vector0 ("Noise tiling (01)", Vector) = (1,1,0,0)
        _Float4 ("Divide (01)", Float) = 2
        _Float12 ("Opacity (01)", Float) = 1
        _Colortexture ("Ctex (02)", Color) = (1,1,1,1)
        _Colorlerp1 ("Clerp1 (02)", Color) = (1,1,1,1)
        _Colorlerp2 ("Clerp2 (02/03)", Color) = (1,1,1,1)
        _Tilingmask ("Noise tiling (02/03)", Vector) = (1,1,0,0)
        _Disapearenceonoff ("", Float) = 0
        _Disapearence ("", Float) = 0
        _Divide ("Divide (02/03)", Float) = 2
        _Mask_smoothe ("", Float) = 0
        _Float0 ("", Float) = 0
        _Float1 ("", Float) = 1
        _opacity ("Opacity (02/03)", Float) = 1
    }
    SubShader {
        Tags { "Queue"="Transparent" "RenderType"="Transparent" "IgnoreProjector"="True" }
        Pass {
            Blend SrcAlpha OneMinusSrcAlpha, One OneMinusSrcAlpha
            ZWrite Off
            Cull Off
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"
            sampler2D _TextureSample5, _mask, _TextureSample3, _Texture, _Maskdisapearence, _Mask;
            float4 _TextureSample5_ST, _TextureSample3_ST, _Texture_ST, _Mask_ST;
            float4 _Color3, _Color9, _Color11, _Vector0, _Colortexture, _Colorlerp1, _Colorlerp2, _Tilingmask;
            float _Variant, _Float4, _Float12, _Disapearenceonoff, _Disapearence, _Divide, _Mask_smoothe, _Float0, _Float1, _opacity;
            struct VI { float4 pos : POSITION; float4 col : COLOR; float4 uv : TEXCOORD0; float4 c1 : TEXCOORD1; };
            struct VO { float4 pos : SV_POSITION; float4 col : COLOR; float2 uv : TEXCOORD0; float d : TEXCOORD1; };
            VO vert(VI i) {
                VO o;
                o.pos = UnityObjectToClipPos(i.pos);
                o.col = i.col;
                o.uv = i.uv.xy;
                o.d = i.c1.x;
                return o;
            }
            float4 frag(VO i) : SV_Target {
                bool v1 = _Variant < 1.5;
                float3 T = v1 ? tex2D(_TextureSample5, i.uv * _TextureSample5_ST.xy + _TextureSample5_ST.zw).rgb
                              : tex2D(_Texture, i.uv * _Texture_ST.xy + _Texture_ST.zw).rgb;
                float N = v1 ? tex2D(_mask, i.uv * _Vector0.xy).r : tex2D(_Maskdisapearence, i.uv * _Tilingmask.xy).r;
                float d = (!v1 && _Disapearenceonoff != 0) ? _Disapearence : i.d;
                float divide = v1 ? _Float4 : _Divide;
                float a = N <= d ? 1.0 : 0.0;
                float b = (d / max(divide, 1e-4)) >= N ? 1.0 : 0.0;
                float edge = a - b;
                float w = 2.0 * a - b;
                float M = v1 ? tex2D(_TextureSample3, i.uv * _TextureSample3_ST.xy + _TextureSample3_ST.zw).r
                             : tex2D(_Mask, i.uv * _Mask_ST.xy + _Mask_ST.zw).r;
                if (_Variant > 1.5 && _Variant < 2.5 && _Mask_smoothe != 0) M = smoothstep(_Float0, _Float1, M);
                float opacity = v1 ? _Float12 : _opacity;
                float alpha = saturate(w * M * T.r * i.col.a * opacity);
                clip(alpha - 1e-5);
                float3 rgb;
                if (v1) {
                    float3 tc9 = T * _Color9.rgb;
                    rgb = saturate(lerp(T, _Color3.rgb, edge) * w * (tc9 + T * (_Color11.rgb - tc9)) * i.col.rgb);
                } else if (_Variant < 2.5) {
                    float3 tct = T * _Colortexture.rgb;
                    rgb = w * lerp(tct + T * (_Colorlerp1.rgb - tct), _Colorlerp2.rgb, edge) * i.col.rgb;
                } else {
                    rgb = w * lerp(T, _Colorlerp2.rgb, edge) * i.col.rgb;
                }
                return float4(rgb, alpha);
            }
            ENDCG
        }
    }
}
