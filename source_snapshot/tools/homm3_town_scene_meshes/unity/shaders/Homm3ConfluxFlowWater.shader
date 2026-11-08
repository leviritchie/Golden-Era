// Conflux full-3D town: river / pond / waterfall surface that flows along each river's own path.
// Mesh: UV0 = frame-space position (the painted water tint), UV1 = flow coordinates in metres:
//   x = across the stream (camera-right metres), y = geodesic metres DOWNSTREAM from the river's source in the
//   mountains (build_conflux_full3d_scene.py / conflux_full3d_env.water_mesh). Ripples and normals are sampled at
//   y - t * speed, so every pattern moves toward larger y: down each river, round its bends, toward the camera.
// _MainTex alpha = shore coordinate: signed px from the (smoothed) bank, sd = a * _ShoreRange - _ShoreOut. The
// surface is alpha-feathered across the bank (no pixel stairs), darkens toward the channel's middle (depth tint) and
// carries a thin foam line at the bank.
// Lighting follows the vanilla Olden Era river (Hex/Sea, Mtl_River_Water): a scrolling WaterNormal map, a fixed
// specular direction (vanilla _SpecularAzimuth/_SpecularZenith, not the scene sun), a fresnel sky reflection at
// ~0.28 opacity, deep/shallow absorption colours.
// Drawn by a bone-less SkinnedMeshRenderer: the town runtime re-materials only MeshRenderers, so this shader stays.
// Proof tier: generated artifact + editor render; unproven in game.
Shader "Homm3Conflux/FlowWater" {
    Properties {
        _MainTex ("Painted tint (frame space), a = shore coordinate", 2D) = "white" {}
        _Noise ("Ripple noise A", 2D) = "gray" {}
        _Noise2 ("Ripple noise B", 2D) = "gray" {}
        _NormalMap ("Vanilla WaterNormal", 2D) = "bump" {}
        _Speed ("Flow speed (m/s)", Float) = 1.4
        _Scale ("Ripple frequency (1/m)", Float) = 0.22
        _Stretch ("Along-flow stretch", Float) = 2.6
        _Ripple ("Ripple contrast", Float) = 0.3
        _NormalScale ("Normal map frequency (1/m)", Float) = 0.35
        _NormalStrength ("Normal strength", Float) = 0.45
        _Glint ("Glint strength", Float) = 0.35
        _GlintColor ("Glint colour", Color) = (0.92, 0.97, 1.0, 1)
        _SpecDir ("Specular light dir (object space, toward the light)", Vector) = (0, 0.5, 1, 0)
        _SpecPower ("Specular power", Float) = 350
        _SpecStrength ("Specular strength", Float) = 1.1
        _SkyColor ("Reflected sky", Color) = (0.62, 0.72, 0.9, 1)
        _Reflect ("Reflection opacity", Float) = 0.28
        _DeepTint ("Deep / shallow absorption ratio", Color) = (0.31, 0.36, 0.54, 1)
        _Deep ("Depth tint strength", Float) = 0.45
        _DeepPx ("Px from the bank to full depth", Float) = 22
        _ShoreRange ("Shore coordinate range (px)", Float) = 32
        _ShoreOut ("Shore coordinate offset (px outside the bank)", Float) = 6
        _Feather ("Bank feather (px)", Float) = 4
        _Foam ("Foam strength", Float) = 0.35
        _FoamPx ("Foam width (px)", Float) = 3.5
        _TimeOffset ("Time offset (s, editor renders)", Float) = 0
        _TimeScale ("Time scale (0 = frozen, editor renders)", Float) = 1
    }
    SubShader {
        Tags { "Queue"="Transparent-50" "RenderType"="Transparent" "IgnoreProjector"="True" }
        Pass {
            ZWrite Off
            Cull Off
            Blend SrcAlpha OneMinusSrcAlpha
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"
            sampler2D _MainTex, _Noise, _Noise2, _NormalMap;
            float _Speed, _Scale, _Stretch, _Ripple, _NormalScale, _NormalStrength, _Glint, _SpecPower, _SpecStrength;
            float _Reflect, _Deep, _DeepPx, _ShoreRange, _ShoreOut, _Feather, _Foam, _FoamPx, _TimeOffset, _TimeScale;
            float4 _GlintColor, _SpecDir, _SkyColor, _DeepTint;
            struct VI { float4 pos : POSITION; float3 normal : NORMAL; float2 uv : TEXCOORD0; float2 flow : TEXCOORD1; };
            struct VO { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; float2 flow : TEXCOORD1; float3 view : TEXCOORD2; float3 n : TEXCOORD3; };
            VO vert(VI i) {
                VO o;
                o.pos = UnityObjectToClipPos(i.pos);
                o.uv = i.uv;
                o.flow = i.flow;
                o.view = ObjSpaceViewDir(i.pos);
                o.n = i.normal;
                return o;
            }
            float4 frag(VO i) : SV_Target {
                float t = _Time.y * _TimeScale + _TimeOffset;
                float4 tintA = tex2D(_MainTex, i.uv);
                float3 tint = tintA.rgb;
                float sd = tintA.a * _ShoreRange - _ShoreOut;          // px inside the bank (negative: outside)
                float2 f = i.flow;
                float2 a = float2(f.x * _Scale * _Stretch, (f.y - t * _Speed) * _Scale);
                float2 b = float2(f.x * _Scale * _Stretch * 1.7 + 0.37, (f.y - t * _Speed * 1.55) * _Scale * 1.9 + 0.11);
                float n1 = tex2D(_Noise, a).r;
                float n2 = tex2D(_Noise2, b).r;
                float n = n1 * 0.6 + n2 * 0.4;
                // Two scrolling layers of the vanilla water normal map, in the flow frame.
                float2 na = float2(f.x, f.y - t * _Speed) * _NormalScale;
                float2 nb = float2(f.x * 1.3 + 0.41, f.y - t * _Speed * 0.7) * _NormalScale * 1.7;
                float3 t1 = UnpackNormal(tex2D(_NormalMap, na));
                float3 t2 = UnpackNormal(tex2D(_NormalMap, nb));
                float2 pert = (t1.xy + t2.xy) * 0.5 * _NormalStrength;
                float3 N = normalize(i.n);
                float3 T = normalize(cross(N, float3(0, 0, 1)) + 1e-4);
                float3 B = cross(N, T);
                N = normalize(N + T * pert.x + B * pert.y);
                float3 V = normalize(i.view);
                float3 L = normalize(_SpecDir.xyz);
                float3 H = normalize(L + V);
                float spec = pow(saturate(dot(N, H)), _SpecPower) * _SpecStrength;
                float fres = 0.02 + 0.98 * pow(1.0 - saturate(dot(N, V)), 5.0);
                // Depth tint: the painted colour is the shallow water; the middle of the channel absorbs more.
                float depth = smoothstep(1.5, _DeepPx, sd);
                float3 col = tint * lerp(float3(1, 1, 1), _DeepTint.rgb, depth * _Deep);
                col *= (1.0 - _Ripple * 0.5 + _Ripple * n);
                col = lerp(col, _SkyColor.rgb, saturate(fres + 0.08) * _Reflect);
                float glint = pow(saturate(n1 * n2 * 1.9), 4.0);
                col += _GlintColor.rgb * (glint * _Glint + spec);
                // Shore: thin broken foam just inside the bank, alpha feathered across it.
                float foam = (1.0 - smoothstep(0.0, _FoamPx, abs(sd - 0.8))) * smoothstep(0.35, 0.65, n2);
                col = lerp(col, float3(0.9, 0.93, 0.95), saturate(foam * _Foam));
                float alpha = smoothstep(-_Feather, 0.8, sd);
                return float4(col, alpha);
            }
            ENDCG
        }
    }
}
