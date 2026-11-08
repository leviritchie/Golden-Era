Shader "OldenEra/Homm3/BillboardArrayDepth"
{
	Properties
	{
		_MainTexArray ("Frame array 0", 2DArray) = "" {}
		_MainTexArray1 ("Frame array 1", 2DArray) = "" {}
		_MainTexArray2 ("Frame array 2", 2DArray) = "" {}
		_MainTexArray3 ("Frame array 3", 2DArray) = "" {}
		_DepthTexArray ("Depth array 0", 2DArray) = "" {}
		_DepthTexArray1 ("Depth array 1", 2DArray) = "" {}
		_DepthTexArray2 ("Depth array 2", 2DArray) = "" {}
		_DepthTexArray3 ("Depth array 3", 2DArray) = "" {}
		_FrameIndex ("Frame index", Float) = 0
		_FrameIndexOffset ("Frame index offset", Float) = 0
		_ArraySliceSize ("Slices per array chunk", Float) = 2048
		_DepthScale ("Depth scale (object-space Z for 0-1 span)", Float) = 4
		_DepthPivot ("Depth pivot (median near=bright)", Range(0, 1)) = 0.5
		_Tessellation ("Billboard tessellation", Range(1, 48)) = 24
	}

	SubShader
	{
		Tags { "Queue" = "AlphaTest" "RenderType" = "TransparentCutout" }
		Cull Off
		ZWrite On
		ZTest LEqual

		Pass
		{
			CGPROGRAM
			#pragma vertex tessvert
			#pragma hull hull
			#pragma domain domain
			#pragma fragment frag
			#pragma target 4.6
			#pragma require 2darray tessellation
			#include "UnityCG.cginc"
			#include "Tessellation.cginc"

			UNITY_DECLARE_TEX2DARRAY(_MainTexArray);
			UNITY_DECLARE_TEX2DARRAY(_MainTexArray1);
			UNITY_DECLARE_TEX2DARRAY(_MainTexArray2);
			UNITY_DECLARE_TEX2DARRAY(_MainTexArray3);
			UNITY_DECLARE_TEX2DARRAY(_DepthTexArray);
			UNITY_DECLARE_TEX2DARRAY(_DepthTexArray1);
			UNITY_DECLARE_TEX2DARRAY(_DepthTexArray2);
			UNITY_DECLARE_TEX2DARRAY(_DepthTexArray3);
			float _FrameIndex;
			float _FrameIndexOffset;
			float _ArraySliceSize;
			float _DepthScale;
			float _DepthPivot;
			float _Tessellation;

			struct appdata
			{
				float4 vertex : POSITION;
				float2 uv : TEXCOORD0;
			};

			struct tessvert_t
			{
				float4 vertex : INTERNALTESSPOS;
				float2 uv : TEXCOORD0;
			};

			struct v2f
			{
				float4 pos : SV_POSITION;
				float2 uv : TEXCOORD0;
			};

			float SliceIndex()
			{
				return _FrameIndex + _FrameIndexOffset;
			}

			fixed4 SampleColor(float2 uv, float slice)
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

			float SampleDepthRaw(float2 uv, float slice)
			{
				float chunk = max(_ArraySliceSize, 1.0);
				fixed4 sample;
				if (slice < chunk)
					sample = UNITY_SAMPLE_TEX2DARRAY_LOD(_DepthTexArray, float3(uv, slice), 0);
				else
				{
					slice -= chunk;
					if (slice < chunk)
						sample = UNITY_SAMPLE_TEX2DARRAY_LOD(_DepthTexArray1, float3(uv, slice), 0);
					else
					{
						slice -= chunk;
						if (slice < chunk)
							sample = UNITY_SAMPLE_TEX2DARRAY_LOD(_DepthTexArray2, float3(uv, slice), 0);
						else
						{
							slice -= chunk;
							sample = UNITY_SAMPLE_TEX2DARRAY_LOD(_DepthTexArray3, float3(uv, slice), 0);
						}
					}
				}
				return sample.r;
			}

			float SampleDepth(float2 uv, float slice)
			{
				// 5-tap box smooth: reduces tessellation pinholes on the front-facing grid.
				float2 texel = float2(1.0 / 256.0, 1.0 / 256.0);
				float d = SampleDepthRaw(uv, slice);
				float dL = SampleDepthRaw(uv + float2(-texel.x, 0.0), slice);
				float dR = SampleDepthRaw(uv + float2(texel.x, 0.0), slice);
				float dU = SampleDepthRaw(uv + float2(0.0, texel.y), slice);
				float dD = SampleDepthRaw(uv + float2(0.0, -texel.y), slice);
				return (d + dL + dR + dU + dD) * 0.2;
			}

			tessvert_t tessvert(appdata v)
			{
				tessvert_t o;
				o.vertex = v.vertex;
				o.uv = v.uv;
				return o;
			}

			UnityTessellationFactors hsconst(InputPatch<tessvert_t, 3> v)
			{
				UnityTessellationFactors o;
				float t = max(_Tessellation, 1.0);
				o.edge[0] = t;
				o.edge[1] = t;
				o.edge[2] = t;
				o.inside = t;
				return o;
			}

			[UNITY_domain("tri")]
			[UNITY_partitioning("fractional_odd")]
			[UNITY_outputtopology("triangle_cw")]
			[UNITY_patchconstantfunc("hsconst")]
			[UNITY_outputcontrolpoints(3)]
			tessvert_t hull(InputPatch<tessvert_t, 3> v, uint id : SV_OutputControlPointID)
			{
				return v[id];
			}

			[UNITY_domain("tri")]
			v2f domain(UnityTessellationFactors tess, const OutputPatch<tessvert_t, 3> vi, float3 bary : SV_DomainLocation)
			{
				float3 pos = vi[0].vertex.xyz * bary.x + vi[1].vertex.xyz * bary.y + vi[2].vertex.xyz * bary.z;
				float2 uv = vi[0].uv * bary.x + vi[1].uv * bary.y + vi[2].uv * bary.z;
				float depth = SampleDepth(uv, SliceIndex());
				pos.z += (depth - _DepthPivot) * _DepthScale;
				v2f o;
				o.pos = UnityObjectToClipPos(float4(pos, 1.0));
				o.uv = uv;
				return o;
			}

			fixed4 frag(v2f i) : SV_Target
			{
				fixed4 col = SampleColor(i.uv, SliceIndex());
				clip(col.a - 0.001);
				return col;
			}
			ENDCG
		}
	}
	FallBack Off
}
