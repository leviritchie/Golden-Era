// Conflux full-3D town: moving lava in the fire dwelling's crater (tbeldw_3 / tbeldw_3_2).
// Mesh: the crater's lava pixels as a camera-registered patch; UV0 = the patch's texture space. _MainTex holds the
// HoMM3 sprite's own painted lava (so the palette stays the art's), _Mask its lava coverage. Two layers of the
// vanilla lava_test_03 texture scroll against each other under a slow crust noise; the heat modulates the painted
// colour and adds an HDR glow in the hot cracks. Alpha-blended over the painted crater (the skirt beneath).
// Drawn by a bone-less SkinnedMeshRenderer (kept by the town runtime). Proof tier: generated artifact.
Shader "Homm3Conflux/Lava" {
    Properties {
        _MainTex ("Painted lava (sprite)", 2D) = "white" {}
        _Mask ("Lava coverage", 2D) = "white" {}
        _Lava ("Lava texture", 2D) = "gray" {}
        _Noise ("Crust noise", 2D) = "gray" {}
        _Tiling ("Lava tiling", Float) = 2.2
        _Speed ("Flow speed", Float) = 0.025
        _HotColor ("Hot glow (HDR)", Color) = (2.6, 1.1, 0.25, 1)
        _Glow ("Glow strength", Float) = 0.8
        _TimeOffset ("Time offset (s, editor renders)", Float) = 0
        _TimeScale ("Time scale (0 = frozen, editor renders)", Float) = 1
    }
    SubShader {
        Tags { "Queue"="Transparent-100" "RenderType"="Transparent" "IgnoreProjector"="True" }
        Pass {
            Blend SrcAlpha OneMinusSrcAlpha
            ZWrite Off
            Cull Off
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"
            sampler2D _MainTex, _Mask, _Lava, _Noise;
            float _Tiling, _Speed, _Glow, _TimeOffset, _TimeScale;
            float4 _HotColor;
            struct VI { float4 pos : POSITION; float2 uv : TEXCOORD0; };
            struct VO { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; };
            VO vert(VI i) { VO o; o.pos = UnityObjectToClipPos(i.pos); o.uv = i.uv; return o; }
            float4 frag(VO i) : SV_Target {
                float t = _Time.y * _TimeScale + _TimeOffset;
                float2 uv = i.uv;
                float3 paint = tex2D(_MainTex, uv).rgb;
                float mask = tex2D(_Mask, uv).r;
                float3 l1 = tex2D(_Lava, uv * _Tiling + t * _Speed * float2(1.0, 0.6)).rgb;
                float3 l2 = tex2D(_Lava, uv * _Tiling * 0.73 + float2(0.31, 0.17) + t * _Speed * float2(-0.7, 1.1)).rgb;
                float crust = tex2D(_Noise, uv * 1.4 + t * _Speed * 0.3).r;
                float heat = saturate(dot(l1 * l2, float3(0.4, 0.45, 0.15)) * 2.6 - crust * 0.45);
                float pulse = 0.85 + 0.15 * sin(t * 1.3 + crust * 6.2832);
                float3 col = paint * lerp(0.45, 1.35, heat) * pulse + _HotColor.rgb * pow(heat, 3.0) * _Glow;
                return float4(col, mask);
            }
            ENDCG
        }
    }
}
