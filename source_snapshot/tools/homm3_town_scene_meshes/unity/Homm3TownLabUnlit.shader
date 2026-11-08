// Town-lab unlit texture with alpha cutout: the camera-projected HoMM3 backdrop and the 2D HoMM3
// sprite cards shown next to the 3D pilot buildings. Preview shader only.
Shader "Hidden/Homm3TownLab/Unlit" {
    Properties {
        _MainTex ("Color", 2D) = "white" {}
        _Cutoff ("Cutoff", Float) = 0.5
    }
    SubShader {
        Tags { "RenderType"="Opaque" }
        Cull Off
        Pass {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"
            float4 _MainTex_ST;
            float _Cutoff;
            Texture2D<float4> _MainTex;
            SamplerState sampler_MainTex;
            struct VI { float4 pos : POSITION; float2 uv : TEXCOORD0; };
            struct VO { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; };
            VO vert(VI i) { VO o; o.uv = i.uv * _MainTex_ST.xy + _MainTex_ST.zw; o.pos = UnityObjectToClipPos(i.pos.xyz); return o; }
            float4 frag(VO i) : SV_Target {
                float4 c = _MainTex.Sample(sampler_MainTex, i.uv);
                if (c.a < _Cutoff) discard;
                return float4(c.rgb, 1);
            }
            ENDCG
        }
    }
}
