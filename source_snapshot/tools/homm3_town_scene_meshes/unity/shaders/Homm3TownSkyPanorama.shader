// Full-3D town (Inferno prototype): ONE continuous sky (docs/homm3_town_sky_continuous.md).
// A sphere around the rest camera (Sky_Pano) whose fragments look an equirectangular panorama up by view direction
// only: the direction is the fragment's object-space position minus the camera's object-space position, so the root's
// aspect scale, the prefab frame and every pan pose see the same sky at the same direction (zero parallax, no seams
// between pieces: there is one piece). The panorama's frame is the rest heading:
//   _SkyFwd / _SkyRight / _SkyUp  object-space (prefab frame) unit vectors of the rest heading, its right, world up
//   azimuth  atan2(dir.right, dir.fwd), u = frac((az - _Az0Deg - drift) / 360)  (u repeats: the wrap is one seam-free
//            column pair behind the rest camera; derivatives are taken on two u parameterisations and the smaller
//            used, so the mip level does not jump at the wrap)
//   elevation asin(dir.up), v = (el - _ElMinDeg) / (_ElMaxDeg - _ElMinDeg), clamped half a texel in from each edge
// Depth: written at the far plane (o.pos.z pinned to w * (1 - 1e-5), reversed-Z aware), ZWrite On / ZTest LEqual, so
// every mesh in the scene draws in front of it whatever order it is drawn in and whatever the sphere's radius;
// nothing behind it exists. No fog, no lighting, no GrabPass, no camera texture.
// _DriftDegPerSec: optional constant azimuth drift of the whole panorama (0 = static; the panorama's clouds are painted
// in it, so a drift moves the whole sky as one layer - never one piece against another).
// Proof tier: generated artifact + offline preview; editor render and the Hex SRP runtime unproven until rendered.
Shader "Homm3Town/SkyPanorama" {
    Properties {
        _MainTex ("Equirect panorama (u = azimuth, v = elevation)", 2D) = "black" {}
        _SkyFwd ("Rest heading (object space)", Vector) = (0, 0, 1, 0)
        _SkyRight ("Rest right (object space)", Vector) = (1, 0, 0, 0)
        _SkyUp ("World up (object space)", Vector) = (0, 1, 0, 0)
        _Az0Deg ("Azimuth of column 0 (deg)", Float) = -180
        _ElMinDeg ("Elevation of the bottom row (deg)", Float) = -20
        _ElMaxDeg ("Elevation of the top row (deg)", Float) = 55
        _DriftDegPerSec ("Azimuth drift (deg/s, 0 = static)", Float) = 0
        _TimeOffset ("Time offset (s, editor renders)", Float) = 0
        _TimeScale ("Time scale (0 = frozen, editor renders)", Float) = 1
    }
    SubShader {
        Tags { "Queue"="Background" "RenderType"="Background" "IgnoreProjector"="True" "PreviewType"="Skybox" }
        Pass {
            ZWrite On
            ZTest LEqual
            Cull Off
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma target 3.0
            #include "UnityCG.cginc"
            sampler2D _MainTex;
            float4 _MainTex_TexelSize;
            float4 _SkyFwd, _SkyRight, _SkyUp;
            float _Az0Deg, _ElMinDeg, _ElMaxDeg, _DriftDegPerSec, _TimeOffset, _TimeScale;
            struct appdata { float4 vertex : POSITION; };
            struct v2f { float4 pos : SV_POSITION; float3 dir : TEXCOORD0; };
            v2f vert(appdata v) {
                v2f o;
                o.pos = UnityObjectToClipPos(v.vertex);
                #if defined(UNITY_REVERSED_Z)
                o.pos.z = o.pos.w * 1e-5;
                #else
                o.pos.z = o.pos.w * (1.0 - 1e-5);
                #endif
                float3 camObj = mul(unity_WorldToObject, float4(_WorldSpaceCameraPos, 1.0)).xyz;
                o.dir = v.vertex.xyz - camObj;
                return o;
            }
            fixed4 frag(v2f i) : SV_Target {
                float3 d = normalize(i.dir);
                float x = dot(d, _SkyRight.xyz), z = dot(d, _SkyFwd.xyz), y = dot(d, _SkyUp.xyz);
                float t = _Time.y * _TimeScale + _TimeOffset;
                float az = degrees(atan2(x, z)) - _DriftDegPerSec * t;
                float el = degrees(asin(clamp(y, -1.0, 1.0)));
                float u = frac((az - _Az0Deg) / 360.0);
                float u2 = frac(u + 0.5);                       // the same column, seamless where u wraps
                float hv = 0.5 * _MainTex_TexelSize.y;
                float v = clamp((el - _ElMinDeg) / (_ElMaxDeg - _ElMinDeg), hv, 1.0 - hv);
                float2 dx = float2(ddx(u), ddx(v)), dy = float2(ddy(u), ddy(v));
                float2 dx2 = float2(ddx(u2), dx.y), dy2 = float2(ddy(u2), dy.y);
                if (abs(dx2.x) + abs(dy2.x) < abs(dx.x) + abs(dy.x)) { dx = dx2; dy = dy2; }
                fixed4 c = tex2Dgrad(_MainTex, float2(u, v), dx, dy);
                c.a = 1.0;
                return c;
            }
            ENDCG
        }
    }
    Fallback Off
}
