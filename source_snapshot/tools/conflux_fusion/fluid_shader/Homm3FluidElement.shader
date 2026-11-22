// Elemental Fusion fluid surface (Homm3FluidFusionRuntime.cs). One parameter model for all 15 elements: the per-element
// row in fluid_fusion.json "elements[*].look" sets the material, so fire, ice, earth, air and psychic are configurations,
// not separate shaders.
//
// Surface detail is procedural in the body's own space (the surface is rebuilt from particles every frame, so it has no
// stable UVs): domain-warped fbm flowing along _Flow, a voronoi layer for cracks / facets / rock plates, bump from screen
// derivatives, temperature from the simulation (uv0.z) driving a heat ramp.
//
// Pipeline: the game runs the custom "Hex" SRP. Like OldenEra/Homm3/MetalShine this is an untagged CGPROGRAM pass in the
// Transparent queue (which renders in battle); it writes depth and draws opaque. No Hex lighting globals are read: the
// plugin feeds the sun (_SunDir / _SunColor), the ambient pair and _FluidTime per material.
Shader "OldenEra/Homm3/FluidElement"
{
	Properties
	{
		_Albedo ("Albedo", Color) = (0.5, 0.6, 0.8, 1)
		_Albedo2 ("Albedo (noise low)", Color) = (0.2, 0.3, 0.5, 1)
		_Emission ("Emission (base, linear HDR)", Color) = (0, 0, 0, 1)
		_HotColor ("Emission when hot / in cracks (linear HDR)", Color) = (2, 0.8, 0.2, 1)
		_TempGlow ("Heat -> hot emission gain", Float) = 0
		_TempFrom ("Heat where the glow starts", Float) = 0.3
		_NoiseScale ("Noise scale (1/m)", Float) = 4
		_Flow ("Flow (object space, m/s)", Vector) = (0, 0.3, 0, 0)
		_Warp ("Domain warp", Float) = 0.6
		_Detail ("Bump strength", Float) = 0.4
		_Cells ("Voronoi darkening", Range(0, 1)) = 0
		_CellScale ("Voronoi scale (1/m)", Float) = 6
		_CrackWidth ("Crack width", Float) = 0.08
		_CrackGlow ("Crack emission", Float) = 0
		_Facet ("Flat (faceted) normals", Range(0, 1)) = 0
		_Spec ("Specular", Float) = 0.3
		_Gloss ("Gloss exponent", Float) = 40
		_FresnelColor ("Rim / sky reflection colour", Color) = (0.6, 0.8, 1, 1)
		_FresnelPower ("Rim power", Float) = 3
		_Irid ("Iridescence", Range(0, 1)) = 0
		_Sparkle ("Glints / stars", Float) = 0
		_Bands ("Swirl bands", Range(0, 1)) = 0
		_BandSpin ("Swirl twist per m", Float) = 3
		_Pulse ("Emission pulse (rad/s)", Float) = 0
		_Translucency ("Wrap / subsurface", Range(0, 1)) = 0.3
		_FluidTime ("Time (s, fed by the plugin)", Float) = 0
		_SunDir ("Sun travel direction (world)", Vector) = (0.624, -0.4035, 0.6692, 0)
		_SunColor ("Sun colour (linear, x intensity)", Color) = (1.1, 1.05, 0.92, 1)
		_SkyColor ("Ambient sky", Color) = (0.42, 0.47, 0.55, 1)
		_GroundColor ("Ambient ground", Color) = (0.2, 0.17, 0.13, 1)
		_HexFade ("Fade (0 visible)", Range(0, 1)) = 0
	}

	SubShader
	{
		Tags { "Queue" = "Transparent-1" "RenderType" = "Opaque" "IgnoreProjector" = "True" }
		Blend Off
		ZWrite On
		ZTest LEqual
		Cull Back

		Pass
		{
			CGPROGRAM
			#pragma vertex vert
			#pragma fragment frag
			#pragma target 3.5
			#include "UnityCG.cginc"

			float4 _Albedo, _Albedo2, _Emission, _HotColor, _Flow, _FresnelColor, _SunDir, _SunColor, _SkyColor, _GroundColor;
			float _TempGlow, _TempFrom, _NoiseScale, _Warp, _Detail, _Cells, _CellScale, _CrackWidth, _CrackGlow, _Facet;
			float _Spec, _Gloss, _FresnelPower, _Irid, _Sparkle, _Bands, _BandSpin, _Pulse, _Translucency, _FluidTime, _HexFade;

			struct appdata { float4 vertex : POSITION; float3 normal : NORMAL; float4 uv : TEXCOORD0; };
			struct v2f
			{
				float4 pos : SV_POSITION;
				float3 opos : TEXCOORD0;
				float3 wpos : TEXCOORD1;
				float3 wn : TEXCOORD2;
				float temp : TEXCOORD3;
			};

			v2f vert(appdata v)
			{
				v2f o;
				o.pos = UnityObjectToClipPos(v.vertex);
				o.opos = v.vertex.xyz;
				o.wpos = mul(unity_ObjectToWorld, v.vertex).xyz;
				o.wn = UnityObjectToWorldNormal(v.normal);
				o.temp = v.uv.z;
				return o;
			}

			float hash13(float3 p)
			{
				p = frac(p * 0.1031);
				p += dot(p, p.zyx + 31.32);
				return frac((p.x + p.y) * p.z);
			}
			float3 hash33(float3 p)
			{
				p = frac(p * float3(0.1031, 0.1030, 0.0973));
				p += dot(p, p.yxz + 33.33);
				return frac((p.xxy + p.yxx) * p.zyx);
			}
			float vnoise(float3 p)
			{
				float3 i = floor(p), f = frac(p);
				float3 u = f * f * (3.0 - 2.0 * f);
				return lerp(lerp(lerp(hash13(i), hash13(i + float3(1, 0, 0)), u.x),
				                 lerp(hash13(i + float3(0, 1, 0)), hash13(i + float3(1, 1, 0)), u.x), u.y),
				            lerp(lerp(hash13(i + float3(0, 0, 1)), hash13(i + float3(1, 0, 1)), u.x),
				                 lerp(hash13(i + float3(0, 1, 1)), hash13(i + float3(1, 1, 1)), u.x), u.y), u.z);
			}
			float fbm(float3 p)
			{
				float a = 0.5, s = 0.0;
				for (int k = 0; k < 4; k++) { s += a * vnoise(p); p = p * 2.03 + 17.1; a *= 0.5; }
				return s / 0.9375;
			}
			// (F1, F2 - F1): distance to the nearest cell point and the edge distance
			float2 voronoi(float3 p)
			{
				float3 i = floor(p), f = frac(p);
				float d1 = 8.0, d2 = 8.0;
				for (int z = -1; z <= 1; z++)
				for (int y = -1; y <= 1; y++)
				for (int x = -1; x <= 1; x++)
				{
					float3 g = float3(x, y, z);
					float3 r = g + hash33(i + g) - f;
					float d = dot(r, r);
					if (d < d1) { d2 = d1; d1 = d; } else if (d < d2) d2 = d;
				}
				d1 = sqrt(d1); d2 = sqrt(d2);
				return float2(d1, d2 - d1);
			}
			float3 hue(float h) { return saturate(abs(frac(h + float3(0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0) - 1.0); }

			float4 frag(v2f i) : SV_Target
			{
				float t = _FluidTime;
				float3 p = i.opos;
				float3 q = p * _NoiseScale - _Flow.xyz * _NoiseScale * t;
				float3 w = float3(fbm(q + float3(1.7, 9.2, 3.1) + 0.15 * t), fbm(q + float3(8.3, 2.8, 5.4) - 0.12 * t), fbm(q + float3(4.1, 6.6, 0.7)));
				q += _Warp * (w - 0.5) * 2.0;
				float n = fbm(q);

				// swirl bands (air): stripes around the vertical axis, twisting with height
				float ang = atan2(p.z, p.x) + p.y * _BandSpin - t * 1.3;
				float bands = (sin(ang * 5.0 + n * 5.0) * 0.5 + 0.5);
				bands = smoothstep(0.45, 0.95, bands) * _Bands;

				float2 vor = voronoi(p * _CellScale + float3(0, -0.15, 0) * t * _CellScale * length(_Flow.xyz) + (w - 0.5) * 0.6);
				float edge = 1.0 - smoothstep(0.0, _CrackWidth, vor.y);

				float3 V = normalize(_WorldSpaceCameraPos - i.wpos);
				float3 N = normalize(i.wn);
				float3 dpdx = ddx(i.wpos), dpdy = ddy(i.wpos);
				float3 Nf = normalize(cross(dpdy, dpdx));
				if (dot(Nf, N) < 0) Nf = -Nf;
				N = normalize(lerp(N, Nf, _Facet));
				// bump from the height field's screen derivatives (no tangents on a per-frame mesh)
				float h = n - 0.6 * edge * (_Cells + _CrackGlow > 0 ? 1.0 : 0.0) + bands * 0.3;
				float3 r1 = cross(dpdy, N), r2 = cross(N, dpdx);
				float det = dot(dpdx, r1);
				float3 grad = sign(det) * (ddx(h) * r1 + ddy(h) * r2);
				N = normalize(abs(det) * N - _Detail * grad * 0.02);
				N = normalize(N + 1e-5);

				float3 L = -normalize(_SunDir.xyz);
				float ndl = dot(N, L);
				float diff = saturate((ndl + _Translucency) / (1.0 + _Translucency));
				float3 amb = lerp(_GroundColor.rgb, _SkyColor.rgb, N.y * 0.5 + 0.5);
				float3 H = normalize(L + V);
				float spec = pow(saturate(dot(N, H)), _Gloss) * _Spec;
				float nv = saturate(dot(N, V));
				float fres = pow(1.0 - nv, _FresnelPower);

				float3 albedo = lerp(_Albedo2.rgb, _Albedo.rgb, smoothstep(0.2, 0.8, n));
				albedo *= lerp(1.0, 0.3, edge * _Cells);
				albedo = lerp(albedo, _FresnelColor.rgb, bands * 0.6);
				float3 col = albedo * (_SunColor.rgb * diff + amb);
				col += spec * _SunColor.rgb * (1.0 - 0.7 * edge * _Cells);
				col += fres * _FresnelColor.rgb * (0.6 + 0.4 * n);

				// iridescence (psychic family): thin-film hue from view angle and the flowing noise
				float3 irid = hue(frac(nv * 1.6 + n * 0.8 + t * 0.04));
				col = lerp(col, col * 0.5 + irid * (0.35 + 0.65 * fres), _Irid * 0.7);

				// emission: base glow riding the noise, heat ramp from the simulation, glowing cracks
				float pulse = _Pulse > 0 ? 0.75 + 0.25 * sin(t * _Pulse + n * 6.283) : 1.0;
				float heat = saturate((i.temp - _TempFrom) * _TempGlow);
				float3 em = _Emission.rgb * (0.45 + 1.1 * n) * pulse;
				float core = smoothstep(0.35, 0.95, n + heat * 0.4);
				em += _HotColor.rgb * heat * lerp(0.35, 1.6, core);
				em += _HotColor.rgb * edge * _CrackGlow * (0.6 + 0.6 * vnoise(p * 3.0 + t * 0.7)) * pulse;
				em += _Emission.rgb * bands * 1.5;

				// glints (ice / frost) follow the sun; stars (astral) twinkle on their own
				float3 cell = floor(p * 70.0);
				float g = hash13(cell);
				float tw = 0.5 + 0.5 * sin(t * 3.0 + g * 40.0);
				float glint = step(0.975, g) * pow(saturate(dot(reflect(-V, N), L)), 6.0) * 4.0;
				float star = step(0.992, hash13(cell + 13.0)) * tw * tw * 3.0;
				em += _Sparkle * (glint * _SunColor.rgb + star * (_FresnelColor.rgb + 0.5));

				col += em;
				col *= (1.0 - _HexFade);
				return float4(col, 1.0);
			}
			ENDCG
		}
	}
}
