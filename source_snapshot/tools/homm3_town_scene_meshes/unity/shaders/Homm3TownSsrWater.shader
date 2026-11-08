// Full-3D town (Cove / Fortress prototype): still water with screen-space reflections.
// A FlowWater superset (Homm3ConfluxFlowWater.shader): the same painted tint, ripple noise, vanilla WaterNormal, fixed
// specular and alpha-feathered shore, with FlowWater's constant _SkyColor reflection replaced by a reflection
// raymarched through the camera's depth and colour textures.
//   Mesh: UV0 = frame-space tint coordinate; UV1 = world XZ metres (still water: a slow drift, not a flow);
//   NORMAL = the painting's world up in the prefab frame (the water is level even where the monocular floor rises).
//   _MainTex: rgb = the water body with the painting's baked reflections painted out (town_full3d_ssr_water.py),
//   a = shore coordinate (sd px = a * _ShoreRange - _ShoreOut), as FlowWater.
// Inputs it reads that it does not own:
//   _CameraDepthTexture   the camera's depth texture. Under the built-in renderer it exists only when the camera's
//                         depthTextureMode includes Depth (the editor renders and Homm3TownScene3d.cs set it while an
//                         SSR material is present; catalog waterLook.ssr.requiresCameraDepthTexture). The game runs
//                         the Hex SRP, whose own Hex/Sea river binds the same name; whether that pipeline fills it in
//                         the town scene is runtime-unproven.
//   _CameraColorTexture   the opaque colour before transparents. No GrabPass (unsupported under an SRP); the Hex
//                         pipeline's Hex/Sea binds this name, and the editor renders blit it with a CommandBuffer at
//                         BeforeForwardAlpha.
// Reflection: view-space ray from the fragment about the (ripple-perturbed) level normal, geometric steps scaled by
// the fragment's eye depth, a thickness test, binary refinement. A hit on the water's own plane (the monocular floor
// under the water) is rejected. A miss (ray off screen, toward the camera, or past the last step) samples the screen
// where the reflected direction meets infinity if that pixel is sky, else _SkyColor. Confidence fades at the screen
// edges and with ray length, so a missing reflection falls back to FlowWater's look rather than to black.
// Drawn by a bone-less SkinnedMeshRenderer: the town runtime re-materials only MeshRenderers, so this shader stays.
// Proof tier: generated artifact + editor render (built-in renderer); unproven in game.
Shader "Homm3Town/SsrWater" {
    Properties {
        _MainTex ("Painted-out water (frame space), a = shore coordinate", 2D) = "white" {}
        _Noise ("Ripple noise A", 2D) = "gray" {}
        _Noise2 ("Ripple noise B", 2D) = "gray" {}
        _NormalMap ("Vanilla WaterNormal", 2D) = "bump" {}
        _Speed ("Drift speed (m/s)", Float) = 0.25
        _Scale ("Ripple frequency (1/m)", Float) = 0.22
        _Stretch ("Across/along stretch", Float) = 1.0
        _Ripple ("Ripple contrast", Float) = 0.2
        _NormalScale ("Normal map frequency (1/m)", Float) = 0.35
        _NormalStrength ("Normal strength (shading)", Float) = 0.45
        _Distort ("Normal strength (reflection direction)", Float) = 0.06
        _Glint ("Glint strength", Float) = 0.25
        _GlintColor ("Glint colour", Color) = (0.92, 0.97, 1.0, 1)
        _SpecDir ("Specular light dir (object space, toward the light)", Vector) = (0, 0.5, 1, 0)
        _SpecPower ("Specular power", Float) = 350
        _SpecStrength ("Specular strength", Float) = 0.8
        _SkyColor ("Reflected sky (miss colour)", Color) = (0.62, 0.72, 0.9, 1)
        _Reflect ("Reflection strength", Float) = 1.0
        _F0 ("Fresnel F0", Float) = 0.04
        _ReflectMin ("Reflection floor (added to fresnel)", Float) = 0.08
        _MissReflect ("Reflection weight where the ray finds nothing on screen", Float) = 0.35
        _SsrSteps ("Raymarch steps", Float) = 48
        _SsrStep ("First step (fraction of eye depth)", Float) = 0.012
        _SsrGrow ("Step growth", Float) = 1.08
        _SsrThick ("Hit thickness (fraction of eye depth)", Float) = 0.04
        _SsrEdge ("Screen edge fade (uv)", Float) = 0.06
        _SsrSelf ("Own-plane rejection (fraction of ray length)", Float) = 0.12
        _DeepTint ("Deep / shallow absorption ratio", Color) = (0.31, 0.36, 0.54, 1)
        _Deep ("Depth tint strength", Float) = 0.3
        _DeepPx ("Px from the bank to full depth", Float) = 22
        _ShoreRange ("Shore coordinate range (px)", Float) = 32
        _ShoreOut ("Shore coordinate offset (px outside the bank)", Float) = 6
        _Feather ("Bank feather (px)", Float) = 4
        _Foam ("Foam strength", Float) = 0.15
        _FoamPx ("Foam width (px)", Float) = 2.5
        _TimeOffset ("Time offset (s, editor renders)", Float) = 0
        _TimeScale ("Time scale (0 = frozen, editor renders)", Float) = 1
    }
    SubShader {
        Tags { "Queue"="Transparent-60" "RenderType"="Transparent" "IgnoreProjector"="True" }
        Pass {
            ZWrite Off
            ZTest LEqual
            Offset -1, -1
            Cull Off
            Blend SrcAlpha OneMinusSrcAlpha
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma target 3.5
            #include "UnityCG.cginc"
            sampler2D _MainTex, _Noise, _Noise2, _NormalMap;
            UNITY_DECLARE_DEPTH_TEXTURE(_CameraDepthTexture);
            sampler2D _CameraColorTexture;
            float _Speed, _Scale, _Stretch, _Ripple, _NormalScale, _NormalStrength, _Distort, _Glint, _SpecPower, _SpecStrength;
            float _Reflect, _F0, _ReflectMin, _MissReflect, _SsrSteps, _SsrStep, _SsrGrow, _SsrThick, _SsrEdge, _SsrSelf;
            float _Deep, _DeepPx, _ShoreRange, _ShoreOut, _Feather, _Foam, _FoamPx, _TimeOffset, _TimeScale;
            float4 _GlintColor, _SpecDir, _SkyColor, _DeepTint;
            struct VI { float4 pos : POSITION; float3 normal : NORMAL; float2 uv : TEXCOORD0; float2 flow : TEXCOORD1; };
            struct VO {
                float4 pos : SV_POSITION; float2 uv : TEXCOORD0; float2 flow : TEXCOORD1; float3 view : TEXCOORD2;
                float3 n : TEXCOORD3; float3 vpos : TEXCOORD4; float3 vn : TEXCOORD5;
            };
            VO vert(VI i) {
                VO o;
                o.pos = UnityObjectToClipPos(i.pos);
                o.uv = i.uv;
                o.flow = i.flow;
                o.view = ObjSpaceViewDir(i.pos);
                o.n = i.normal;
                o.vpos = UnityObjectToViewPos(i.pos.xyz);
                o.vn = normalize(mul((float3x3)UNITY_MATRIX_V, UnityObjectToWorldNormal(i.normal)));
                return o;
            }
            // View-space point -> screen uv of the depth / colour textures (ComputeScreenPos convention).
            float2 ScreenUv(float3 vp) {
                float4 c = mul(UNITY_MATRIX_P, float4(vp, 1));
                float2 ndc = c.xy / c.w;
                return float2(0.5 + 0.5 * ndc.x, 0.5 + 0.5 * ndc.y * _ProjectionParams.x);
            }
            float SceneEye(float2 uv) {
                return LinearEyeDepth(SAMPLE_DEPTH_TEXTURE_LOD(_CameraDepthTexture, float4(uv, 0, 0)));
            }
            bool IsSky(float2 uv) {
                float raw = SAMPLE_DEPTH_TEXTURE_LOD(_CameraDepthTexture, float4(uv, 0, 0));
            #if defined(UNITY_REVERSED_Z)
                return raw <= 1e-6;
            #else
                return raw >= 1 - 1e-6;
            #endif
            }
            float EdgeFade(float2 uv) {
                float2 e = min(uv, 1 - uv);
                return saturate(min(e.x, e.y) / max(_SsrEdge, 1e-4));
            }
            // rgb = reflected colour, a = confidence of the screen-space hit (0: the miss colour alone)
            float4 Trace(float3 p0, float3 r, float3 ng, out float3 miss) {
                float eye0 = -p0.z;
                miss = _SkyColor.rgb;
                // the reflected direction at infinity: the painted sky, where the screen shows sky there
                float3 far = p0 + r * (_ProjectionParams.z * 0.9);
                if (far.z < -_ProjectionParams.y) {
                    float2 fu = ScreenUv(far);
                    if (all(fu > 0) && all(fu < 1) && IsSky(fu))
                        miss = lerp(miss, tex2Dlod(_CameraColorTexture, float4(fu, 0, 0)).rgb, EdgeFade(fu));
                }
                if (r.z > 0.15) return float4(miss, 0);               // toward the camera: nothing on screen to hit
                float stepLen = max(eye0 * _SsrStep, 1e-3);
                float t = 0, tPrev = 0;
                int steps = (int)_SsrSteps;
                [loop] for (int k = 0; k < steps; k++) {
                    tPrev = t;
                    t += stepLen;
                    stepLen *= _SsrGrow;
                    float3 p = p0 + r * t;
                    if (-p.z < _ProjectionParams.y) break;
                    float2 uv = ScreenUv(p);
                    if (any(uv < 0) || any(uv > 1)) break;
                    float sceneEye = SceneEye(uv);
                    float rayEye = -p.z;
                    float thick = max(_SsrThick * eye0, stepLen * 1.5);
                    if (rayEye > sceneEye && rayEye - sceneEye < thick) {
                        // binary refinement between the last free and the first occluded sample
                        float a = tPrev, b = t;
                        [unroll] for (int j = 0; j < 6; j++) {
                            float m = 0.5 * (a + b);
                            float3 pm = p0 + r * m;
                            if (-pm.z > SceneEye(ScreenUv(pm))) b = m; else a = m;
                        }
                        float3 ph = p0 + r * b;
                        float2 huv = ScreenUv(ph);
                        // the scene point there, reconstructed from the depth texture along the hit pixel's ray
                        float3 ps = ph * (SceneEye(huv) / max(-ph.z, 1e-4));
                        // the water's own (monocular) floor plane is not a reflector
                        if (dot(ps - p0, ng) < _SsrSelf * b) continue;
                        float conf = EdgeFade(huv) * (1 - smoothstep(0.6, 1.0, (float)k / steps))
                                   * (1 - smoothstep(0.0, 0.15, r.z));
                        float3 hit = tex2Dlod(_CameraColorTexture, float4(huv, 0, 0)).rgb;
                        return float4(hit, conf);
                    }
                }
                return float4(miss, 0);
            }
            float4 frag(VO i) : SV_Target {
                float t = _Time.y * _TimeScale + _TimeOffset;
                float4 tintA = tex2D(_MainTex, i.uv);
                float3 tint = tintA.rgb;
                float sd = tintA.a * _ShoreRange - _ShoreOut;          // px inside the bank (negative: outside)
                float2 f = i.flow;
                float2 a = float2(f.x * _Scale * _Stretch, (f.y - t * _Speed) * _Scale);
                float2 b = float2(f.x * _Scale * _Stretch * 1.7 + 0.37, (f.y + t * _Speed * 0.8) * _Scale * 1.9 + 0.11);
                float n1 = tex2D(_Noise, a).r;
                float n2 = tex2D(_Noise2, b).r;
                float n = n1 * 0.6 + n2 * 0.4;
                float2 na = float2(f.x + t * _Speed * 0.6, f.y - t * _Speed) * _NormalScale;
                float2 nb = float2(f.x * 1.3 + 0.41 - t * _Speed * 0.5, f.y + t * _Speed * 0.7) * _NormalScale * 1.7;
                float3 t1 = UnpackNormal(tex2D(_NormalMap, na));
                float3 t2 = UnpackNormal(tex2D(_NormalMap, nb));
                float2 pert = (t1.xy + t2.xy) * 0.5;
                // shading normal (object space, as FlowWater)
                float3 N = normalize(i.n);
                float3 T = normalize(cross(N, float3(0, 0, 1)) + 1e-4);
                float3 B = cross(N, T);
                float3 Ns = normalize(N + (T * pert.x + B * pert.y) * _NormalStrength);
                float3 V = normalize(i.view);
                float3 L = normalize(_SpecDir.xyz);
                float3 H = normalize(L + V);
                float spec = pow(saturate(dot(Ns, H)), _SpecPower) * _SpecStrength;
                float fres = _F0 + (1 - _F0) * pow(1.0 - saturate(dot(Ns, V)), 5.0);
                // reflection normal (view space): the level normal, perturbed by the ripples much less than the shading
                float3 vn = normalize(i.vn);
                float3 vt = normalize(cross(vn, float3(0, 0, 1)) + 1e-4);
                float3 vb = cross(vn, vt);
                float3 Nr = normalize(vn + (vt * pert.x + vb * pert.y) * _Distort);
                float3 p0 = i.vpos;
                float3 r = reflect(normalize(p0), Nr);
                // the surface's own geometric normal (the monocular floor under the water), facing the camera
                float3 ng = normalize(cross(ddy(p0), ddx(p0)));
                if (dot(ng, -p0) < 0) ng = -ng;
                float3 miss;
                float4 tr = Trace(p0, r, ng, miss);
                float3 refl = lerp(miss, tr.rgb, tr.a);
                float3 col = tint;
                float depth = smoothstep(1.5, _DeepPx, sd);
                col *= lerp(float3(1, 1, 1), _DeepTint.rgb, depth * _Deep);
                col *= (1.0 - _Ripple * 0.5 + _Ripple * n);
                // a miss is an unknown, not a mirror of the sky colour: it reflects at _MissReflect of the hit weight
                col = lerp(col, refl, saturate((fres + _ReflectMin) * _Reflect * lerp(_MissReflect, 1.0, tr.a)));
                float glint = pow(saturate(n1 * n2 * 1.9), 4.0);
                col += _GlintColor.rgb * (glint * _Glint + spec);
                float foam = (1.0 - smoothstep(0.0, _FoamPx, abs(sd - 0.8))) * smoothstep(0.35, 0.65, n2);
                col = lerp(col, float3(0.9, 0.93, 0.95), saturate(foam * _Foam));
                float alpha = smoothstep(-_Feather, 0.8, sd);
                return float4(col, alpha);
            }
            ENDCG
        }
    }
}
