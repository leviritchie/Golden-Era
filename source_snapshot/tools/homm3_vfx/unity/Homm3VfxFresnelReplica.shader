// HOMM3_VFX_LAB_GENERATED: managed by tools/homm3_vfx/vanilla_style_lab.py. Lab-only shader, not a delivery shader.
// Replica of the installed `magic/Fresnel` (vanilla ability shells: griffin_upg fresnel_emissary_vfx, the Lightweaver
// fresnel meshes), read from its DXBC (d3dcompiler D3DDisassemble of the installed programs 0 and 8; cbuffer slots
// named from the pass m_NameIndices; 2026-09-27, static bytecode only). Inputs: world pos, TEXCOORD0.xyz, world normal,
// vertex COLOR (Unity supplies whatever the mesh has; the lab does not invent one).
//   F     = (_Bias + _FresnelScale * max(1 - N.V, 1e-4)^_FresnelPower) * _MultiplyFresnel       V = normalize(cam - pos)
//   mask  = _SlideMask != 0 ? tex(t1, uv.xy + (0, _Customslideopacityoffon != 0 ? uv.z : 0)).r
//                           : smoothstep(_MinSmoothe, _MaxSmoothe, uv.y)
//   a     = mask * F * vcol.a  (saturated when _ToggleOpacity != 0);  discard a <= 0
//   T     = tex(_MainTex, uv.xy * _TexSpeedandTile.zw + _Time.y * _TexSpeedandTile.xy)
//   rgb   = sat(T.rgb * _Emission + F) * _Color.rgb + sat(F) * _EdgeColor.rgb * _EdgePower
//           + (_EdgeSaturate != 0 ? _Edgesaturatefloat : sat(F))
//   rgb  *= (1 + _Height - uv.y * _TexSpeedandTile.w) * vcol.rgb ;  saturated when _ToggleEmission != 0
//   out   = (rgb, sat(a))  Blend SrcAlpha OneMinusSrcAlpha, ZWrite Off (as the original)
// t1 (the slide mask) is bound from `_SlideTex` when a material lists a second texture; the vanilla materials probed so
// far run _SlideMask 0 (uv.y smoothstep). Omitted: _HexFade (fog of war). _LabTime stands in for _Time.y.
Shader "Hidden/Homm3Vfx/FresnelReplica" {
    Properties {
        _MainTex ("T", 2D) = "white" {}
        _SlideTex ("Slide mask", 2D) = "white" {}
        _TexSpeedandTile ("Speed xy, tile zw", Vector) = (0,0,1,1)
        _Height ("", Float) = 0
        _EdgeColor ("", Color) = (1,1,1,1)
        _Bias ("", Float) = 0
        _FresnelScale ("", Float) = 1
        _FresnelPower ("", Float) = 1
        _MultiplyFresnel ("", Float) = 1
        _EdgePower ("", Float) = 1
        _Color ("", Color) = (1,1,1,1)
        _Emission ("", Float) = 1
        _EdgeSaturate ("", Float) = 0
        _Edgesaturatefloat ("", Float) = 0
        _ToggleOpacity ("", Float) = 0
        _ToggleEmission ("", Float) = 0
        _SlideMask ("", Float) = 0
        _MinSmoothe ("", Float) = 0
        _MaxSmoothe ("", Float) = 1
        _Customslideopacityoffon ("", Float) = 0
        _LabTime ("", Float) = 0
    }
    SubShader {
        Tags { "Queue"="Transparent" "RenderType"="Transparent" }
        Pass {
            Blend SrcAlpha OneMinusSrcAlpha
            ZWrite Off
            Cull Back
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"
            float4 _TexSpeedandTile, _EdgeColor, _Color;
            float _Height, _Bias, _FresnelScale, _FresnelPower, _MultiplyFresnel, _EdgePower, _Emission, _EdgeSaturate,
                  _Edgesaturatefloat, _ToggleOpacity, _ToggleEmission, _SlideMask, _MinSmoothe, _MaxSmoothe,
                  _Customslideopacityoffon, _LabTime;
            sampler2D _MainTex, _SlideTex;
            struct VI { float4 pos : POSITION; float4 col : COLOR; float3 uv : TEXCOORD0; float3 nrm : NORMAL; };
            struct VO { float4 pos : SV_POSITION; float3 pws : TEXCOORD0; float3 uv : TEXCOORD1; float3 nws : TEXCOORD2; float4 col : COLOR; };
            VO vert(VI i) {
                VO o;
                o.pws = mul(unity_ObjectToWorld, float4(i.pos.xyz, 1)).xyz;
                o.pos = UnityObjectToClipPos(i.pos.xyz);
                o.uv = i.uv;
                o.nws = UnityObjectToWorldNormal(i.nrm);
                o.col = i.col;
                return o;
            }
            float4 frag(VO i) : SV_Target {
                float3 v = normalize(_WorldSpaceCameraPos - i.pws);
                float f = max(1 - dot(i.nws, v), 1e-4);
                f = (_Bias + _FresnelScale * pow(f, _FresnelPower)) * _MultiplyFresnel;
                float t = saturate((i.uv.y - _MinSmoothe) / (_MaxSmoothe - _MinSmoothe));
                float mask = t * t * (3 - 2 * t);
                float2 suv = i.uv.xy + float2(0, _Customslideopacityoffon != 0 ? i.uv.z : 0);
                if (_SlideMask != 0) mask = tex2D(_SlideTex, suv).r;
                float a = mask * f * i.col.a;
                if (_ToggleOpacity != 0) a = saturate(a);
                clip(a <= 0 ? -1 : 1);
                float3 T = tex2D(_MainTex, i.uv.xy * _TexSpeedandTile.zw + _LabTime * _TexSpeedandTile.xy).rgb;
                float3 rgb = saturate(T * _Emission + f) * _Color.rgb + saturate(f) * _EdgeColor.rgb * _EdgePower;
                rgb += _EdgeSaturate != 0 ? _Edgesaturatefloat : saturate(f);
                rgb *= (1 + _Height - i.uv.y * _TexSpeedandTile.w) * i.col.rgb;
                if (_ToggleEmission != 0) rgb = saturate(rgb);
                return float4(rgb, saturate(a));
            }
            ENDCG
        }
    }
}
