// Additive dynamic metal shine for owned-skinned HoMM3 units (docs/homm3_metal_shine.md).
//
// The plugin appends this as an EXTRA material on the unit's body SkinnedMeshRenderer, next to the unchanged
// Hex/Lit clone, so it redraws the same skinned triangles and adds light on top:
//
//   rgb += mask * tint * (_ShineIntensity * sunColor * blinnPhong(N, L, V, _ShineGloss) * ndlSoft
//                       + _SheenStrength * lerp(ground, sky, reflectedViewElevation) * fresnel) * (1 - _HexFade)
//
// The mask (A) and the metal tint (RGB) come from one RGBA texture in the body's base-colour UV space (Meshy
// metallicRoughness B channel, tools/homm3_metal_shine/build_masks.py). _MainTex_ST rides the renderer's property
// block (the Animator / atlas snap write it there), so the mask stays in UV sync with the body.
//
// Pipeline: the game runs the custom "Hex" SRP. This is an untagged CGPROGRAM pass in the Transparent queue, the
// same dialect and queue as OldenEra/Homm3/BillboardArray, which renders in battle. No lighting, shadow or fog
// globals of the Hex pipeline are read: the plugin feeds the sun direction and colour per material.
Shader "OldenEra/Homm3/MetalShine"
{
	Properties
	{
		_MainTex ("UV transform carrier (unused texture)", 2D) = "white" {}
		_ShineMask ("Metal tint (RGB) + mask (A), base-colour UVs", 2D) = "black" {}
		_ShineIntensity ("Sun highlight intensity", Range(0, 4)) = 0.35
		_ShineGloss ("Glossiness (Blinn-Phong exponent)", Range(2, 512)) = 48
		_SheenStrength ("Environment sheen strength", Range(0, 2)) = 0.12
		_TintAmount ("Metal tint amount (0 white, 1 albedo hue)", Range(0, 1)) = 0.6
		_ShineSunDir ("Sun travel direction (world)", Vector) = (0.624, -0.4035, 0.6692, 0)
		_ShineSunColor ("Sun colour (linear, x intensity)", Color) = (1, 0.957, 0.839, 1)
		_SheenSky ("Sheen sky colour (linear)", Color) = (0.85, 0.9, 1.0, 1)
		_SheenGround ("Sheen ground colour (linear)", Color) = (0.12, 0.1, 0.08, 1)
		_SheenHorizon ("Sheen horizon softness", Range(0.02, 1)) = 0.25
		_FresnelPower ("Sheen fresnel power", Range(0.5, 8)) = 3
		_HexFade ("Mirrored body fade (0 visible)", Range(0, 1)) = 0
	}

	SubShader
	{
		Tags { "Queue" = "Transparent" "RenderType" = "Transparent" "IgnoreProjector" = "True" }
		Blend One One
		ZWrite Off
		ZTest LEqual
		Cull Back
		Offset -1, -1

		Pass
		{
			CGPROGRAM
			#pragma vertex vert
			#pragma fragment frag
			#pragma target 3.5

			#include "UnityCG.cginc"

			sampler2D _ShineMask;
			float4 _MainTex_ST;
			float _ShineIntensity;
			float _ShineGloss;
			float _SheenStrength;
			float _TintAmount;
			float4 _ShineSunDir;
			float4 _ShineSunColor;
			float4 _SheenSky;
			float4 _SheenGround;
			float _SheenHorizon;
			float _FresnelPower;
			float _HexFade;

			struct appdata
			{
				float4 vertex : POSITION;
				float3 normal : NORMAL;
				float2 uv : TEXCOORD0;
			};

			struct v2f
			{
				float4 pos : SV_POSITION;
				float2 uv : TEXCOORD0;
				float3 nWS : TEXCOORD1;
				float3 pWS : TEXCOORD2;
			};

			v2f vert(appdata v)
			{
				v2f o;
				o.pos = UnityObjectToClipPos(v.vertex);
				o.uv = TRANSFORM_TEX(v.uv, _MainTex);
				o.nWS = UnityObjectToWorldNormal(v.normal);
				o.pWS = mul(unity_ObjectToWorld, v.vertex).xyz;
				return o;
			}

			float4 frag(v2f i) : SV_Target
			{
				float4 m = tex2D(_ShineMask, i.uv);
				float fade = saturate(1.0 - _HexFade);
				float w = m.a * fade;
				if (w <= 0.002)
					return float4(0, 0, 0, 0);

				float3 n = normalize(i.nWS);
				// Perspective: toward the eye. Orthographic: the camera's backward axis (view-matrix row 2; Unity
				// view space looks down -z).
				float3 vPersp = _WorldSpaceCameraPos.xyz - i.pWS;
				float3 vOrtho = UNITY_MATRIX_V[2].xyz;
				float3 v = normalize(unity_OrthoParams.w > 0.5 ? vOrtho : vPersp);
				float3 l = -normalize(_ShineSunDir.xyz + float3(0, 1e-5, 0));
				float3 h = normalize(l + v);

				float ndl = dot(n, l);
				float ndlSoft = smoothstep(0.0, 0.2, ndl);
				float spec = pow(saturate(dot(n, h)), _ShineGloss) * ndlSoft;

				float3 r = reflect(-v, n);
				float sky = smoothstep(-_SheenHorizon, _SheenHorizon, r.y);
				float3 env = lerp(_SheenGround.rgb, _SheenSky.rgb, sky);
				float fres = 0.25 + 0.75 * pow(1.0 - saturate(dot(n, v)), _FresnelPower);

				float3 tint = lerp(float3(1, 1, 1), m.rgb, _TintAmount);
				float3 c = tint * (_ShineIntensity * spec * _ShineSunColor.rgb + _SheenStrength * env * fres);
				return float4(c * w, 0);
			}
			ENDCG
		}
	}
	Fallback Off
}
