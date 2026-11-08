import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const params = new URLSearchParams(location.search);
const unit = params.get("unit") || "h3_roc";
const clip = params.get("clip") || "idle_start_move_end";

const TOGGLES = [
  ["showSprite", "Sprite plate", true],
  ["showSilhouette", "Sprite silhouette outline", true],
  ["showMesh", "Mesh", true],
  ["unlit", "Unlit shading", true],
  ["textured", "Keep mesh texture", true],
  ["showSkeleton", "Skeleton", true],
  ["showJointMarkers", "Joint markers", true],
  ["showLabels", "Joint labels", false],
  ["anatomyColors", "Color mesh by anatomy group", false],
  ["occupancyCamera", "Lock occupancy camera", true],
  ["viewSide", "Side-check camera", false],
  ["viewFront", "Front-check camera", false],
  ["viewTop", "Top-check camera", false],
  ["onionSkin", "Onion-skin neighbor frames", false],
  ["leftoverApprox", "Browser leftover/extra overlay", true],
  ["mirrorBilateral", "Mirror paired joints with the same raise/sweep/twist", false],
  ["lockRoot", "Lock motion root", true],
  ["lockIdle", "Lock idle perch frames", true],
  ["isolateBone", "Isolate selected joint (fade other markers)", false],
  ["ghostBind", "Ghost bind pose", false],
  ["snapCoarse", "Snap sliders to 45°", false],
  ["grid", "Ground grid", false],
  ["playWrap", "Wrap playback (off for concatenated idle/move)", false],
  ["highContrast", "High-contrast sprite", false],
  ["hideHelperNodes", "Hide unlabeled helper nodes", true],
];

const state = {
  session: null,
  frame: 0,
  joint: "",
  hoverJoint: "",
  playing: false,
  dirty: false,
  idlePoses: {},
  flyPoses: {},
  rest: {},
  helpers: [],
  markers: new Map(),
  drag: null,
  pending: null,
  silhouetteKey: "",
  viewZoom: 1,
  viewPanX: 0,
  viewPanY: 0,
  meshPreview: false,
  meshPreviewHeld: false,
  toggles: Object.fromEntries(TOGGLES.map(([id, , on]) => [id, on])),
};

const el = (id) => document.getElementById(id);
const status = (text) => {
  el("status").textContent = text;
};

function clonePose(pose) {
  return JSON.parse(JSON.stringify(pose || {}));
}

function ensureBone(pose, name) {
  if (!pose[name]) pose[name] = { x: 0, y: 0, z: 0 };
  return pose[name];
}

function poseStore(frame) {
  const source = (state.session.frameRestSources[frame] || "perch");
  return source === "perch" ? state.idlePoses : state.flyPoses;
}

function currentPose() {
  const store = poseStore(state.frame);
  if (!store[state.frame]) store[state.frame] = {};
  return store[state.frame];
}

function axisAngleQuat(xDeg, yDeg, zDeg) {
  const x = THREE.MathUtils.degToRad(xDeg);
  const y = THREE.MathUtils.degToRad(yDeg);
  const z = THREE.MathUtils.degToRad(zDeg);
  const vec = new THREE.Vector3(x, y, z);
  const angle = vec.length();
  if (angle <= 1e-12) return new THREE.Quaternion();
  vec.multiplyScalar(1 / angle);
  return new THREE.Quaternion().setFromAxisAngle(vec, angle);
}

function quatToAxisAngleDeg(quat) {
  const q = quat.clone().normalize();
  if (q.w < 0) q.set(-q.x, -q.y, -q.z, -q.w);
  const angle = 2 * Math.acos(THREE.MathUtils.clamp(q.w, -1, 1));
  const s = Math.sqrt(Math.max(0, 1 - q.w * q.w));
  if (angle <= 1e-12 || s <= 1e-8) return { x: 0, y: 0, z: 0 };
  const scale = THREE.MathUtils.radToDeg(angle) / s;
  return { x: q.x * scale, y: q.y * scale, z: q.z * scale };
}

function restEntry() {
  return state.rest[restNameForFrame(state.frame)];
}

function modelFrameOrNull() {
  const entry = restEntry();
  const landmarks = state.session?.anatomy?.landmarks || {};
  const ventralRaw = state.session?.anatomy?.bindAxes?.ventral;
  if (!entry?.restWorldPos || !ventralRaw) {
    status("Model midline needs bindAxes.ventral and rest-world joint positions.");
    return null;
  }
  const tail = entry.restWorldPos.get(landmarks.tailTip);
  const head = entry.restWorldPos.get(landmarks.headTip);
  if (!tail || !head) {
    status("Rest mesh is missing tailTip or headTip.");
    return null;
  }
  const ventral = new THREE.Vector3(...ventralRaw);
  if (ventral.length() <= 1e-12) {
    status("bindAxes.ventral is zero.");
    return null;
  }
  ventral.normalize();
  const spine = head.clone().sub(tail);
  if (spine.length() <= 1e-12) {
    status("Model spine (headTip - tailTip) is zero.");
    return null;
  }
  spine.normalize();
  const lateral = new THREE.Vector3().crossVectors(spine, ventral);
  if (lateral.length() <= 1e-12) {
    status("Model lateral (spine × ventral) is zero.");
    return null;
  }
  lateral.normalize();
  const ventralOrtho = new THREE.Vector3().crossVectors(lateral, spine);
  if (ventralOrtho.length() <= 1e-12) {
    status("Model ventral is zero after orthonormalize.");
    return null;
  }
  ventralOrtho.normalize();
  return { lateral, spine, ventral: ventralOrtho };
}

function distalDirection(name) {
  const entry = restEntry();
  const groups = state.session?.anatomy?.groups || {};
  for (const group of Object.values(groups)) {
    const bones = group.bonesDependencyOrder || [];
    const index = bones.indexOf(name);
    if (index < 0) continue;
    const here = entry?.restWorldPos?.get(name);
    if (!here) return null;
    if (index + 1 < bones.length) {
      const child = entry.restWorldPos.get(bones[index + 1]);
      if (!child) return null;
      return child.clone().sub(here);
    }
    if (index > 0) {
      const parent = entry.restWorldPos.get(bones[index - 1]);
      if (!parent) return null;
      return here.clone().sub(parent);
    }
  }
  return null;
}

function anatomicalAxes(boneDir, model) {
  const bone = boneDir.clone().normalize();
  const dorsal = model.ventral.clone().multiplyScalar(-1);
  let raise = new THREE.Vector3().crossVectors(bone, dorsal);
  if (raise.length() <= 1e-8) raise = new THREE.Vector3().crossVectors(bone, model.spine);
  if (raise.length() <= 1e-12) return null;
  raise.normalize();
  const raiseMove = new THREE.Vector3().crossVectors(raise, bone);
  if (raiseMove.dot(dorsal) < 0) raise.multiplyScalar(-1);
  const twist = bone.clone();
  const sweep = new THREE.Vector3().crossVectors(raise, twist);
  if (sweep.length() <= 1e-12) return null;
  sweep.normalize();
  const sweepMove = new THREE.Vector3().crossVectors(sweep, bone);
  if (sweepMove.dot(model.spine) < 0) sweep.multiplyScalar(-1);
  return { raise, sweep, twist };
}

