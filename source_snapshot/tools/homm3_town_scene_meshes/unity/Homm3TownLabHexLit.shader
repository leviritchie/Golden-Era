// Town-lab replica of the installed Hex/Lit Lit-pass formula (see docs/homm3_prebaked_lighting.md):
//   rgb = albedo * (_SunColor * saturate(dot(N, -_SunDir)) + _Ambient)
// Ambient: the scene's trilight (RenderSettings sky/equator/ground, linear), evaluated as a smooth
// hemisphere blend of the normal's y (an approximation of Unity's trilight SH probe). The spec passes
// the city rig: sun = colour.linear * intensity (game: linear colour space, lightsUseLinearIntensity).
// No tonemapping: output clamps at 1 (the game's post chain was not read).
// plus the city scene's linear fog (RenderSettings of cityHuman2) and optional alpha clip
// (HEX_ALPHA_CLIP_ENABLED materials). No normal map / specular / shadows: the installed Hex/Lit
// reads base colour only. Preview shader only; not a delivery shader.
// Cloth (town_full3d_cloth.py, _UseFlag 1): the installed Hex/Lit FLAG vertex wave (HEX_VERTEX_DISPLACEMENT_FLAG),
//   posWS += _FlagPower.xyz * sin(dot(posWS, _FlagDirection.xyz) + t * _FlagSpeed) * COLOR.r
// with t = _LabTime (global, set per render frame: the batch editor's _Time is wall clock); normals unchanged, as
// in the game. Both passes displace, so the depth texture follows the cloth.
// Culling matches the shipped state (2026-09-29, static read): in game the Mesh_ pieces are clones of the city's
// Hex/Lit donor (Homm3TownSceneMeshBundle.TryRebindRenderersToCityDonor; the lane pins _CullMode 2 on them), the
// installed Hex/Lit binds the Lit pass's cull to _CullMode (default 2 = Back; donor fence_field_mt 2.0) and its
// Lit-pass pixel shader reads no SV_IsFrontFace. So: Cull Back and no face flip. (Cull Off with a flipped normal
// painted every face seen from behind black; the game drops it, a see-through slit.)
Shader "Hidden/Homm3TownLab/HexLit" {
    Properties {
        _MainTex ("Color", 2D) = "white" {}
        _SunDir ("Sun travel dir (world)", Vector) = (0.91, -0.397, 0.112, 0)
        _SunColor ("Sun colour (linear)", Vector) = (1, 0.905, 0.672, 0)
        _FillDir ("Fill travel dir (world)", Vector) = (0, -1, 0, 0)
        _FillColor ("Fill colour (linear; 0 = none)", Vector) = (0, 0, 0, 0)
        _AmbSky ("Ambient sky (linear)", Vector) = (0.347, 0.418, 0.591, 0)
        _AmbEq ("Ambient equator (linear)", Vector) = (0.347, 0.418, 0.591, 0)
        _AmbGround ("Ambient ground (linear)", Vector) = (0.347, 0.418, 0.591, 0)
        _FogColor ("Fog colour (linear)", Vector) = (0.58, 0.77, 0.77, 0)
        _FogRange ("Fog start/end/enabled", Vector) = (16.1, 92.12, 0, 0)
        _Clip ("Alpha clip", Float) = 0
        _UseFlag ("Hex/Lit FLAG wave (0/1)", Float) = 0
        _FlagDirection ("Flag direction (world)", Vector) = (0, 0, 0, 0)
        _FlagPower ("Flag power (world)", Vector) = (0, 0, 0, 0)
        _FlagSpeed ("Flag speed", Float) = 0
    }
    SubShader {
        Tags { "RenderType"="Opaque" }
        Cull Back
        Pass {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"
            float4 _MainTex_ST;
            float4 _SunDir, _SunColor, _FillDir, _FillColor, _AmbSky, _AmbEq, _AmbGround, _FogColor, _FogRange;
            float _Clip;
            float _UseFlag, _FlagSpeed, _LabTime;
            float4 _FlagDirection, _FlagPower;
            Texture2D<float4> _MainTex;
            SamplerState sampler_MainTex;
            struct VI { float4 pos : POSITION; float3 nrm : NORMAL; float2 uv : TEXCOORD0; float4 color : COLOR; };
            struct VO { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; float3 nws : TEXCOORD1; float3 wpos : TEXCOORD2; };
            VO vert(VI i) {
                VO o;
                o.uv = i.uv * _MainTex_ST.xy + _MainTex_ST.zw;
                o.nws = UnityObjectToWorldNormal(i.nrm);
                o.wpos = mul(unity_ObjectToWorld, float4(i.pos.xyz, 1)).xyz;
                if (_UseFlag > 0.5)
                    o.wpos += _FlagPower.xyz * sin(dot(o.wpos, _FlagDirection.xyz) + _LabTime * _FlagSpeed) * i.color.r;
                o.pos = mul(UNITY_MATRIX_VP, float4(o.wpos, 1));
                return o;
            }
            float4 frag(VO i) : SV_Target {
                float4 albedo = _MainTex.Sample(sampler_MainTex, i.uv);
                if (_Clip > 0.5 && albedo.a < 0.5) discard;
                float3 n = normalize(i.nws);
                float ndl = saturate(dot(n, -normalize(_SunDir.xyz)));
                float3 amb = n.y >= 0 ? lerp(_AmbEq.rgb, _AmbSky.rgb, sqrt(n.y)) : lerp(_AmbEq.rgb, _AmbGround.rgb, sqrt(-n.y));
                float fdl = saturate(dot(n, -normalize(_FillDir.xyz)));
                float3 rgb = albedo.rgb * (_SunColor.rgb * ndl + _FillColor.rgb * fdl + amb);
                if (_FogRange.z > 0.5) {
                    float d = distance(i.wpos, _WorldSpaceCameraPos);
                    float f = saturate((_FogRange.y - d) / (_FogRange.y - _FogRange.x));
                    rgb = lerp(_FogColor.rgb, rgb, f);
                }
                return float4(rgb, 1);
            }
            ENDCG
        }
        // Depth for the editor's camera depth texture (built-in renderer: drawn with the ShadowCaster pass). Only the
        // opt-in SSR water reads it; the scene has no shadow-casting light, so nothing else changes. The game's own
        // Hex/Lit has DepthOnly / SHADOWCASTER passes for the same role.
        Pass {
            Tags { "LightMode"="ShadowCaster" }
            ZWrite On
            CGPROGRAM
            #pragma vertex vertSc
            #pragma fragment fragSc
            #include "UnityCG.cginc"
            float4 _MainTex_ST;
            float _Clip;
            float _UseFlag, _FlagSpeed, _LabTime;
            float4 _FlagDirection, _FlagPower;
            Texture2D<float4> _MainTex;
            SamplerState sampler_MainTex;
            struct VSc { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; };
            VSc vertSc(float4 pos : POSITION, float2 uv : TEXCOORD0, float4 color : COLOR) {
                VSc o;
                float3 w = mul(unity_ObjectToWorld, float4(pos.xyz, 1)).xyz;
                if (_UseFlag > 0.5)
                    w += _FlagPower.xyz * sin(dot(w, _FlagDirection.xyz) + _LabTime * _FlagSpeed) * color.r;
                o.pos = mul(UNITY_MATRIX_VP, float4(w, 1));
                o.uv = uv * _MainTex_ST.xy + _MainTex_ST.zw;
                return o;
            }
            float4 fragSc(VSc i) : SV_Target {
                if (_Clip > 0.5 && _MainTex.Sample(sampler_MainTex, i.uv).a < 0.5) discard;
                return 0;
            }
            ENDCG
        }
    }
}
