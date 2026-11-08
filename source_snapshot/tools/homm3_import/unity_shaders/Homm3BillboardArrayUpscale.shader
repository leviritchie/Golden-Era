Shader "OldenEra/Homm3/BillboardArrayUpscale"
{
	Properties
	{
		_MainTexArray ("Frame array 0", 2DArray) = "" {}
		_MainTexArray1 ("Frame array 1", 2DArray) = "" {}
		_MainTexArray2 ("Frame array 2", 2DArray) = "" {}
		_MainTexArray3 ("Frame array 3", 2DArray) = "" {}
		_FrameIndex ("Frame index", Float) = 0
		_FrameIndexOffset ("Frame index offset", Float) = 0
		_ArraySliceSize ("Slices per array chunk", Float) = 2048
		_Homm3UpscaleStrength ("Upscale strength", Range(0, 1)) = 0.65
		_Homm3UpscaleSourceTexelSize ("Source texel size", Vector) = (0.001953125, 0.001953125, 512, 512)
	}

	SubShader
	{
		Tags { "Queue" = "Transparent" "RenderType" = "Transparent" }
		Blend SrcAlpha OneMinusSrcAlpha
		ZWrite Off
		Cull Off

		Pass
		{
			CGPROGRAM
			#pragma vertex vert
			#pragma fragment frag
			#pragma target 3.5
			#pragma require 2darray

			#include "UnityCG.cginc"

			UNITY_DECLARE_TEX2DARRAY(_MainTexArray);
			UNITY_DECLARE_TEX2DARRAY(_MainTexArray1);
			UNITY_DECLARE_TEX2DARRAY(_MainTexArray2);
			UNITY_DECLARE_TEX2DARRAY(_MainTexArray3);
			float _FrameIndex;
			float _FrameIndexOffset;
			float _ArraySliceSize;
			float _Homm3UpscaleStrength;
			float4 _Homm3UpscaleSourceTexelSize;

			struct appdata
			{
				float4 vertex : POSITION;
				float2 uv : TEXCOORD0;
			};

			struct v2f
			{
				float4 pos : SV_POSITION;
				float2 uv : TEXCOORD0;
			};

			v2f vert(appdata v)
			{
				v2f o;
				o.pos = UnityObjectToClipPos(v.vertex);
				o.uv = v.uv;
				return o;
			}

			fixed4 SampleSlice(float2 uv, float slice)
			{
				float chunk = max(_ArraySliceSize, 1.0);
				if (slice < chunk)
					return UNITY_SAMPLE_TEX2DARRAY(_MainTexArray, float3(uv, slice));
				slice -= chunk;
				if (slice < chunk)
					return UNITY_SAMPLE_TEX2DARRAY(_MainTexArray1, float3(uv, slice));
				slice -= chunk;
				if (slice < chunk)
					return UNITY_SAMPLE_TEX2DARRAY(_MainTexArray2, float3(uv, slice));
				slice -= chunk;
				return UNITY_SAMPLE_TEX2DARRAY(_MainTexArray3, float3(uv, slice));
			}

			float ColorDistance(fixed4 a, fixed4 b)
			{
				float3 d = a.rgb * a.a - b.rgb * b.a;
				return dot(d, d) + abs(a.a - b.a);
			}

			fixed4 SampleEdgeAware(float2 uv, float slice)
			{
				float2 sourceSize = max(_Homm3UpscaleSourceTexelSize.zw, float2(1.0, 1.0));
				float2 texel = 1.0 / sourceSize;
				float2 pixel = uv * sourceSize - 0.5;
				float2 basePixel = floor(pixel) + 0.5;
				float2 centerUv = basePixel / sourceSize;
				float2 f = saturate(pixel - floor(pixel));

				fixed4 c = SampleSlice(centerUv, slice);
				fixed4 l = SampleSlice(centerUv + float2(-texel.x, 0.0), slice);
				fixed4 r = SampleSlice(centerUv + float2( texel.x, 0.0), slice);
				fixed4 d = SampleSlice(centerUv + float2(0.0, -texel.y), slice);
				fixed4 u = SampleSlice(centerUv + float2(0.0,  texel.y), slice);

				fixed4 horizontal = lerp(l, r, f.x);
				fixed4 vertical = lerp(d, u, f.y);
				fixed4 smooth = lerp(horizontal, vertical, 0.5);

				float edgeH = ColorDistance(l, r);
				float edgeV = ColorDistance(d, u);
				float edge = saturate((edgeH + edgeV) * 8.0);
				float blend = saturate(_Homm3UpscaleStrength) * (1.0 - edge);
				return lerp(c, smooth, blend);
			}

			fixed4 frag(v2f i) : SV_Target
			{
				float slice = _FrameIndex + _FrameIndexOffset;
				fixed4 col = SampleEdgeAware(i.uv, slice);
				clip(col.a - 0.001);
				return col;
			}
			ENDCG
		}
	}
}