function worldAxisAngleFromLocal(delta, restWorld) {
  return new THREE.Vector3(delta.x || 0, delta.y || 0, delta.z || 0).applyQuaternion(restWorld);
}

function localFromWorldAxisAngle(world, restWorld) {
  const local = world.clone().applyQuaternion(restWorld.clone().invert());
  return { x: local.x, y: local.y, z: local.z };
}

function anatomicalCombo(delta, restWorld, axes) {
  const world = worldAxisAngleFromLocal(delta, restWorld);
  return {
    raise: world.dot(axes.raise),
    sweep: world.dot(axes.sweep),
    twist: world.dot(axes.twist),
  };
}

function deltaFromAnatomical(combo, restWorld, axes) {
  const world = axes.raise.clone().multiplyScalar(combo.raise)
    .add(axes.sweep.clone().multiplyScalar(combo.sweep))
    .add(axes.twist.clone().multiplyScalar(combo.twist));
  return localFromWorldAxisAngle(world, restWorld);
}

function copyAnatomicalDelta(nameA, nameB, deltaA) {
  const entry = restEntry();
  const model = modelFrameOrNull();
  if (!entry?.restWorldQuat || !model) return null;
  const restA = entry.restWorldQuat.get(nameA);
  const restB = entry.restWorldQuat.get(nameB);
  const dirA = distalDirection(nameA);
  const dirB = distalDirection(nameB);
  if (!restA || !restB) {
    status(`Rest-world axes missing for ${nameA}/${nameB}.`);
    return null;
  }
  if (!dirA || !dirB || dirA.length() <= 1e-12 || dirB.length() <= 1e-12) {
    status(`Distal direction missing for ${nameA}/${nameB}.`);
    return null;
  }
  const axesA = anatomicalAxes(dirA, model);
  const axesB = anatomicalAxes(dirB, model);
  if (!axesA || !axesB) {
    status(`Anatomical axes failed for ${nameA}/${nameB}.`);
    return null;
  }
  return deltaFromAnatomical(anatomicalCombo(deltaA, restA, axesA), restB, axesB);
}

function averageAnatomicalPair(nameA, nameB, deltaA, deltaB) {
  const entry = restEntry();
  const model = modelFrameOrNull();
  if (!entry?.restWorldQuat || !model) return null;
  const restA = entry.restWorldQuat.get(nameA);
  const restB = entry.restWorldQuat.get(nameB);
  const dirA = distalDirection(nameA);
  const dirB = distalDirection(nameB);
  if (!restA || !restB || !dirA || !dirB) {
    status(`Anatomical average missing rest or distal for ${nameA}/${nameB}.`);
    return null;
  }
  const axesA = anatomicalAxes(dirA, model);
  const axesB = anatomicalAxes(dirB, model);
  if (!axesA || !axesB) return null;
  const comboA = anatomicalCombo(deltaA, restA, axesA);
  const comboB = anatomicalCombo(deltaB, restB, axesB);
  const avg = {
    raise: (comboA.raise + comboB.raise) / 2,
    sweep: (comboA.sweep + comboB.sweep) / 2,
    twist: (comboA.twist + comboB.twist) / 2,
  };
  return {
    a: deltaFromAnatomical(avg, restA, axesA),
    b: deltaFromAnatomical(avg, restB, axesB),
  };
}

function cameraBasis() {
  const cam = state.session.camera;
  return {
    right: new THREE.Vector3(...cam.right),
    down: new THREE.Vector3(...cam.down),
    up: new THREE.Vector3(...cam.up),
    forward: new THREE.Vector3(...cam.forward),
  };
}

const renderer = new THREE.WebGLRenderer({
  canvas: el("view"),
  alpha: true,
  antialias: false,
  preserveDrawingBuffer: true,
});
renderer.setClearColor(0x000000, 0);
renderer.setPixelRatio(1);
const scene = new THREE.Scene();
const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.01, 100);
const orbit = new OrbitControls(camera, el("view"));
orbit.enabled = false;
orbit.enablePan = false;
const light = new THREE.AmbientLight(0xffffff, 1);
scene.add(light);
const dir = new THREE.DirectionalLight(0xffffff, 0.8);
dir.position.set(2, 4, 3);
scene.add(dir);
const grid = new THREE.GridHelper(4, 8, 0x444033, 0x2a261e);
grid.visible = false;
scene.add(grid);
const markerGroup = new THREE.Group();
scene.add(markerGroup);
const loader = new GLTFLoader();
const overlay = el("overlay");
const overlayCtx = overlay.getContext("2d");
const scratch = document.createElement("canvas");
const scratchCtx = scratch.getContext("2d", { willReadFrequently: true });
const silhouette = document.createElement("canvas");
const silhouetteCtx = silhouette.getContext("2d");
const raycaster = new THREE.Raycaster();
const pointerNdc = new THREE.Vector2();
const _parentQ = new THREE.Quaternion();

function resize() {
  const box = el("viewport").getBoundingClientRect();
  const res = state.session?.camera.sourceResolution || [288, 258];
  const aspect = res[0] / res[1];
  let width = box.width;
  let height = box.width / aspect;
  if (height > box.height) {
    height = box.height;
    width = height * aspect;
  }
  renderer.setSize(width, height, false);
  overlay.width = res[0];
  overlay.height = res[1];
  overlay.style.width = `${width}px`;
  overlay.style.height = `${height}px`;
  ["sprite", "spritePrev", "spriteNext", "view"].forEach((id) => {
    const node = el(id);
    if (!node) return;
    node.style.width = `${width}px`;
    node.style.height = `${height}px`;
  });
}

function occupancyCamera() {
  const cam = state.session.camera;
  const basis = cameraBasis();
  const width = cam.sourceResolution[0];
  const height = cam.sourceResolution[1];
  const px = cam.pxPerWorld[0];
  const ox = cam.offsetPx[0];
  const oy = cam.offsetPx[1];
  camera.left = -ox / px;
  camera.right = (width - ox) / px;
  camera.top = oy / px;
  camera.bottom = (oy - height) / px;
  camera.up.copy(basis.up);
  const origin = new THREE.Vector3();
  camera.position.copy(origin).addScaledVector(basis.forward, -8);
  camera.lookAt(origin);
  camera.updateProjectionMatrix();
  orbit.target.copy(origin);
  orbit.enabled = !state.toggles.occupancyCamera && !state.drag && !state.pending;
}

function cameraScreenAxes() {
  camera.updateMatrixWorld();
  return {
    right: new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0).normalize(),
    up: new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 1).normalize(),
  };
}

