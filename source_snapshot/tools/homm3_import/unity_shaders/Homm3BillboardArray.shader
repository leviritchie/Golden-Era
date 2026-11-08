Shader "OldenEra/Homm3/BillboardArray"
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

			fixed4 frag(v2f i) : SV_Target
			{
				float slice = _FrameIndex + _FrameIndexOffset;
				fixed4 col = SampleSlice(i.uv, slice);
				clip(col.a - 0.001);
				return col;
			}
			ENDCG
		}
	}
}
