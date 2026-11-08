// Town ambient aurora (town_full3d_ambient fxmesh kinds, e.g. bulwark aurora_curtain). A real curtain, not dots:
// Mesh: a ribbon strip, UV0 u = along the curtain (0..1), v = hem (0) to top (1), with a skirt below (v < 0) for the soft fade; uv2.x = the curtain's length in
// ray periods (so rays keep their width on long and short curtains), uv2.y = a per-curtain phase.
// Look (after photographs of auroral curtains): a thin bright green hem that ripples and kinks, sheaves of fine
// vertical rays rising from it and fading into violet, brightness surges that run along the curtain, and folds that
// travel sideways (the vertex shader sways the ribbon in the prefab x/z plane, so the folds really move in 3D and
// overlap where the curtain turns). Additive, no depth write, depth-tested so the peaks in front occlude it.
// _TimeOffset/_TimeScale: the editor motion renders freeze _Time and drive t (Homm3TownScene3dBundleBuild).
Shader "Homm3Town/Aurora" {
    Properties {
        _Noise ("Ray noise", 2D) = "gray" {}
        _Noise2 ("Fold noise", 2D) = "gray" {}
        _ColorHem ("Hem colour (HDR)", Color) = (0.55, 1.0, 0.6, 1)
        _ColorLow ("Lower curtain colour (HDR)", Color) = (0.2, 1.0, 0.55, 1)
        _ColorHigh ("Top colour (HDR)", Color) = (0.55, 0.3, 1.0, 1)
        _Intensity ("Intensity", Float) = 1.0
        _HemWidth ("Hem width (v)", Float) = 0.05
        _HemSoft ("Hem softness below (v)", Float) = 0.015
        _RayFade ("Ray fade upward (1/v)", Float) = 2.2
        _Drift ("Ray drift (periods/s)", Float) = 0.15
        _Surge ("Surge speed (u/s)", Float) = 0.05
        _Sway ("Fold sway (prefab units)", Float) = 0
        _SwayFreq ("Folds along the curtain", Float) = 2.5
        _SwaySpeed ("Fold travel (rad/s)", Float) = 0.25
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
            float4 _ColorHem, _ColorLow, _ColorHigh;
            float _Intensity, _HemWidth, _HemSoft, _RayFade, _Drift, _Surge, _Sway, _SwayFreq, _SwaySpeed, _TimeOffset, _TimeScale;
            struct VI { float4 pos : POSITION; float2 uv : TEXCOORD0; float2 uv2 : TEXCOORD1; };
            struct VO { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; float2 info : TEXCOORD1; float fold : TEXCOORD2; };
            float T() { return _Time.y * _TimeScale + _TimeOffset; }
            VO vert(VI i) {
                VO o;
                float t = T();
                float u = i.uv.x, v = i.uv.y, ph = i.uv2.y;
                // travelling folds: the ribbon sways along x and z, more at the top than the hem (the hem is the
                // bright, slowly kinking base; the rays above swing like a hanging drape)
                float s = sin(u * _SwayFreq * 6.2832 - t * _SwaySpeed + ph) * 0.7
                        + sin(u * _SwayFreq * 2.7 * 6.2832 + t * _SwaySpeed * 1.7 + ph * 2.3) * 0.3;
                float4 p = i.pos;
                p.x += _Sway * s * (0.35 + 0.65 * v);
                p.z += _Sway * 1.6 * cos(u * _SwayFreq * 6.2832 - t * _SwaySpeed + ph) * (0.35 + 0.65 * v);
                o.pos = UnityObjectToClipPos(p);
                o.uv = i.uv;
                o.info = i.uv2;
                // where the drape turns (sway at its extreme) it is seen edge-on: a bright fold band
                o.fold = sin(u * _SwayFreq * 6.2832 - t * _SwaySpeed + ph);
                return o;
            }
            float4 frag(VO i) : SV_Target {
                float t = T();
                float u = i.uv.x, v = i.uv.y, L = max(i.info.x, 1.0), ph = i.info.y;
                float ur = u * L;                                   // along the curtain, in ray periods
                // the hem ripples and kinks: its height wanders along the curtain and in time
                float kink = tex2D(_Noise2, float2(ur * 0.05 + t * 0.006 + ph, t * 0.01)).r - 0.5;
                float vh = v - 0.06 * kink - 0.02 * sin(ur * 0.4 + t * 0.6 + ph);
                // rays: vertical streak noise (TileNoise_19) at two scales drifting opposite ways, over a glowing sheet
                // (a curtain is a luminous veil with brighter sheaves in it, not a row of separate lines)
                float r1 = tex2D(_Noise, float2(ur * 0.07 + t * _Drift * 0.07, vh * 0.12 + ph)).r;
                float r2 = tex2D(_Noise, float2(ur * 0.19 - t * _Drift * 0.11 + 0.37, vh * 0.09 + ph * 1.7)).r;
                float rays = saturate(r1 * 1.25 - 0.2) * 0.75 + saturate(r2 * 1.4 - 0.45) * 0.45;
                float sheet = 0.32 + rays * rays * 1.1;
                // ragged top: the curtain's height wanders along it and slowly in time
                float top = 0.45 + 0.55 * tex2D(_Noise2, float2(ur * 0.012 + ph * 0.3, t * 0.004 + 0.5)).r;
                // vertical profile: nothing below the hem, a bright hem band, the sheet fading upward to its ragged top
                float below = smoothstep(-0.02 - _HemSoft, _HemSoft, vh);
                float hem = exp(-pow(max(vh, 0) / max(_HemWidth, 1e-3), 2.0)) * (1.0 - smoothstep(0.0, 0.15, _HemSoft) * 0.6);
                float body = exp(-max(vh, 0) * _RayFade) * (1.0 - smoothstep(top * 0.55, top, v));
                // surges: brightness running along the curtain, plus slow breathing of the whole curtain
                float surge = 0.5 + 0.5 * sin((u - t * _Surge) * 6.2832 * 1.3 + ph);
                surge = 0.45 + 0.55 * surge * surge;
                surge *= 0.8 + 0.2 * sin(t * 0.37 + ph * 3.0);
                float fold = 0.75 + 0.9 * pow(1.0 - abs(i.fold), 6.0);
                float ends = smoothstep(0.0, 0.14, u) * (1.0 - smoothstep(0.86, 1.0, u));
                float3 cRay = lerp(_ColorLow.rgb, _ColorHigh.rgb, smoothstep(0.2, 0.9, v / top));
                float3 c = _ColorHem.rgb * hem * (0.7 + 0.5 * rays) * 1.3 + cRay * body * sheet;
                c *= fold;
                return float4(c * below * surge * ends * _Intensity, 0);
            }
            ENDCG
        }
    }
}