function applyZoomPan() {
  camera.zoom = state.viewZoom;
  camera.updateProjectionMatrix();
  const axes = cameraScreenAxes();
  camera.position.addScaledVector(axes.right, state.viewPanX);
  camera.position.addScaledVector(axes.up, state.viewPanY);
  orbit.target.addScaledVector(axes.right, state.viewPanX);
  orbit.target.addScaledVector(axes.up, state.viewPanY);
}

function resetView() {
  state.viewZoom = 1;
  state.viewPanX = 0;
  state.viewPanY = 0;
  draw();
}

function zoomAtEvent(event, factor) {
  if (!state.session) return;
  applyViewCamera();
  const ndc = eventNdc(event).clone();
  const onPlate = Math.abs(ndc.x) <= 1 && Math.abs(ndc.y) <= 1;
  const before = onPlate ? new THREE.Vector3(ndc.x, ndc.y, 0).unproject(camera) : null;
  state.viewZoom = THREE.MathUtils.clamp(state.viewZoom * factor, 0.35, 14);
  applyViewCamera();
  if (before) {
    const after = new THREE.Vector3(ndc.x, ndc.y, 0).unproject(camera);
    const delta = before.sub(after);
    const axes = cameraScreenAxes();
    state.viewPanX += delta.dot(axes.right);
    state.viewPanY += delta.dot(axes.up);
  }
  draw({ overlay: false });
}

function meshPreviewOn() {
  return state.meshPreview || state.meshPreviewHeld;
}

function syncMeshPreviewClass() {
  const on = meshPreviewOn();
  document.body.classList.toggle("mesh-preview", on);
  const btn = el("meshPreviewBtn");
  if (btn) {
    btn.setAttribute("aria-pressed", on ? "true" : "false");
  }
}

function setMeshPreview(on) {
  state.meshPreview = on;
  syncMeshPreviewClass();
  draw();
}

function applyViewCamera() {
  if (state.toggles.viewTop) {
    camera.up.set(0, 0, 1);
    camera.position.set(0, 8, 0);
    camera.lookAt(0, 0, 0);
    orbit.target.set(0, 0, 0);
    orbit.enabled = !state.drag && !state.pending;
    applyZoomPan();
    return;
  }
  if (state.toggles.viewFront) {
    camera.up.set(0, 1, 0);
    camera.position.set(0, 0, 8);
    camera.lookAt(0, 0, 0);
    orbit.target.set(0, 0, 0);
    orbit.enabled = !state.drag && !state.pending;
    applyZoomPan();
    return;
  }
  if (state.toggles.viewSide) {
    camera.up.set(0, 1, 0);
    camera.position.set(8, 0, 0);
    camera.lookAt(0, 0, 0);
    orbit.target.set(0, 0, 0);
    orbit.enabled = !state.drag && !state.pending;
    applyZoomPan();
    return;
  }
  occupancyCamera();
  applyZoomPan();
}

function anatomyGroup(bone) {
  const groups = state.session.anatomy.groups || {};
  for (const [name, group] of Object.entries(groups)) {
    if ((group.bonesDependencyOrder || []).includes(bone)) return name;
  }
  return "unlabeled";
}

function groupColor(name) {
  const map = {
    trunk: 0xc9a227,
    wing_a: 0xd07a3a,
    wing_b: 0x3aa0d0,
    neck_head: 0xe8dfc8,
    tail: 0x8a6a3a,
    leg_a: 0x7ec37e,
    leg_b: 0xc37e7e,
    unlabeled: 0x888888,
  };
  return map[name] || 0x888888;
}

function collectBones(root) {
  const bones = new Map();
  root.traverse((obj) => {
    if (obj.isBone) bones.set(obj.name, obj);
  });
  return bones;
}

async function loadMesh(name, url) {
  const gltf = await loader.loadAsync(url);
  const root = gltf.scene;
  const bones = collectBones(root);
  const restQuat = new Map();
  bones.forEach((bone, key) => restQuat.set(key, bone.quaternion.clone()));
  root.updateMatrixWorld(true);
  const restWorldQuat = new Map();
  const restWorldPos = new Map();
  bones.forEach((bone, key) => {
    const worldQ = new THREE.Quaternion();
    bone.getWorldQuaternion(worldQ);
    restWorldQuat.set(key, worldQ.clone());
    restWorldPos.set(key, new THREE.Vector3().setFromMatrixPosition(bone.matrixWorld));
  });
  root.traverse((obj) => {
    if (obj.isMesh) {
      obj.material = obj.material.clone();
      obj.material.transparent = true;
      obj.material.opacity = 0.92;
      obj.material.side = THREE.DoubleSide;
      obj.frustumCulled = false;
    }
  });
  const skeleton = new THREE.SkeletonHelper(root);
  skeleton.visible = true;
  scene.add(root);
  scene.add(skeleton);
  root.visible = false;
  return { name, root, bones, restQuat, restWorldQuat, restWorldPos, skeleton };
}

function applyUnlit() {
  const unlit = state.toggles.unlit;
  Object.values(state.rest).forEach((entry) => {
    entry.root.traverse((obj) => {
      if (!obj.isMesh) return;
      const map = obj.material.map;
      if (unlit) {
        obj.material = new THREE.MeshBasicMaterial({
          map: state.toggles.textured ? map : null,
          color: state.toggles.anatomyColors ? groupColor(anatomyGroup(obj.name)) : 0xffffff,
          transparent: true,
          opacity: 0.92,
          side: THREE.DoubleSide,
        });
      }
    });
  });
}

function applyPoseTo(entry, pose) {
  const rest = entry.restQuat;
  entry.bones.forEach((bone, name) => {
    const q = rest.get(name).clone();
    const delta = pose[name] || { x: 0, y: 0, z: 0 };
    q.multiply(axisAngleQuat(delta.x || 0, delta.y || 0, delta.z || 0));
    bone.quaternion.copy(q);
  });
  const basis = cameraBasis();
  const root = pose.__motion_root__ || {};
  const rot = pose.__motion_root_rotation__ || {};
  const translation = new THREE.Vector3()
    .addScaledVector(basis.forward, root.forward || 0)
    .addScaledVector(basis.right, root.lateral || 0)
    .addScaledVector(basis.up, root.vertical || 0);
  entry.root.position.copy(translation);
  const q = new THREE.Quaternion();
  const axes = [
    [basis.forward, rot.camera_forward || 0],
    [basis.right, rot.camera_right || 0],
    [basis.up, rot.camera_up || 0],
  ];
  axes.forEach(([axis, deg]) => {
    q.premultiply(new THREE.Quaternion().setFromAxisAngle(axis, THREE.MathUtils.degToRad(deg)));
  });
  entry.root.quaternion.copy(q);
  entry.root.updateMatrixWorld(true);
}

function restNameForFrame(frame) {
  return state.session.frameRestSources[frame] || "perch";
}

