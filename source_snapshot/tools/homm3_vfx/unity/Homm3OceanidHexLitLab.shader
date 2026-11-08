// HOMM3_VFX_LAB_GENERATED: managed by tools/homm3_vfx/oceanid_unity_lab.py. Lab-only; NOT a delivery shader.
// Pipeline-independent replica of the installed Hex/Lit Lit pass, extended with the Hex/Lit features the
// installed bytecode shows (static read, artifacts/homm3_vfx_experiments/oceanid/evidence/hex_lit_vs/):
//   uv  = (uv0 + _UvScroll.xy * _Time.y) * _MainTex_ST.xy + _MainTex_ST.zw        (every vertex program)
//   pos = worldPos + _FlagPower.xyz * sin(dot(worldPos, _FlagDirection.xyz) + _Time.y * _FlagSpeed) * COLOR.r
//         (HEX_VERTEX_DISPLACEMENT_FLAG variants)
//   rgb = albedo * (_SunColor * saturate(N.L) + _Ambient)                        (Lit pass, no shadows here)
// _LabTime stands in for _Time.y so renders are deterministic. _MaskMode 1 outputs the vertex colour
// (r = water, g = foam) for region masks. Blend state is exposed so the shell can be translucent.
Shader "Hidden/Homm3VfxLab/OceanidHexLitLab" {
    Properties {
        _MainTex ("Color", 2D) = "white" {}
        _Color ("Tint", Color) = (1,1,1,1)
        _UvScroll ("Scroll", Vector) = (0,0,0,0)
        _LabTime ("Lab time (s)", Float) = 0
        _FlagEnabled ("Flag displacement on", Float) = 0
        _FlagDirection ("Flag direction", Vector) = (0,0,15,0)
        _FlagPower ("Flag power", Vector) = (0.1,0,0.1,0)
        _FlagSpeed ("Flag speed", Float) = 5
        _SunDir ("Sun travel dir (world)", Vector) = (0.624, -0.4035, 0.6692, 0)
        _SunColor ("Sun colour (linear)", Vector) = (1, 0.905, 0.672, 0)
        _Ambient ("Ambient (linear)", Vector) = (0.347, 0.418, 0.591, 0)
        _MaskMode ("Mask mode", Float) = 0
        _SrcBlend ("Src", Float) = 1
        _DstBlend ("Dst", Float) = 0
        _ZWrite ("ZWrite", Float) = 1
        _Cull ("Cull", Float) = 2
    }
    SubShader {
        Tags { "RenderType"="Opaque" }
        Pass {
            Blend [_SrcBlend] [_DstBlend]
            ZWrite [_ZWrite]
            Cull [_Cull]
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"
            float4 _MainTex_ST;
            float4 _UvScroll, _FlagDirection, _FlagPower, _Color;
            float _LabTime, _FlagEnabled, _FlagSpeed, _MaskMode;
            float4 _SunDir, _SunColor, _Ambient;
            Texture2D<float4> _MainTex;
            SamplerState sampler_MainTex;
            struct VI { float4 pos : POSITION; float3 nrm : NORMAL; float2 uv : TEXCOORD0; float4 col : COLOR; };
            struct VO { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; float3 nws : TEXCOORD1; float4 col : TEXCOORD2; };
            VO vert(VI i) {
                VO o;
                float3 w = mul(unity_ObjectToWorld, float4(i.pos.xyz, 1)).xyz;
                if (_FlagEnabled > 0.5) {
                    float s = sin(dot(w, _FlagDirection.xyz) + _LabTime * _FlagSpeed);
                    w += _FlagPower.xyz * s * i.col.r;
                }
                o.pos = mul(UNITY_MATRIX_VP, float4(w, 1));
                o.uv = (i.uv + _UvScroll.xy * _LabTime) * _MainTex_ST.xy + _MainTex_ST.zw;
                o.nws = UnityObjectToWorldNormal(i.nrm);
                o.col = i.col;
                return o;
            }
            float4 frag(VO i) : SV_Target {
                if (_MaskMode > 0.5)
                    return float4(i.col.r, i.col.g, 0, 1);
                float3 n = normalize(i.nws);
                float ndl = saturate(dot(n, -normalize(_SunDir.xyz)));
                float4 albedo = _MainTex.Sample(sampler_MainTex, i.uv) * _Color;
                return float4(albedo.rgb * (_SunColor.rgb * ndl + _Ambient.rgb), albedo.a);
            }
            ENDCG
        }
    }
}
