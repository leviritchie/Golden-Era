// Conflux full-3D town: moving aurora curtains for the Grail (tbelholy).
// Mesh: curtain strips, UV0 u = along the curtain (0..1), v = bottom (0) to top (1). Vertical rays are noise
// sampled with a long vertical period, drifting along u at two speeds; the curtain folds (a u-warp that travels) and
// its brightness breathes. Colours follow the HoMM3 grail art: green at the hem, rose and violet above.
// Additive, no depth write, so the peaks in front occlude it. Drawn by a bone-less SkinnedMeshRenderer (kept by the
// town runtime). Proof tier: generated artifact; unproven in game.
Shader "Homm3Conflux/Aurora" {
    Properties {
        _Noise ("Ray noise", 2D) = "gray" {}
        _Noise2 ("Fold noise", 2D) = "gray" {}
        _ColorLow ("Hem colour (HDR)", Color) = (0.35, 1.0, 0.6, 1)
        _ColorMid ("Middle colour (HDR)", Color) = (1.0, 0.45, 0.75, 1)
        _ColorHigh ("Top colour (HDR)", Color) = (0.55, 0.35, 1.0, 1)
        _Intensity ("Intensity", Float) = 1.3
        _Drift ("Ray drift (u/s)", Float) = 0.012
        _Fold ("Fold amplitude", Float) = 0.035
        _Rays ("Ray count", Float) = 5
        _TimeOffset ("Time offset (s, editor renders)", Float) = 0
        _TimeScale ("Time scale (0 = frozen, editor renders)", Float) = 1
    }
    SubShader {
        Tags { "Queue"="Transparent-50" "RenderType"="Transparent" "IgnoreProjector"="True" }
        Pass {
            Blend One One
            ZWrite Off
            Cull Off
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"
            sampler2D _Noise, _Noise2;
            float4 _ColorLow, _ColorMid, _ColorHigh;
            float _Intensity, _Drift, _Fold, _Rays, _TimeOffset, _TimeScale;
            struct VI { float4 pos : POSITION; float2 uv : TEXCOORD0; };
            struct VO { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; };
            VO vert(VI i) { VO o; o.pos = UnityObjectToClipPos(i.pos); o.uv = i.uv; return o; }
            float4 frag(VO i) : SV_Target {
                float t = _Time.y * _TimeScale + _TimeOffset;
                float u = i.uv.x, v = i.uv.y;
                // Travelling folds: the curtain's u shifts with height and time.
                float fold = tex2D(_Noise2, float2(u * 1.3 + t * 0.01, v * 0.35 + t * 0.02)).r - 0.5;
                float uw = u + _Fold * sin(v * 2.4 + u * 9.0 + t * 0.35) + fold * _Fold * 2.0;
                // Vertical rays: noise stretched vertically, two layers drifting in opposite directions.
                float r1 = tex2D(_Noise, float2(uw * _Rays + t * _Drift, v * 0.08 + t * 0.004)).r;
                float r2 = tex2D(_Noise, float2(uw * _Rays * 1.9 - t * _Drift * 1.6 + 0.43, v * 0.05 + 0.3)).r;
                float rays = saturate(r1 * 1.25 - 0.2) * 0.65 + saturate(r2 * 1.3 - 0.35) * 0.55;
                rays = rays * rays * 1.8;
                // Bright hem with a soft top; fade at both curtain ends.
                float hem = smoothstep(0.0, 0.1, v) * (1.0 - smoothstep(0.45, 1.0, v));
                float edge = smoothstep(0.0, 0.18, u) * (1.0 - smoothstep(0.82, 1.0, u));
                float breathe = 0.75 + 0.25 * sin(t * 0.45 + u * 5.0);
                float3 c = v < 0.35 ? lerp(_ColorLow.rgb, _ColorMid.rgb, v / 0.35)
                                    : lerp(_ColorMid.rgb, _ColorHigh.rgb, saturate((v - 0.35) / 0.65));
                float a = rays * hem * edge * breathe * _Intensity;
                return float4(c * a, 0);
            }
            ENDCG
        }
    }
}