function showRest(name) {
  const preview = meshPreviewOn();
  Object.values(state.rest).forEach((entry) => {
    entry.root.visible = entry.name === name && state.toggles.showMesh;
    entry.skeleton.visible = entry.name === name && state.toggles.showSkeleton && !state.toggles.isolateBone && !preview;
    entry.root.traverse((obj) => {
      if (!obj.isMesh || !obj.material) return;
      obj.material.opacity = preview ? 1 : 0.92;
      obj.material.transparent = !preview;
    });
  });
}

function spriteUrl(frame) {
  return `${state.session.spriteUrlPrefix}${String(frame).padStart(2, "0")}.png`;
}

function neighborFrame(offset) {
  const last = state.session.frameIndices.length - 1;
  let next = state.frame + offset;
  if (state.toggles.playWrap) {
    next = (next + last + 1) % (last + 1);
  }
  if (next < 0 || next > last) return null;
  return next;
}

function updateOnion() {
  const prev = el("spritePrev");
  const next = el("spriteNext");
  if (!prev || !next || !state.session) return;
  const on = state.toggles.onionSkin;
  const prevFrame = neighborFrame(-1);
  const nextFrame = neighborFrame(1);
  prev.classList.toggle("onion-on", on && prevFrame !== null);
  next.classList.toggle("onion-on", on && nextFrame !== null);
  if (on && prevFrame !== null) prev.src = spriteUrl(prevFrame);
  if (on && nextFrame !== null) next.src = spriteUrl(nextFrame);
}

function jointList() {
  const names = new Set();
  const groups = state.session.anatomy.groups || {};
  Object.values(groups).forEach((group) => {
    (group.bonesDependencyOrder || []).forEach((bone) => names.add(bone));
  });
  Object.values(state.rest).forEach((entry) => {
    entry.bones.forEach((_bone, name) => {
      if (!state.toggles.hideHelperNodes || !name.includes("unwrapped")) names.add(name);
    });
  });
  return [...names].filter((name) => name && name !== "UniRigArmature");
}

function fillJoints() {
  const select = el("jointSelect");
  const previous = state.joint;
  select.innerHTML = "";
  jointList().forEach((name) => {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = `${name}  (${anatomyGroup(name)})`;
    select.appendChild(option);
  });
  if (!state.joint || ![...select.options].some((opt) => opt.value === state.joint)) {
    state.joint = select.value;
  }
  select.value = state.joint;
  if (previous !== state.joint) fillSliders();
}

function channelValue(id, pose) {
  const bone = pose[state.joint] || { x: 0, y: 0, z: 0 };
  const root = pose.__motion_root__ || { forward: 0, lateral: 0, vertical: 0 };
  const rot = pose.__motion_root_rotation__ || { camera_forward: 0, camera_right: 0, camera_up: 0 };
  if (id in bone) return bone[id] || 0;
  if (id in root) return root[id] || 0;
  return rot[id] || 0;
}

function syncSliderReadouts() {
  const pose = currentPose();
  el("sliders").querySelectorAll("input").forEach((input) => {
    const value = channelValue(input.dataset.id, pose);
    if (document.activeElement !== input) input.value = String(value);
    const readout = input.closest(".slider-row")?.querySelector("i");
    if (readout) readout.textContent = Number(value).toFixed(2);
  });
}

function fillSliders() {
  const pose = currentPose();
  const bone = pose[state.joint] || { x: 0, y: 0, z: 0 };
  const root = pose.__motion_root__ || { forward: 0, lateral: 0, vertical: 0 };
  const rot = pose.__motion_root_rotation__ || { camera_forward: 0, camera_right: 0, camera_up: 0 };
  const rows = [];
  const add = (id, label, value, min, max, step) => {
    rows.push(`<div class="slider-row"><span><b>${label}</b><i>${Number(value).toFixed(2)}</i></span>
      <input data-id="${id}" type="range" min="${min}" max="${max}" step="${step}" value="${value}"></div>`);
  };
  add("x", `${state.joint} x`, bone.x || 0, -180, 180, state.toggles.snapCoarse ? 45 : 0.5);
  add("y", `${state.joint} y`, bone.y || 0, -180, 180, state.toggles.snapCoarse ? 45 : 0.5);
  add("z", `${state.joint} z`, bone.z || 0, -180, 180, state.toggles.snapCoarse ? 45 : 0.5);
  if (!state.toggles.lockRoot) {
    add("forward", "root forward", root.forward || 0, -1, 1, 0.01);
    add("lateral", "root lateral", root.lateral || 0, -1, 1, 0.01);
    add("vertical", "root vertical", root.vertical || 0, -1, 1, 0.01);
    add("camera_forward", "root camera_forward", rot.camera_forward || 0, -90, 90, 1);
    add("camera_right", "root camera_right", rot.camera_right || 0, -90, 90, 1);
    add("camera_up", "root camera_up", rot.camera_up || 0, -90, 90, 1);
  }
  el("sliders").innerHTML = rows.join("");
  el("sliders").querySelectorAll("input").forEach((input) => {
    input.addEventListener("input", onSlider);
    input.addEventListener("change", () => draw({ overlay: true }));
  });
  el("jointHint").textContent = idleLocked()
    ? "Idle frames are locked. Unlock them in View & edit toggles to change the perch."
    : "Click a joint, then drag it in the view. Shift twists. Alt is finer. Sliders keep moving while you hold them.";
}

function idleLocked() {
  return state.toggles.lockIdle && restNameForFrame(state.frame) === "perch";
}

function pairedBone(name) {
  const pairs = state.session.anatomy.symmetry?.bilateralGroupPairs || [];
  const groups = state.session.anatomy.groups || {};
  for (const [left, right] of pairs) {
    const a = groups[left]?.bonesDependencyOrder || [];
    const b = groups[right]?.bonesDependencyOrder || [];
    const i = a.indexOf(name);
    const j = b.indexOf(name);
    if (i >= 0 && b[i]) return b[i];
    if (j >= 0 && a[j]) return a[j];
  }
  return null;
}

function bilateralBonePairs() {
  const pairs = state.session.anatomy.symmetry?.bilateralGroupPairs || [];
  const groups = state.session.anatomy.groups || {};
  const out = [];
  for (const [left, right] of pairs) {
    const a = groups[left]?.bonesDependencyOrder || [];
    const b = groups[right]?.bonesDependencyOrder || [];
    if (a.length !== b.length) {
      status(`Symmetry pair ${left}/${right} has unequal bone counts.`);
      return null;
    }
    for (let i = 0; i < a.length; i += 1) {
      out.push([a[i], b[i]]);
    }
  }
  return out;
}

function poseEntry(store, frame) {
  return store[frame] || store[String(frame)];
}

function idleReferencePose() {
  const idleFrame = Number(state.session.idleReferenceFrame ?? 0);
  return poseEntry(state.idlePoses, idleFrame);
}

function copyJointChannels(src) {
  const next = {};
  for (const [key, value] of Object.entries(src || {})) {
    if (String(key).startsWith("__")) continue;
    next[key] = clonePose(value);
  }
  return next;
}

