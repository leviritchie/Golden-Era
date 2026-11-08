// Conflux full-3D town: the magic portal's energy surface (tbeldw_5 / tbeldw_5_2), replacing the phase-1 rigidly
// spinning painted disc. Mesh: a camera-facing disc, UV0 in [0,1]^2 about its centre. In polar coordinates the
// surface turns faster toward the centre (differential rotation), so the spiral arms wind in and are drawn toward
// the eye instead of rotating as one plate; an inflow noise travels inward along r. Cyan/blue after the HoMM3 art,
// with a bright core. Premultiplied alpha. Drawn by a bone-less SkinnedMeshRenderer (kept by the town runtime).
// Proof tier: generated artifact; unproven in game.
Shader "Homm3Conflux/Portal" {
    Properties {
        _Noise ("Swirl noise", 2D) = "gray" {}
        _Noise2 ("Inflow noise", 2D) = "gray" {}
        _ColorEdge ("Edge colour (HDR)", Color) = (0.15, 0.35, 1.2, 1)
        _ColorMid ("Arm colour (HDR)", Color) = (0.35, 0.9, 1.6, 1)
        _ColorCore ("Core colour (HDR)", Color) = (1.6, 1.9, 2.2, 1)
        _Spin ("Spin (rad/s at the rim)", Float) = 0.6
        _Arms ("Arms", Float) = 3
        _Wind ("Arm winding", Float) = 7
        _Opacity ("Opacity", Float) = 0.92
        _TimeOffset ("Time offset (s, editor renders)", Float) = 0
        _TimeScale ("Time scale (0 = frozen, editor renders)", Float) = 1
    }
    SubShader {
        Tags { "Queue"="Transparent" "RenderType"="Transparent" "IgnoreProjector"="True" }
        Pass {
            Blend One OneMinusSrcAlpha
            ZWrite Off
            Cull Off
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"
            sampler2D _Noise, _Noise2;
            float4 _ColorEdge, _ColorMid, _ColorCore;
            float _Spin, _Arms, _Wind, _Opacity, _TimeOffset, _TimeScale;
            struct VI { float4 pos : POSITION; float2 uv : TEXCOORD0; };
            struct VO { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; };
            VO vert(VI i) { VO o; o.pos = UnityObjectToClipPos(i.pos); o.uv = i.uv; return o; }
            float4 frag(VO i) : SV_Target {
                float t = _Time.y * _TimeScale + _TimeOffset;
                float2 p = i.uv * 2 - 1;
                float r = length(p);
                float th = atan2(p.y, p.x);
                float omega = _Spin * (1.0 + 1.6 / (r + 0.25));      // faster toward the centre
                float ang = th + t * omega;
                float arms = 0.5 + 0.5 * sin(_Arms * ang + _Wind * r * 3.14159);
                float2 pu = float2(ang / 6.28318 * 2.0, r * 0.9 + t * 0.12);      // noise flows inward along r
                float n1 = tex2D(_Noise, pu).r;
                float n2 = tex2D(_Noise2, float2(ang / 6.28318 * 3.0 + 0.3, r * 1.7 + t * 0.2)).r;
                float swirl = saturate(arms * 0.7 + n1 * 0.55 + n2 * 0.25 - 0.3);
                float3 c = lerp(_ColorEdge.rgb, _ColorMid.rgb, swirl);
                float core = 1.0 - smoothstep(0.0, 0.35, r);
                c = lerp(c, _ColorCore.rgb, core * core);
                float rim = 1.0 - smoothstep(0.9, 1.0, r);
                float a = rim * _Opacity * saturate(0.55 + 0.45 * swirl + core);
                return float4(c * a, a);
            }
            ENDCG
        }
    }
}
