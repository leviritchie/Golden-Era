// HOMM3_VFX_LAB_GENERATED: managed by tools/homm3_vfx/titan_light_lab.py. Lab-only shader, not a delivery shader.
// Replica of the installed Hex/Lit Lit-pass formula (static DXBC read, artifacts/homm3_prebaked_lighting/
// hex_lit_ps/ps_o0_t4_n150.txt), extended from tools/homm3_prebake/unity/Homm3PrebakeHexLitReplica.shader
// with the bytecode's per-object point-light loop:
//   rgb = albedo * (ambient + sun * saturate(N.L) + sum_i col_i * atten_i * saturate(N.L_i))
//   atten_i = saturate(1 - (d2 * invRange2)^2)^2 / max(d2, 1e-5)      (cb2[40+i].w = 1/range^2)
// Shadows, spot cones, the screen-space ambient texture and the desaturation branch are omitted.
Shader "Hidden/Homm3Vfx/HexLitReplicaPoint" {
    Properties {
        _MainTex ("Color", 2D) = "white" {}
        _SunDir ("Sun travel dir (world)", Vector) = (0.624, -0.4035, 0.6692, 0)
        _SunColor ("Sun colour (linear)", Vector) = (1, 0.905, 0.672, 0)
        _Ambient ("Ambient (linear)", Vector) = (0.347, 0.418, 0.591, 0)
    }
    SubShader {
        Tags { "RenderType"="Opaque" }
        Pass {
            Cull Off
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"
            float4 _MainTex_ST;
            float4 _SunDir, _SunColor, _Ambient;
            // lab-set point lights (world position, linear colour x intensity, 1/range^2)
            float4 _PLPos[4];
            float4 _PLCol[4];
            float _PLInvRange2[4];
            float _PLCount;
            Texture2D<float4> _MainTex;
            SamplerState sampler_MainTex;
            struct VI { float4 pos : POSITION; float3 nrm : NORMAL; float2 uv : TEXCOORD0; };
            struct VO { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; float3 nws : TEXCOORD1; float3 pws : TEXCOORD2; };
            VO vert(VI i) {
                VO o;
                o.uv = i.uv * _MainTex_ST.xy + _MainTex_ST.zw;
                o.nws = UnityObjectToWorldNormal(i.nrm);
                o.pws = mul(unity_ObjectToWorld, float4(i.pos.xyz, 1)).xyz;
                o.pos = UnityObjectToClipPos(i.pos.xyz);
                return o;
            }
            float4 frag(VO i, bool front : SV_IsFrontFace) : SV_Target {
                float3 n = normalize(i.nws) * (front ? 1 : -1);
                float3 light = _Ambient.rgb + _SunColor.rgb * saturate(dot(n, -normalize(_SunDir.xyz)));
                for (int k = 0; k < 4; k++) {
                    if (k >= (int)_PLCount) break;
                    float3 d = _PLPos[k].xyz - i.pws;
                    float d2 = max(dot(d, d), 1e-5);
                    float s = d2 * _PLInvRange2[k];
                    s = max(1 - s * s, 0);
                    float atten = s * s / d2;
                    light += _PLCol[k].rgb * atten * saturate(dot(n, d * rsqrt(d2)));
                }
                float4 albedo = _MainTex.Sample(sampler_MainTex, i.uv);
                return float4(albedo.rgb * light, 1);
            }
            ENDCG
        }
    }
}