function enforceSymmetry() {
  if (idleLocked()) {
    status("Idle frames are locked.");
    return;
  }
  const pairs = bilateralBonePairs();
  if (!pairs) return;
  if (!pairs.length) {
    status("No bilateral pairs in the anatomy catalog.");
    return;
  }
  const mode = el("symmetryMode").value;
  const pose = currentPose();
  for (const [nameA, nameB] of pairs) {
    const boneA = ensureBone(pose, nameA);
    const boneB = ensureBone(pose, nameB);
    if (mode === "copy_a_to_b") {
      const mirrored = copyAnatomicalDelta(nameA, nameB, boneA);
      if (!mirrored) return;
      pose[nameB] = mirrored;
    } else if (mode === "copy_b_to_a") {
      const mirrored = copyAnatomicalDelta(nameB, nameA, boneB);
      if (!mirrored) return;
      pose[nameA] = mirrored;
    } else if (mode === "average") {
      const averaged = averageAnatomicalPair(nameA, nameB, boneA, boneB);
      if (!averaged) return;
      pose[nameA] = averaged.a;
      pose[nameB] = averaged.b;
    } else {
      status(`Unknown symmetry mode ${mode}.`);
      return;
    }
  }
  state.dirty = true;
  fillSliders();
  draw();
  status(`Enforced symmetry (${mode}) on this frame.`);
}

function resetFrameToIdle() {
  const perch = restNameForFrame(state.frame) === "perch";
  if (perch && idleLocked()) {
    status("Idle frames are locked.");
    return;
  }
  const idle = idleReferencePose();
  if (!idle) {
    status("No idle pose is loaded.");
    return;
  }
  const dest = currentPose();
  const next = copyJointChannels(idle);
  if (perch) {
    poseStore(state.frame)[state.frame] = clonePose(idle);
  } else {
    if (dest.__motion_root__) next.__motion_root__ = clonePose(dest.__motion_root__);
    if (dest.__motion_root_rotation__) {
      next.__motion_root_rotation__ = clonePose(dest.__motion_root_rotation__);
    }
    poseStore(state.frame)[state.frame] = next;
  }
  state.dirty = true;
  fillSliders();
  draw();
  status(
    perch
      ? "Reset this idle frame to the idle pose."
      : "Reset this frame's joints to the idle pose. Motion root is unchanged."
  );
}

function applyChannel(id, value) {
  if (idleLocked()) {
    status("Idle frames are locked.");
    return false;
  }
  const pose = currentPose();
  if (["x", "y", "z"].includes(id)) {
    ensureBone(pose, state.joint)[id] = value;
    if (state.toggles.mirrorBilateral) {
      const other = pairedBone(state.joint);
      if (other) {
        const mirrored = copyAnatomicalDelta(state.joint, other, ensureBone(pose, state.joint));
        if (mirrored) pose[other] = mirrored;
      }
    }
  } else if (["forward", "lateral", "vertical"].includes(id)) {
    pose.__motion_root__ = pose.__motion_root__ || { forward: 0, lateral: 0, vertical: 0 };
    pose.__motion_root__[id] = value;
  } else {
    pose.__motion_root_rotation__ = pose.__motion_root_rotation__ || {
      camera_forward: 0,
      camera_right: 0,
      camera_up: 0,
    };
    pose.__motion_root_rotation__[id] = value;
  }
  state.dirty = true;
  return true;
}

function onSlider(event) {
  const id = event.target.dataset.id;
  const value = Number(event.target.value);
  if (!applyChannel(id, value)) {
    syncSliderReadouts();
    return;
  }
  const readout = event.target.closest(".slider-row")?.querySelector("i");
  if (readout) readout.textContent = value.toFixed(2);
  draw({ overlay: false });
}

function selectJoint(name, rebuildSliders = true) {
  if (!name || name === state.joint) {
    if (rebuildSliders) fillSliders();
    return;
  }
  state.joint = name;
  el("jointSelect").value = name;
  if (rebuildSliders) fillSliders();
}

function setFrame(frame) {
  const frames = state.session.frameIndices;
  const last = frames.length - 1;
  let next = frame;
  const wrap = state.toggles.playWrap;
  if (wrap) {
    next = (frame + frames.length) % frames.length;
  } else {
    if (frame > last) {
      state.playing = false;
      el("playBtn").textContent = "Play";
      next = last;
    } else if (frame < 0) {
      next = 0;
    } else {
      next = frame;
    }
  }
  state.frame = next;
  el("frameSlider").value = String(next);
  const label = `f${String(next).padStart(2, "0")}`;
  const phase = restNameForFrame(next);
  el("frameLabel").textContent = label;
  el("phaseLabel").textContent = phase;
  const url = spriteUrl(next);
  el("sprite").src = url;
  el("spritePlate").src = url;
  el("plateMeta").textContent = `${label} ${phase}`;
  updateOnion();
  fillSliders();
  draw();
}

function cacheSilhouette(sprite, w, h) {
  const key = `${state.frame}:${sprite.src}:${w}x${h}`;
  if (state.silhouetteKey === key) return;
  silhouette.width = w;
  silhouette.height = h;
  silhouetteCtx.clearRect(0, 0, w, h);
  silhouetteCtx.fillStyle = "rgba(250, 230, 140, 0.85)";
  scratch.width = w;
  scratch.height = h;
  scratchCtx.clearRect(0, 0, w, h);
  scratchCtx.drawImage(sprite, 0, 0, w, h);
  const spriteData = scratchCtx.getImageData(0, 0, w, h).data;
  for (let y = 1; y < h - 1; y += 1) {
    for (let x = 1; x < w - 1; x += 1) {
      const a = spriteData[(y * w + x) * 4 + 3] > 16;
      if (!a) continue;
      const edge =
        spriteData[(y * w + x - 1) * 4 + 3] <= 16 ||
        spriteData[(y * w + x + 1) * 4 + 3] <= 16 ||
        spriteData[((y - 1) * w + x) * 4 + 3] <= 16 ||
        spriteData[((y + 1) * w + x) * 4 + 3] <= 16;
      if (edge) silhouetteCtx.fillRect(x, y, 1, 1);
    }
  }
  state.silhouetteKey = key;
}

function drawOverlay({ leftover = true } = {}) {
  const ctx = overlayCtx;
  const w = overlay.width;
  const h = overlay.height;
  ctx.clearRect(0, 0, w, h);
  if (!state.toggles.showSilhouette && !(leftover && state.toggles.leftoverApprox)) return;
  const sprite = el("sprite");
  if (!sprite.complete || sprite.naturalWidth < 1) return;
  if (leftover && state.toggles.leftoverApprox && !state.drag) {
    scratch.width = w;
    scratch.height = h;
    scratchCtx.clearRect(0, 0, w, h);
    scratchCtx.drawImage(sprite, 0, 0, w, h);
    const spriteData = scratchCtx.getImageData(0, 0, w, h).data;
    scratchCtx.clearRect(0, 0, w, h);
    scratchCtx.drawImage(renderer.domElement, 0, 0, w, h);
    const meshData = scratchCtx.getImageData(0, 0, w, h).data;
    const out = ctx.createImageData(w, h);
    for (let i = 0; i < spriteData.length; i += 4) {
      const s = spriteData[i + 3] > 16;
      const m = meshData[i + 3] > 16;
      if (s && !m) {
        out.data[i] = 220;
        out.data[i + 1] = 40;
        out.data[i + 2] = 40;
        out.data[i + 3] = 140;
      } else if (m && !s) {
        out.data[i] = 40;
        out.data[i + 1] = 90;
        out.data[i + 2] = 220;
        out.data[i + 3] = 110;
      }
    }
    ctx.putImageData(out, 0, 0);
  }
  if (state.toggles.showSilhouette) {
    cacheSilhouette(sprite, w, h);
    ctx.drawImage(silhouette, 0, 0);
  }
}

