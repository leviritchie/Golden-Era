// HOMM3_VFX_LAB_GENERATED: managed by tools/homm3_vfx/vanilla_style_lab.py. Lab-only shader, not a delivery shader.
// Hex/Lit replica (Homm3VfxHexLitReplicaPoint.shader: ambient + sun N.L + up to 4 point lights with the
// installed bytecode's attenuation) plus the Hex/Lit emission variant's inputs (HEX_EMISSION_MAP_ENABLED:
// _EmissionTex, HDR _EmissionColor, _EmissionMinPower / _EmissionBlinkSpeed / _EmissionBlinkPower) and alpha clip.
// ASSUMPTION (the emission math was not located in the bytecode):
//   rgb += emissionTex.rgb * _EmissionColor.rgb * (_EmissionMinPower + _EmissionBlinkPower * (0.5 + 0.5 sin(2 pi speed t)))
// FLAG wave is the installed Hex/Lit vertex path: posWS += _FlagPower * sin(dot(posWS, _FlagDirection)
// + time * _FlagSpeed) * COLOR.r. The lab enables it only on a GLB baked with a nonzero COLOR_0.r mask.
Shader "Hidden/Homm3Vfx/HexLitEmissionReplica" {
    Properties {
        _MainTex ("Color", 2D) = "white" {}
        _EmissionTex ("Emission", 2D) = "black" {}
        _EmissionColor ("Emission colour (HDR)", Color) = (0,0,0,1)
        _EmissionMinPower ("", Float) = 1
        _EmissionBlinkSpeed ("", Float) = 0
        _EmissionBlinkPower ("", Float) = 0
        _Cutoff ("Alpha clip", Float) = 0
        _LabTime ("", Float) = 0
        _UseFlag ("", Float) = 0
        _FlagDirection ("", Vector) = (0,0,0,0)
        _FlagPower ("", Vector) = (0,0,0,0)
        _FlagSpeed ("", Float) = 0
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
            float4 _SunDir, _SunColor, _Ambient, _EmissionColor;
            float _EmissionMinPower, _EmissionBlinkSpeed, _EmissionBlinkPower, _Cutoff, _LabTime;
            float _UseFlag, _FlagSpeed;
            float4 _FlagDirection, _FlagPower;
            float4 _PLPos[4];
            float4 _PLCol[4];
            float _PLInvRange2[4];
            float _PLCount;
            sampler2D _MainTex, _EmissionTex;
            struct VI { float4 pos : POSITION; float3 nrm : NORMAL; float2 uv : TEXCOORD0; float4 color : COLOR; };
            struct VO { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; float2 uv0 : TEXCOORD3; float3 nws : TEXCOORD1; float3 pws : TEXCOORD2; };
            VO vert(VI i) {
                VO o;
                o.uv = i.uv * _MainTex_ST.xy + _MainTex_ST.zw;
                o.uv0 = i.uv;
                o.nws = UnityObjectToWorldNormal(i.nrm);
                o.pws = mul(unity_ObjectToWorld, float4(i.pos.xyz, 1)).xyz;
                if (_UseFlag > 0.5) {
                    float phase = dot(o.pws, _FlagDirection.xyz) + _LabTime * _FlagSpeed;
                    o.pws += _FlagPower.xyz * sin(phase) * i.color.r;
                }
                o.pos = mul(UNITY_MATRIX_VP, float4(o.pws, 1));
                return o;
            }
            float4 frag(VO i, bool front : SV_IsFrontFace) : SV_Target {
                float4 albedo = tex2D(_MainTex, i.uv);
                if (_Cutoff > 0) clip(albedo.a - _Cutoff);
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
                float pulse = _EmissionMinPower + _EmissionBlinkPower * (0.5 + 0.5 * sin(6.2831853 * _EmissionBlinkSpeed * _LabTime));
                float3 emi = tex2D(_EmissionTex, i.uv0).rgb * _EmissionColor.rgb * pulse;
                return float4(albedo.rgb * light + emi, 1);
            }
            ENDCG
        }
    }
}
