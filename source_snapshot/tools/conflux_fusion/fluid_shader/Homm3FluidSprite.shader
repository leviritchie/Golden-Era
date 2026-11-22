// Elemental Fusion sprites (FluidFusionCore SpriteVerts / SpriteKind): steam, flame tongues, embers, sparks, air wisps,
// snow crystals, dust and psychic motes, all procedural (no textures). Each sprite arrives as four vertices at its
// centre; the quad is expanded here in view space (velocity-stretched for sparks / wisps), so the simulation worker
// never needs the camera.
//
// Per vertex: position = centre, normal = velocity, uv0 = (corner x, corner y, kind, age 0..1),
// uv1 = (size, seed, rotation, stretch), uv2 = linear rgba colour
// (TEXCOORD2 rather than COLOR: the plugin uploads it with Mesh.SetUVs, the interop path it already uses). Premultiplied output: rgb adds light, a occludes.
// Same pipeline notes as Homm3FluidElement.shader (untagged CG pass, Transparent queue).
Shader "OldenEra/Homm3/FluidSprite"
{
	Properties
	{
		_FluidTime ("Time (s, fed by the plugin)", Float) = 0
		_Intensity ("Intensity", Float) = 1
		_HexFade ("Fade (0 visible)", Range(0, 1)) = 0
	}

	SubShader
	{
		Tags { "Queue" = "Transparent+20" "RenderType" = "Transparent" "IgnoreProjector" = "True" }
		Blend One OneMinusSrcAlpha
		ZWrite Off
		ZTest LEqual
		Cull Off

		Pass
		{
			CGPROGRAM
			#pragma vertex vert
			#pragma fragment frag
			#pragma target 3.5
			#include "UnityCG.cginc"

			float _FluidTime, _Intensity, _HexFade;

			struct appdata { float4 vertex : POSITION; float3 normal : NORMAL; float4 uv0 : TEXCOORD0; float4 uv1 : TEXCOORD1; float4 color : TEXCOORD2; };
			struct v2f
			{
				float4 pos : SV_POSITION;
				float2 c : TEXCOORD0;
				float4 k : TEXCOORD1;   // kind, age, seed, unused
				float4 col : COLOR;
			};

			v2f vert(appdata v)
			{
				v2f o;
				float3 vc = UnityObjectToViewPos(v.vertex.xyz);
				float s = length(mul((float3x3)UNITY_MATRIX_MV, float3(1, 0, 0)));   // object scale (sim -> view)
				float size = v.uv1.x * s;
				float2 c = v.uv0.xy;
				float2 off;
				float2 vel = mul((float3x3)UNITY_MATRIX_MV, v.normal).xy;
				float vl = length(vel);
				if (v.uv1.w > 0 && vl > 1e-4)
				{
					float2 ax = vel / vl, pp = float2(-ax.y, ax.x);
					off = ax * c.y * size * (1.0 + v.uv1.w * min(vl, 2.0)) + pp * c.x * size * 0.45;
				}
				else
				{
					float cr = cos(v.uv1.z), sr = sin(v.uv1.z);
					off = float2(c.x * cr - c.y * sr, c.x * sr + c.y * cr) * size;
					if (abs(v.uv0.z - 1.0) < 0.5) off = float2(c.x * 0.7, c.y * 1.35) * size;   // flame tongues stay upright
				}
				vc.xy += off;
				o.pos = mul(UNITY_MATRIX_P, float4(vc, 1.0));
				o.c = c;
				o.k = float4(v.uv0.z, v.uv0.w, v.uv1.y, 0);
				o.col = v.color;
				return o;
			}

			float h11(float x) { return frac(sin(x * 127.1) * 43758.5453); }
			float n21(float2 p)
			{
				float2 i = floor(p), f = frac(p);
				f = f * f * (3.0 - 2.0 * f);
				float a = h11(i.x + i.y * 57.0), b = h11(i.x + 1.0 + i.y * 57.0), c = h11(i.x + (i.y + 1.0) * 57.0), d = h11(i.x + 1.0 + (i.y + 1.0) * 57.0);
				return lerp(lerp(a, b, f.x), lerp(c, d, f.x), f.y);
			}

			float4 frag(v2f i) : SV_Target
			{
				int kind = (int)round(i.k.x);
				float age = i.k.y, seed = i.k.z, t = _FluidTime;
				float2 c = i.c;
				float r = length(c);
				float a = 0, occl = 0, fade = sin(3.14159 * saturate(age));
				float3 rgb = i.col.rgb;
				if (kind == 0)        // steam: soft rolling puff
				{
					float nz = n21(c * 2.2 + seed * 31.0 + float2(0, -t * 0.6));
					a = smoothstep(1.0, 0.15, r) * (0.55 + 0.45 * nz);
					rgb *= 0.75 + 0.3 * nz;
					occl = 1.0;   // normal blend: overlapping puffs settle on the steam colour instead of adding to white
				}
				else if (kind == 1)   // flame tongue: tapering teardrop, white-yellow core to red edge
				{
					float y01 = c.y * 0.5 + 0.5;
					float wid = 0.6 * (1.0 - 0.75 * y01) + 0.05;
					float flick = n21(float2(c.x * 3.0, c.y * 2.0 - t * 6.0) + seed * 17.0);
					float d = length(float2(c.x / wid, (c.y + 0.25) / 1.1)) + (flick - 0.5) * 0.5;
					a = smoothstep(1.0, 0.35, d);
					float core = smoothstep(0.8, 0.1, d);
					rgb = lerp(rgb * float3(1.0, 0.45, 0.25), rgb * float3(1.3, 1.15, 0.85), core);
					fade = 1.0 - age * age;
				}
				else if (kind == 2)   // ember: flickering hot dot
				{
					a = exp(-r * r * 9.0) * (0.6 + 0.4 * sin(t * 23.0 + seed * 60.0));
					rgb *= 1.6;
				}
				else if (kind == 3)   // spark: thin bright streak (stretched along velocity in the vertex stage)
				{
					a = exp(-c.x * c.x * 14.0) * smoothstep(1.0, 0.0, abs(c.y));
					rgb *= 2.2;
					fade = 1.0 - age;
				}
				else if (kind == 4)   // air wisp: curved soft streak
				{
					float bend = c.y + 0.45 * c.x * c.x - 0.2;
					a = exp(-bend * bend * 16.0) * smoothstep(1.0, 0.3, abs(c.x)) * (0.6 + 0.4 * n21(c * 3.0 + seed * 9.0 + t));
					occl = 0.1;
				}
				else if (kind == 5)   // snow crystal: six-armed star with a glinting centre
				{
					float an = atan2(c.y, c.x);
					float arms = pow(abs(cos(3.0 * an)), 12.0);
					a = saturate(exp(-r * r * 18.0) + arms * smoothstep(0.95, 0.2, r) * 0.8) * (0.7 + 0.3 * sin(t * 9.0 + seed * 40.0));
					occl = 0.25;
				}
				else if (kind == 6)   // dust / pebble: chunky dark grain
				{
					float an = atan2(c.y, c.x);
					float edge = 0.7 + 0.18 * (n21(float2(an * 2.0, seed * 50.0)) - 0.5);
					a = smoothstep(edge, edge - 0.15, r);
					occl = 0.9;
					rgb *= 0.55 + 0.45 * (c.y * 0.5 + 0.5);
				}
				else                  // mote: twinkling four-point star
				{
					float tw = 0.55 + 0.45 * sin(t * 7.0 + seed * 50.0);
					a = (exp(-r * r * 14.0) + 0.7 * exp(-abs(c.x) * 18.0) * exp(-c.y * c.y * 3.0) + 0.7 * exp(-abs(c.y) * 18.0) * exp(-c.x * c.x * 3.0)) * tw;
					rgb *= 1.5;
				}
				a = saturate(a * fade * i.col.a);
				float k = _Intensity * (1.0 - _HexFade);
				return float4(rgb * a * k, a * occl * k);
			}
			ENDCG
		}
	}
}