function keepIsolated(name) {
  if (!state.toggles.isolateBone) return true;
  if (name === state.joint) return true;
  return pairedBone(state.joint) === name;
}

function pixelWorld(pixels) {
  const width = renderer.domElement.clientWidth || 1;
  return ((camera.right - camera.left) / width) * pixels;
}

function syncMarkers(entry) {
  const names = new Set(jointList());
  for (const [name, mesh] of state.markers) {
    if (!names.has(name) || !entry.bones.has(name)) {
      markerGroup.remove(mesh);
      state.markers.delete(name);
    }
  }
  names.forEach((name) => {
    const bone = entry.bones.get(name);
    if (!bone) return;
    let mesh = state.markers.get(name);
    if (!mesh) {
      mesh = new THREE.Mesh(
        new THREE.SphereGeometry(1, 12, 12),
        new THREE.MeshBasicMaterial({ depthTest: false, transparent: true }),
      );
      mesh.userData.boneName = name;
      mesh.renderOrder = 10;
      markerGroup.add(mesh);
      state.markers.set(name, mesh);
    }
    bone.updateWorldMatrix(true, false);
    mesh.position.setFromMatrixPosition(bone.matrixWorld);
    const selected = name === state.joint;
    const hovered = name === state.hoverJoint;
    const visible = state.toggles.showJointMarkers && keepIsolated(name);
    mesh.visible = true;
    mesh.material.opacity = visible ? 1 : 0.001;
    mesh.material.color.setHex(selected ? 0xffee88 : hovered ? 0xffffff : groupColor(anatomyGroup(name)));
    const radius = pixelWorld(selected || hovered ? 10 : 7);
    mesh.scale.setScalar(Math.max(radius, 0.008));
  });
}

function projectBone(bone, width, height) {
  bone.updateWorldMatrix(true, false);
  const projected = new THREE.Vector3().setFromMatrixPosition(bone.matrixWorld).project(camera);
  if (projected.z < -1 || projected.z > 1) return null;
  return {
    x: (projected.x * 0.5 + 0.5) * width,
    y: (-projected.y * 0.5 + 0.5) * height,
  };
}

function drawHits(entry) {
  const host = el("hits");
  if (!host) return;
  host.innerHTML = "";
  if (!entry || state.drag) return;
  const canvas = renderer.domElement;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  const allowed = jointList();
  allowed.forEach((name) => {
    const bone = entry.bones.get(name);
    if (!bone || !keepIsolated(name)) return;
    const pos = projectBone(bone, width, height);
    if (!pos) return;
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.bone = name;
    button.title = `${name} (${anatomyGroup(name)})`;
    button.setAttribute("aria-label", `Joint ${name}`);
    button.className = name === state.joint ? "selected" : name === state.hoverJoint ? "hover" : "";
    button.style.left = `${pos.x}px`;
    button.style.top = `${pos.y}px`;
    host.appendChild(button);
  });
}

function drawLabels(entry) {
  const host = el("labels");
  if (!host) return;
  host.innerHTML = "";
  if (!state.toggles.showLabels) return;
  const canvas = renderer.domElement;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  entry.bones.forEach((bone, name) => {
    if (!keepIsolated(name)) return;
    if (!jointList().includes(name)) return;
    bone.updateWorldMatrix(true, false);
    const projected = new THREE.Vector3().setFromMatrixPosition(bone.matrixWorld).project(camera);
    if (projected.z < -1 || projected.z > 1) return;
    const span = document.createElement("span");
    span.dataset.bone = name;
    span.textContent = name;
    span.style.left = `${(projected.x * 0.5 + 0.5) * width}px`;
    span.style.top = `${(-projected.y * 0.5 + 0.5) * height}px`;
    host.appendChild(span);
  });
}

function currentEntry() {
  if (!state.session) return null;
  const name = restNameForFrame(state.frame);
  return state.rest[name] || state.rest.perch || null;
}

function draw({ overlay = true } = {}) {
  if (!state.session) return;
  const preview = meshPreviewOn();
  syncMeshPreviewClass();
  const name = restNameForFrame(state.frame);
  showRest(name);
  updateOnion();
  const entry = currentEntry();
  state.helpers.forEach((helper) => scene.remove(helper));
  state.helpers = [];
  if (entry) {
    if (state.toggles.ghostBind && !preview) {
      applyPoseTo(entry, {});
      entry.bones.forEach((bone) => {
        const geom = new THREE.SphereGeometry(pixelWorld(5), 8, 8);
        const mat = new THREE.MeshBasicMaterial({ color: 0x667788, transparent: true, opacity: 0.4, depthTest: false });
        const mesh = new THREE.Mesh(geom, mat);
        bone.updateWorldMatrix(true, false);
        mesh.position.setFromMatrixPosition(bone.matrixWorld);
        scene.add(mesh);
        state.helpers.push(mesh);
      });
    }
    applyPoseTo(entry, currentPose());
    if (!preview) syncMarkers(entry);
    else {
      state.markers.forEach((mesh) => {
        mesh.visible = false;
      });
    }
  }
  grid.visible = state.toggles.grid && !preview;
  el("sprite").style.opacity = preview || !state.toggles.showSprite ? "0" : "1";
  document.body.classList.toggle("silhouette-only", state.toggles.highContrast && !preview);
  applyViewCamera();
  renderer.render(scene, camera);
  if (!preview) drawOverlay({ leftover: overlay && !state.drag });
  else overlayCtx.clearRect(0, 0, overlay.width, overlay.height);
  if (entry && !state.drag && !preview) {
    drawHits(entry);
    drawLabels(entry);
  } else if (state.drag) {
    /* Keep the last hit buttons so pointer capture can finish the drag. */
  } else {
    if (el("hits")) el("hits").innerHTML = "";
    if (el("labels")) el("labels").innerHTML = "";
  }
  const leftoverNote = !preview && state.toggles.leftoverApprox ? "red leftover / blue extra (browser approx)" : "";
  const zoomNote = state.viewZoom !== 1 ? `zoom ${state.viewZoom.toFixed(2)}×` : "";
  el("hud").textContent = [
    `${unit} ${clip}`,
    `f${String(state.frame).padStart(2, "0")} ${name}`,
    leftoverNote,
    zoomNote,
    preview ? "mesh only" : "",
    state.drag ? "dragging" : "",
    state.dirty ? "unsaved" : "",
  ].filter(Boolean).join(" · ");
}

