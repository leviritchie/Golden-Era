Shader "OldenEra/Homm2/ShadeObjectClass"
{
	Properties
	{
		_Color ("Class", Color) = (0, 0, 0, 0.353)
		_MainTex ("Clip", 2D) = "white" {}
		_Cutoff ("Cutoff", Range(0, 1)) = 0.5
		_UseCutoff ("Use cutoff", Float) = 0
	}

	SubShader
	{
		Tags { "RenderPipeline" = "UniversalPipeline" "Queue" = "Overlay" "RenderType" = "Opaque" "IgnoreProjector" = "True" }
		Pass
		{
			Name "ClassAlpha"
			ColorMask A
			ZWrite Off
			ZTest LEqual
			Cull Off
			Blend One Zero

			HLSLPROGRAM
			#pragma vertex vert
			#pragma fragment frag
			#pragma target 3.0
			#include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

			CBUFFER_START(UnityPerMaterial)
			float4 _Color;
			float4 _MainTex_ST;
			float _Cutoff;
			float _UseCutoff;
			CBUFFER_END

			TEXTURE2D(_MainTex);
			SAMPLER(sampler_MainTex);

			struct Attributes
			{
				float4 positionOS : POSITION;
				float2 uv : TEXCOORD0;
			};

			struct Varyings
			{
				float4 positionCS : SV_POSITION;
				float2 uv : TEXCOORD0;
			};

			Varyings vert(Attributes v)
			{
				Varyings o;
				o.positionCS = TransformObjectToHClip(v.positionOS.xyz);
				o.uv = v.uv * _MainTex_ST.xy + _MainTex_ST.zw;
				return o;
			}

			float4 frag(Varyings i) : SV_Target
			{
				if (_UseCutoff > 0.5)
					clip(SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, i.uv).a - _Cutoff);
				return _Color;
			}
			ENDHLSL
		}
	}

	Fallback Off
}
