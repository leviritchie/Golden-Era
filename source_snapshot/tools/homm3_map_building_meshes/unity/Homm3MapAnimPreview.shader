// Preview-only shader for Homm3MapBuildingAnimPreview.cs: albedo x (ambient + lambert) for the building body,
// plain alpha-clipped texture for the flipbook/billboard quads (_Lit = 0). Not the in-game Hex/Lit.
Shader "Hidden/Homm3MapAnimPreview/Simple"
{
    Properties
    {
        _MainTex ("Albedo", 2D) = "white" {}
        _Cutoff ("Cutoff", Float) = 0.5
        _Lit ("Lit", Float) = 1
        _SunDir ("Sun travel direction", Vector) = (0.3, -0.8, -0.5, 0)
        _Ambient ("Ambient", Float) = 0.45
    }
    SubShader
    {
        Tags { "RenderType"="TransparentCutout" "Queue"="AlphaTest" }
        Cull Off
        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"
            sampler2D _MainTex;
            float4 _MainTex_ST;
            float _Cutoff, _Lit, _Ambient;
            float4 _SunDir;
            struct a2v { float4 vertex : POSITION; float3 normal : NORMAL; float2 uv : TEXCOORD0; };
            struct v2f { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; float3 n : TEXCOORD1; };
            v2f vert (a2v v)
            {
                v2f o;
                o.pos = UnityObjectToClipPos(v.vertex);
                o.uv = TRANSFORM_TEX(v.uv, _MainTex);
                o.n = UnityObjectToWorldNormal(v.normal);
                return o;
            }
            fixed4 frag (v2f i, fixed facing : VFACE) : SV_Target
            {
                fixed4 c = tex2D(_MainTex, i.uv);
                clip(c.a - _Cutoff);
                if (_Lit > 0.5)
                {
                    float3 n = normalize(i.n) * (facing > 0 ? 1 : -1);
                    float d = saturate(dot(n, -normalize(_SunDir.xyz)));
                    c.rgb *= _Ambient + (1 - _Ambient) * d;
                }
                return fixed4(c.rgb, 1);
            }
            ENDCG
        }
    }
}