function eventNdc(event) {
  const rect = renderer.domElement.getBoundingClientRect();
  pointerNdc.set(
    ((event.clientX - rect.left) / rect.width) * 2 - 1,
    -((event.clientY - rect.top) / rect.height) * 2 - 1,
  );
  return pointerNdc;
}

function hitJoint(event) {
  const entry = currentEntry();
  if (!entry) return "";
  raycaster.setFromCamera(eventNdc(event), camera);
  const hits = raycaster.intersectObjects([...state.markers.values()], false);
  const allowed = new Set(jointList());
  for (const hit of hits) {
    const name = hit.object.userData.boneName;
    if (name && allowed.has(name)) return name;
  }
  return "";
}

function worldQuatFromDelta(bone, startWorldQ, deltaQ) {
  return deltaQ.clone().multiply(startWorldQ);
}

function writeBoneWorldQuat(entry, boneName, worldQuat) {
  const bone = entry.bones.get(boneName);
  const rest = entry.restQuat.get(boneName);
  if (!bone || !rest) return;
  if (bone.parent) bone.parent.getWorldQuaternion(_parentQ);
  else _parentQ.identity();
  const local = _parentQ.clone().invert().multiply(worldQuat);
  const delta = rest.clone().invert().multiply(local);
  const xyz = quatToAxisAngleDeg(delta);
  const pose = currentPose();
  pose[boneName] = xyz;
  if (state.toggles.mirrorBilateral) {
    const other = pairedBone(boneName);
    if (other) {
      const mirrored = copyAnatomicalDelta(boneName, other, xyz);
      if (mirrored) pose[other] = mirrored;
    }
  }
  state.dirty = true;
}

function armPick(event, boneName) {
  const entry = currentEntry();
  const bone = entry?.bones.get(boneName);
  if (!bone) return;
  selectJoint(boneName);
  bone.updateWorldMatrix(true, false);
  const jointWorld = new THREE.Vector3().setFromMatrixPosition(bone.matrixWorld);
  const jointNdc = jointWorld.clone().project(camera);
  const parent = bone.parent;
  let mode = "trackball";
  let parentNdc = null;
  let startAngle = 0;
  if (parent) {
    parent.updateWorldMatrix(true, false);
    const parentWorld = new THREE.Vector3().setFromMatrixPosition(parent.matrixWorld);
    parentNdc = parentWorld.clone().project(camera);
    const dx = jointNdc.x - parentNdc.x;
    const dy = jointNdc.y - parentNdc.y;
    if (Math.hypot(dx, dy) > 0.02) {
      mode = "orbit";
      startAngle = Math.atan2(dy, dx);
    }
  }
  const startWorldQ = new THREE.Quaternion();
  bone.getWorldQuaternion(startWorldQ);
  state.pending = {
    boneName,
    mode,
    startWorldQ,
    parentNdc,
    startAngle,
    pointer: eventNdc(event).clone(),
    clientX: event.clientX,
    clientY: event.clientY,
    pointerId: event.pointerId,
  };
  const cap = event.target instanceof Element ? event.target : el("view");
  try {
    cap.setPointerCapture(event.pointerId);
    state.pending.captureEl = cap;
  } catch (_err) {
    /* window move listeners still drive the drag */
  }
  orbit.enabled = false;
}

function continueDrag(event) {
  if (state.pending && !state.drag) {
    const dx = event.clientX - state.pending.clientX;
    const dy = event.clientY - state.pending.clientY;
    if (Math.hypot(dx, dy) >= 4) {
      state.drag = state.pending;
      state.pending = null;
      document.body.classList.add("dragging");
    }
  }
  const drag = state.drag;
  const entry = currentEntry();
  if (!drag || !entry || idleLocked()) return;
  const now = eventNdc(event);
  const bone = entry.bones.get(drag.boneName);
  if (!bone) return;
  const fine = event.altKey ? 0.25 : 1;
  let deltaQ = new THREE.Quaternion();
  if (drag.mode === "orbit" && drag.parentNdc && !event.shiftKey) {
    const angle = Math.atan2(now.y - drag.parentNdc.y, now.x - drag.parentNdc.x);
    const dAngle = (angle - drag.startAngle) * fine;
    const axis = new THREE.Vector3();
    camera.getWorldDirection(axis);
    deltaQ.setFromAxisAngle(axis, dAngle);
  } else {
    const dx = (now.x - drag.pointer.x) * fine;
    const dy = (now.y - drag.pointer.y) * fine;
    const up = camera.up.clone().normalize();
    const forward = new THREE.Vector3();
    camera.getWorldDirection(forward);
    const right = new THREE.Vector3().crossVectors(up, forward).normalize();
    if (event.shiftKey) {
      deltaQ.setFromAxisAngle(forward.clone().negate(), dx * 1.6);
    } else {
      deltaQ.multiply(new THREE.Quaternion().setFromAxisAngle(up, dx * 1.4));
      deltaQ.multiply(new THREE.Quaternion().setFromAxisAngle(right, -dy * 1.4));
    }
  }
  writeBoneWorldQuat(entry, drag.boneName, worldQuatFromDelta(bone, drag.startWorldQ, deltaQ));
  syncSliderReadouts();
  draw({ overlay: false });
}

function endDrag() {
  const armed = state.drag || state.pending;
  if (!armed) return;
  const cap = armed.captureEl;
  try {
    if (cap) cap.releasePointerCapture(armed.pointerId);
  } catch (_err) {
    /* already released */
  }
  const posed = Boolean(state.drag);
  state.drag = null;
  state.pending = null;
  document.body.classList.remove("dragging");
  draw({ overlay: true });
  if (posed) status("Pose updated. Save when you want it written to the worktree.");
}

function bindPointer() {
  const canvas = el("view");
  const pickFromEvent = (event) => event.target?.dataset?.bone || hitJoint(event);
  const onPickDown = (event) => {
    if (event.button !== 0) return;
    if (meshPreviewOn()) return;
    const name = pickFromEvent(event);
    if (!name) return;
    event.preventDefault();
    event.stopPropagation();
    if (idleLocked()) {
      selectJoint(name);
      draw({ overlay: true });
      status("Idle frames are locked. Unlock them to drag this perch pose.");
      return;
    }
    armPick(event, name);
  };
  const onMove = (event) => {
    if (state.pending || state.drag) {
      continueDrag(event);
      return;
    }
    const name = hitJoint(event);
    canvas.style.cursor = name ? "grab" : "";
    if (name !== state.hoverJoint) {
      state.hoverJoint = name;
      const entry = currentEntry();
      if (entry) syncMarkers(entry);
      renderer.render(scene, camera);
    }
  };
  canvas.addEventListener("pointerdown", onPickDown);
  el("hits").addEventListener("pointerdown", onPickDown);
  el("labels").addEventListener("pointerdown", onPickDown);
  canvas.addEventListener("mousedown", onPickDown);
  el("hits").addEventListener("mousedown", onPickDown);
  window.addEventListener("pointermove", onMove);
  window.addEventListener("mousemove", onMove);
  window.addEventListener("pointerup", endDrag);
  window.addEventListener("mouseup", endDrag);
  window.addEventListener("pointercancel", endDrag);
  el("viewport").addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      const factor = event.deltaY > 0 ? 1 / 1.12 : 1.12;
      zoomAtEvent(event, factor);
    },
    { passive: false },
  );
  el("viewport").addEventListener("dblclick", (event) => {
    if (hitJoint(event)) return;
    resetView();
  });
}

