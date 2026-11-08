// Pipeline-independent replica of the installed Hex/Lit Lit-pass formula (static bytecode read):
//   rgb = albedo * (_SunColor * saturate(dot(N, -_SunDir)) + _Ambient)
// No normal map, no specular, no shadows (the game's screen-space shadow term is omitted).
// Colours are linear. Used only by the prebaked-lighting Unity preview; not a delivery shader.
Shader "Hidden/Homm3Prebake/HexLitReplica" {
    Properties {
        _MainTex ("Color", 2D) = "white" {}
        _SunDir ("Sun travel dir (world)", Vector) = (0.624, -0.4035, 0.6692, 0)
        _SunColor ("Sun colour (linear)", Vector) = (1, 0.905, 0.672, 0)
        _Ambient ("Ambient (linear)", Vector) = (0.347, 0.418, 0.591, 0)
    }
    SubShader {
        Tags { "RenderType"="Opaque" }
        Pass {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"
            float4 _MainTex_ST;
            float4 _SunDir, _SunColor, _Ambient;
            Texture2D<float4> _MainTex;
            SamplerState sampler_MainTex;
            struct VI { float4 pos : POSITION; float3 nrm : NORMAL; float2 uv : TEXCOORD0; };
            struct VO { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; float3 nws : TEXCOORD1; };
            VO vert(VI i) {
                VO o;
                o.uv = i.uv * _MainTex_ST.xy + _MainTex_ST.zw;
                o.nws = UnityObjectToWorldNormal(i.nrm);
                o.pos = UnityObjectToClipPos(i.pos.xyz);
                return o;
            }
            float4 frag(VO i) : SV_Target {
                float3 n = normalize(i.nws);
                float ndl = saturate(dot(n, -normalize(_SunDir.xyz)));
                float4 albedo = _MainTex.Sample(sampler_MainTex, i.uv);
                return float4(albedo.rgb * (_SunColor.rgb * ndl + _Ambient.rgb), 1);
            }
            ENDCG
        }
    }
}