function fillToggles() {
  el("toggleGrid").innerHTML = TOGGLES.map(([id, label]) => {
    const on = state.toggles[id] ? "checked" : "";
    return `<label><input type="checkbox" data-toggle="${id}" ${on}> ${label}</label>`;
  }).join("");
  el("toggleGrid").querySelectorAll("input").forEach((input) => {
    input.addEventListener("change", (event) => {
      state.toggles[event.target.dataset.toggle] = event.target.checked;
      if (
        event.target.dataset.toggle === "unlit" ||
        event.target.dataset.toggle === "textured" ||
        event.target.dataset.toggle === "anatomyColors"
      ) {
        applyUnlit();
      }
      fillJoints();
      fillSliders();
      draw();
    });
  });
}

async function save(kind) {
  const payload = {
    unit,
    clip,
    poseUnits: "degrees",
    neverMasterGlb: true,
    sourceRound: state.session.sourceRound,
    frameIndices: state.session.frameIndices,
    idlePoses: state.idlePoses,
    flyPoses: state.flyPoses,
  };
  if (kind === "download") {
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${unit}_${clip}_manual_poses.json`;
    a.click();
    status("Exported JSON download.");
    return;
  }
  const response = await fetch("/api/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json();
  if (!body.ok) {
    status(`Save failed: ${body.error}`);
    return;
  }
  state.dirty = false;
  status(`Saved ${body.dir}\nSnapshot ${body.snapshot}`);
  draw();
}

function bindUi() {
  el("frameSlider").addEventListener("input", (event) => setFrame(Number(event.target.value)));
  el("prevBtn").addEventListener("click", () => setFrame(state.frame - 1));
  el("nextBtn").addEventListener("click", () => setFrame(state.frame + 1));
  el("playBtn").addEventListener("click", () => {
    state.playing = !state.playing;
    el("playBtn").textContent = state.playing ? "Pause" : "Play";
  });
  el("jointSelect").addEventListener("change", (event) => {
    selectJoint(event.target.value);
    draw();
  });
  el("zeroJoint").addEventListener("click", () => {
    if (idleLocked()) return;
    currentPose()[state.joint] = { x: 0, y: 0, z: 0 };
    state.dirty = true;
    fillSliders();
    draw();
  });
  el("copyPrev").addEventListener("click", () => {
    if (state.frame <= 0 || idleLocked()) return;
    if (restNameForFrame(state.frame) !== restNameForFrame(state.frame - 1)) {
      status("Cannot copy a perch pose onto a fly rest (or the reverse).");
      return;
    }
    const prev = poseStore(state.frame - 1)[state.frame - 1];
    poseStore(state.frame)[state.frame] = clonePose(prev);
    state.dirty = true;
    fillSliders();
    draw();
  });
  el("enforceSymmetry").addEventListener("click", enforceSymmetry);
  el("resetIdlePose").addEventListener("click", resetFrameToIdle);
  el("saveBtn").addEventListener("click", () => save("worktree"));
  el("exportBtn").addEventListener("click", () => save("download"));
  el("meshPreviewBtn").addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch (_err) {
      /* capture is optional */
    }
    state.meshPreviewHeld = true;
    state.meshPreviewHeldFrom = performance.now();
    state.meshPreviewHeldWasOn = state.meshPreview;
    syncMeshPreviewClass();
    draw();
  });
  el("meshPreviewBtn").addEventListener("pointerup", (event) => {
    if (!state.meshPreviewHeld) return;
    const heldMs = performance.now() - (state.meshPreviewHeldFrom || 0);
    state.meshPreviewHeld = false;
    if (heldMs >= 280) {
      state.meshPreview = Boolean(state.meshPreviewHeldWasOn);
    } else {
      state.meshPreview = !state.meshPreviewHeldWasOn;
    }
    syncMeshPreviewClass();
    draw();
  });
  el("resetViewBtn").addEventListener("click", resetView);
  window.addEventListener("keydown", (event) => {
    if (event.target.matches("input, select, textarea")) return;
    if (event.key === "ArrowLeft") setFrame(state.frame - 1);
    if (event.key === "ArrowRight") setFrame(state.frame + 1);
    if (event.key === " ") {
      event.preventDefault();
      el("playBtn").click();
    }
    if (event.key.toLowerCase() === "v" && !event.repeat) {
      event.preventDefault();
      setMeshPreview(!state.meshPreview);
    }
    if (event.key === "0" && !event.ctrlKey && !event.metaKey) resetView();
    if (event.key.toLowerCase() === "s" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      save("worktree");
    }
  });
  el("sprite").addEventListener("load", () => draw({ overlay: !state.drag }));
  el("spritePlate").addEventListener("load", () => {});
  window.addEventListener("resize", () => {
    resize();
    draw();
  });
  bindPointer();
}

async function start() {
  fillToggles();
  const session = await (await fetch(`/api/session?unit=${encodeURIComponent(unit)}&clip=${encodeURIComponent(clip)}`)).json();
  if (session.error) {
    status(session.error);
    return;
  }
  state.session = session;
  state.idlePoses = clonePose(session.idlePoses);
  state.flyPoses = clonePose(session.flyPoses);
  el("meta").textContent = `${unit} / ${clip} · ${session.sourceRound} · degrees · never masterGlb`;
  el("frameSlider").max = String(session.frameIndices.length - 1);
  bindUi();
  fillJoints();
  resize();
  setFrame(0);
  const meshEntries = Object.entries(session.meshUrls);
  for (let i = 0; i < meshEntries.length; i += 1) {
    const [name, url] = meshEntries[i];
    status(`Sprite is live. Loading ${name} GLB (${i + 1}/${meshEntries.length})…`);
    state.rest[name] = await loadMesh(name, url);
    applyUnlit();
    fillJoints();
    draw();
  }
  status("Loaded. Click a joint and drag it. Left pane is the original sprite. Red leftover / blue extra is a browser approximation.");
  let last = 0;
  const tick = (now) => {
    if (state.playing && now - last >= (session.playbackMs || 180)) {
      last = now;
      setFrame(state.frame + 1);
    } else if (!state.drag) {
      renderer.render(scene, camera);
    }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

start().catch((err) => {
  status(String(err));
});
