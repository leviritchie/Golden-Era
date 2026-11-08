import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const $ = (id) => document.getElementById(id);
const PALETTE = [
  0xef4444, 0x22c55e, 0x3b82f6, 0xeab308, 0xa855f7, 0x14b8a6, 0xf97316, 0xec4899,
];

const state = {
  unit: null,
  payload: null,
  clipName: "",
  mode: "orbit",
  playing: false,
  frame: 0,
  frameCount: 1,
  fps: 12,
  edits: [],
  pickedVertex: -1,
  mixer: null,
  action: null,
  clip: null,
  skinned: null,
  originalInverses: [],
  bindWorlds: [],
  originalMaterial: null,
  weightMaterial: null,
  neighbors: [],
  mirrorOf: [],
  restPositions: [],
  meshSize: 1,
  boneView: null,
  boneSpheres: [],
  boneSticks: [],
  brushCursor: null,
  painting: false,
  selectedBone: "",
  bindLocalPos: [],
  bindLocalQuat: [],
  boneLengthScale: {},
  followDirty: false,
  weightRewriteFromBind: false,
  skinRules: null,
  clock: new THREE.Clock(),
};

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x2a261e);
const camera = new THREE.PerspectiveCamera(40, 1, 0.01, 10000);
camera.position.set(1.8, 1.4, 2.4);
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
renderer.setPixelRatio(window.devicePixelRatio || 1);
renderer.outputColorSpace = THREE.SRGBColorSpace;
const viewport = $("viewport");
viewport.appendChild(renderer.domElement);
renderer.domElement.style.display = "block";
renderer.domElement.style.width = "100%";
renderer.domElement.style.height = "100%";
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 0.8, 0);
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
const loader = new GLTFLoader();
const root = new THREE.Group();
scene.add(root);
scene.add(new THREE.AmbientLight(0xffffff, 0.55));
scene.add(new THREE.HemisphereLight(0xfff3d0, 0x1a1610, 1.1));
const key = new THREE.DirectionalLight(0xffffff, 1.1);
key.position.set(2.5, 4, 3);
scene.add(key);
scene.add(new THREE.GridHelper(4, 8, 0x6a5b32, 0x3a3428));

function status(text) {
  $("status").textContent = text;
}

function currentDelta() {
  return {
    yawDeg: Number($("yaw").value),
    pitchDeg: Number($("pitch").value),
    rollDeg: Number($("roll").value),
    scale: Number($("scale").value),
    translation: [Number($("tx").value), Number($("ty").value), Number($("tz").value)],
  };
}

function deltaMatrix() {
  const d = currentDelta();
  const euler = new THREE.Euler(
    THREE.MathUtils.degToRad(d.pitchDeg),
    THREE.MathUtils.degToRad(d.yawDeg),
    THREE.MathUtils.degToRad(d.rollDeg),
    "YXZ",
  );
  const matrix = new THREE.Matrix4().makeRotationFromEuler(euler);
  matrix.scale(new THREE.Vector3(d.scale, d.scale, d.scale));
  matrix.setPosition(d.translation[0], d.translation[1], d.translation[2]);
  return matrix;
}

function syncDeltaLabels() {
  const d = currentDelta();
  $("yawOut").textContent = d.yawDeg.toFixed(1);
  $("pitchOut").textContent = d.pitchDeg.toFixed(1);
  $("rollOut").textContent = d.rollDeg.toFixed(1);
  $("scaleOut").textContent = d.scale.toFixed(3);
  $("txOut").textContent = d.translation[0].toFixed(2);
  $("tyOut").textContent = d.translation[1].toFixed(2);
  $("tzOut").textContent = d.translation[2].toFixed(2);
}

function deltaIsIdentity(delta) {
  return (
    Math.abs(delta.yawDeg) < 1e-6 &&
    Math.abs(delta.pitchDeg) < 1e-6 &&
    Math.abs(delta.rollDeg) < 1e-6 &&
    Math.abs(delta.scale - 1) < 1e-6 &&
    delta.translation.every((value) => Math.abs(value) < 1e-6)
  );
}

function restoreBind() {
  const skeleton = state.skinned?.skeleton;
  if (!skeleton) return;
  skeleton.boneInverses.forEach((matrix, index) => {
    matrix.copy(state.originalInverses[index]);
  });
  if (skeleton.boneTexture) skeleton.computeBoneTexture();
}

function applyBindDelta() {
  const skinned = state.skinned;
  if (!skinned) return;
  if (deltaIsIdentity(currentDelta())) {
    restoreBind();
    return;
  }
  skinned.updateMatrixWorld(true);
  const skeleton = skinned.skeleton;
  const D = deltaMatrix();
  const Dinv = new THREE.Matrix4().copy(D).invert();
  skeleton.bones.forEach((bone, index) => {
    bone.matrixWorld.premultiply(D);
    skeleton.boneInverses[index].copy(state.originalInverses[index]).multiply(Dinv);
  });
  if (skeleton.boneTexture) skeleton.computeBoneTexture();
}

function displayBoneMatrix(bone) {
  const world = bone.matrixWorld.clone();
  if (!deltaIsIdentity(currentDelta())) world.premultiply(deltaMatrix());
  return world;
}

function frameCamera(skinned) {
  skinned.geometry.computeBoundingBox();
  const box = skinned.geometry.boundingBox.clone();
  box.applyMatrix4(skinned.matrixWorld);
  if (!Number.isFinite(box.min.x) || box.isEmpty()) {
    box.set(new THREE.Vector3(-1, -1, -1), new THREE.Vector3(1, 1, 1));
  }
  const center = box.getCenter(new THREE.Vector3());
  const size = Math.max(box.getSize(new THREE.Vector3()).length(), 0.5);
  state.meshSize = size;
  controls.target.copy(center);
  camera.near = Math.max(size / 200, 0.001);
  camera.far = Math.max(size * 20, 20);
  camera.position.copy(center).add(new THREE.Vector3(size * 0.7, size * 0.45, size * 0.9));
  camera.updateProjectionMatrix();
  controls.update();
}

function setSelectedBone(name) {
  state.selectedBone = name;
  if ($("paintBone")) $("paintBone").value = name;
  if ($("seatBone")) $("seatBone").value = name;
  if ($("lengthBone")) $("lengthBone").value = name;
  syncLengthSlider();
  refreshWeightColors();
}

function setMode(mode) {
  state.mode = mode;
  $("shiftPane").hidden = mode !== "shift" && mode !== "orbit";
  $("lengthPane").hidden = mode !== "length";
  $("paintPane").hidden = mode !== "paint";
  $("trimPane").hidden = mode !== "trim";
  if (mode === "paint" || mode === "trim" || mode === "length") {
    $("shading").value = mode === "length" ? $("shading").value : "weights";
    if (mode !== "length" && Number($("xray").value) > 0.55) $("xray").value = "0.42";
  }
  if (mode === "length" && Number($("xray").value) > 0.7) $("xray").value = "0.45";
  applyShading();
  applyXray();
}

function fillBoneSelects(names) {
  const excluded = new Set([...($("skinExclude")?.selectedOptions || [])].map((option) => option.value));
  for (const id of ["seatBone", "paintBone", "lengthBone", "skinExclude"]) {
    const select = $(id);
    const previous = select.value;
    select.innerHTML = "";
    names.forEach((name) => {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      if (id === "skinExclude") option.selected = excluded.has(name);
      select.appendChild(option);
    });
    if (id !== "skinExclude") select.value = names.includes(previous) ? previous : names[0] || "";
  }
  setSelectedBone($("paintBone").value || names[0] || "");
}

function boneNames() {
  return state.skinned.skeleton.bones.map((bone) => bone.name);
}

function boneIndex(name) {
  return state.skinned.skeleton.bones.findIndex((bone) => bone.name === name);
}

function boneParentIndex(index) {
  const bones = state.skinned.skeleton.bones;
  return bones.findIndex((bone) => bone === bones[index].parent);
}

function descendantIndices(rootIndex) {
  const bones = state.skinned.skeleton.bones;
  const found = [];
  const walk = (parent) => {
    bones.forEach((bone, index) => {
      if (bone.parent === bones[parent]) {
        found.push(index);
        walk(index);
      }
    });
  };
  walk(rootIndex);
  return found;
}

function lengthScale(name) {
  return state.boneLengthScale[name] ?? 1;
}

function scaledBindPosition(index) {
  const bone = state.skinned.skeleton.bones[index];
  return state.bindLocalPos[index].clone().multiplyScalar(lengthScale(bone.name));
}

function prepareBindPositions() {
  if (!state.skinned || !state.bindLocalPos.length) return;
  state.skinned.skeleton.bones.forEach((bone, index) => {
    bone.position.copy(state.bindLocalPos[index]);
  });
}

function applyBoneLengthLocals() {
  if (!state.skinned || !state.bindLocalPos.length) return;
  state.skinned.skeleton.bones.forEach((bone, index) => {
    const bind = state.bindLocalPos[index];
    const current = bone.position.clone();
    bone.position.copy(bind).multiplyScalar(lengthScale(bone.name)).add(current.sub(bind));
  });
}

function syncLengthSlider() {
  const name = state.selectedBone;
  const index = boneIndex(name);
  $("boneLength").value = String(lengthScale(name));
  $("boneLengthOut").textContent = lengthScale(name).toFixed(2);
  if (index < 0 || !state.bindLocalPos[index]) {
    $("lengthHint").textContent = "";
    return;
  }
  const restLen = state.bindLocalPos[index].length();
  if (restLen <= 1e-6) {
    $("lengthHint").textContent = `${name} has no bind offset. Select a child bone.`;
  } else {
    $("lengthHint").textContent = `Bind offset ${restLen.toFixed(3)} → ${(restLen * lengthScale(name)).toFixed(3)}`;
  }
}

function recomputeBindInverses() {
  const bones = state.skinned.skeleton.bones;
  const savedQ = bones.map((bone) => bone.quaternion.clone());
  bones.forEach((bone, index) => {
    bone.quaternion.copy(state.bindLocalQuat[index]);
    bone.position.copy(scaledBindPosition(index));
  });
  root.updateMatrixWorld(true);
  bones.forEach((bone, index) => {
    state.originalInverses[index] = bone.matrixWorld.clone().invert();
    state.skinned.skeleton.boneInverses[index].copy(state.originalInverses[index]);
    state.bindWorlds[index] = bone.matrixWorld.clone();
  });
  if (state.skinned.skeleton.boneTexture) state.skinned.skeleton.computeBoneTexture();
  bones.forEach((bone, index) => bone.quaternion.copy(savedQ[index]));
  prepareBindPositions();
  applyBoneLengthLocals();
}

function restJointsInMeshSpace() {
  const worlds = restJointPositions();
  const invMesh = state.skinned.matrixWorld.clone().invert();
  const shifted = deltaIsIdentity(currentDelta()) ? null : deltaMatrix();
  return worlds.map((point) => {
    const world = point.clone();
    if (shifted) world.applyMatrix4(shifted);
    return world.applyMatrix4(invMesh);
  });
}

function restJointPositions() {
  const bones = state.skinned.skeleton.bones;
  const savedQ = bones.map((bone) => bone.quaternion.clone());
  const savedP = bones.map((bone) => bone.position.clone());
  bones.forEach((bone, index) => {
    bone.quaternion.copy(state.bindLocalQuat[index]);
    bone.position.copy(scaledBindPosition(index));
  });
  root.updateMatrixWorld(true);
  const positions = bones.map((bone) => new THREE.Vector3().setFromMatrixPosition(bone.matrixWorld));
  bones.forEach((bone, index) => {
    bone.quaternion.copy(savedQ[index]);
    bone.position.copy(savedP[index]);
  });
  return positions;
}

function segmentDistance(vertex, start, end) {
  const ab = end.clone().sub(start);
  const lengthSq = ab.lengthSq();
  if (lengthSq <= 1e-12) return vertex.distanceTo(start);
  const t = Math.min(1, Math.max(0, vertex.clone().sub(start).dot(ab) / lengthSq));
  return vertex.distanceTo(start.clone().add(ab.multiplyScalar(t)));
}

function outgoingDistances(vertices, joints) {
  const bones = state.skinned.skeleton.bones;
  const dist = vertices.map(() => bones.map(() => Infinity));
  const children = bones.map(() => []);
  bones.forEach((bone, index) => {
    const parent = boneParentIndex(index);
    if (parent >= 0) children[parent].push(index);
  });
  bones.forEach((_bone, joint) => {
    const kids = children[joint];
    vertices.forEach((vertex, v) => {
      if (!kids.length) {
        dist[v][joint] = vertex.distanceTo(joints[joint]);
        return;
      }
      dist[v][joint] = Math.min(...kids.map((child) => segmentDistance(vertex, joints[joint], joints[child])));
    });
  });
  return dist;
}

function nearestSegmentDense(dist, k) {
  return dist.map((row) => {
    const order = row.map((value, index) => ({ value, index })).sort((a, b) => a.value - b.value).slice(0, k);
    const weights = order.map((item) => 1 / (item.value * item.value + 1e-8));
    const total = weights.reduce((sum, value) => sum + value, 0);
    const dense = new Float64Array(row.length);
    order.forEach((item, slot) => {
      dense[item.index] = weights[slot] / total;
    });
    return dense;
  });
}

function unpackDenseWeights() {
  const count = state.skinned.geometry.attributes.position.count;
  const jointCount = state.skinned.skeleton.bones.length;
  const dense = Array.from({ length: count }, () => new Float64Array(jointCount));
  for (let vertex = 0; vertex < count; vertex += 1) {
    const packed = readInfluences(vertex);
    packed.joints.forEach((joint, slot) => {
      if (joint >= 0 && joint < jointCount) dense[vertex][joint] += packed.weights[slot];
    });
  }
  return dense;
}

function packDenseWeights(dense) {
  const slots = readInfluences(0).joints.length;
  dense.forEach((row, vertex) => {
    const order = Array.from(row.keys()).sort((a, b) => row[b] - row[a]).slice(0, slots);
    const joints = Array(slots).fill(0);
    const weights = Array(slots).fill(0);
    order.forEach((joint, slot) => {
      joints[slot] = joint;
      weights[slot] = row[joint];
    });
    writeInfluences(vertex, joints, packedRenormalize(weights));
  });
}

function followWeightsForChain(chain) {
  const positions = state.skinned.geometry.attributes.position;
  const vertices = [];
  for (let i = 0; i < positions.count; i += 1) {
    vertices.push(new THREE.Vector3().fromBufferAttribute(positions, i));
  }
  const joints = restJointsInMeshSpace();
  const prox = nearestSegmentDense(outgoingDistances(vertices, joints), Math.min(4, joints.length));
  const old = unpackDenseWeights();
  old.forEach((row, vertex) => {
    const oldMass = chain.reduce((sum, joint) => sum + row[joint], 0);
    const newMass = chain.reduce((sum, joint) => sum + prox[vertex][joint], 0);
    if (oldMass <= 1e-8 || newMass <= 1e-8) return;
    const scale = oldMass / newMass;
    chain.forEach((joint) => {
      row[joint] = prox[vertex][joint] * scale;
    });
    const total = row.reduce((sum, value) => sum + value, 0);
    if (total <= 1e-12) return;
    for (let i = 0; i < row.length; i += 1) row[i] /= total;
  });
  packDenseWeights(old);
  state.followDirty = true;
  refreshWeightColors();
}

const SKIN_PRESETS = {
  lab_fast: {
    distance: "euclidean",
    ownership: "outgoing",
    seedPolicy: "largest_voronoi_component",
    weldPolicy: "coincident_agreeing_normals",
    connectionPolicy: "all_edges",
    maxIncidentalCut: 6,
    k: 4,
    falloff: "inverse_square",
    falloffSigma: 0.05,
    maxDistance: 0,
  },
  pipeline_initializer: {
    distance: "geodesic",
    ownership: "outgoing",
    seedPolicy: "largest_voronoi_component",
    weldPolicy: "coincident_agreeing_normals",
    connectionPolicy: "all_edges",
    maxIncidentalCut: 6,
    k: 4,
    falloff: "inverse_square",
    falloffSigma: 0.05,
    maxDistance: 0,
  },
  surface_ignore_narrow: {
    distance: "geodesic",
    ownership: "outgoing",
    seedPolicy: "largest_voronoi_component",
    weldPolicy: "coincident_agreeing_normals",
    connectionPolicy: "drop_narrow_incidental",
    maxIncidentalCut: 6,
    k: 4,
    falloff: "inverse_square",
    falloffSigma: 0.05,
    maxDistance: 0,
  },
};

function currentSkinRules() {
  return {
    preset: $("skinPreset").value,
    distance: $("skinDistance").value,
    ownership: $("skinOwnership").value,
    seedPolicy: $("skinSeed").value,
    weldPolicy: $("skinWeld").value,
    connectionPolicy: $("skinConnection").value,
    maxIncidentalCut: Number($("skinCut").value),
    k: Number($("skinK").value),
    falloff: $("skinFalloff").value,
    falloffSigma: Number($("skinSigma").value),
    maxDistance: Number($("skinMaxDist").value),
    excludedBones: [...$("skinExclude").selectedOptions].map((option) => option.value),
  };
}

function syncSkinRuleLabels() {
  $("skinKOut").textContent = String(Number($("skinK").value));
  $("skinSigmaOut").textContent = Number($("skinSigma").value).toFixed(2);
  $("skinMaxDistOut").textContent = Number($("skinMaxDist").value).toFixed(2);
  $("skinCutOut").textContent = String(Number($("skinCut").value));
  const geodesic = $("skinDistance").value === "geodesic";
  $("skinSeedRow").hidden = !geodesic;
  $("skinWeldRow").hidden = !geodesic;
  $("skinConnectionRow").hidden = !geodesic;
  $("skinCutRow").hidden = !geodesic || $("skinConnection").value !== "drop_narrow_incidental";
  $("skinSigmaRow").hidden = $("skinFalloff").value !== "gaussian";
}

function applySkinPreset(name) {
  const preset = SKIN_PRESETS[name];
  if (!preset) return;
  $("skinPreset").value = name;
  $("skinDistance").value = preset.distance;
  $("skinOwnership").value = preset.ownership;
  $("skinSeed").value = preset.seedPolicy;
  $("skinWeld").value = preset.weldPolicy;
  $("skinConnection").value = preset.connectionPolicy;
  $("skinCut").value = String(preset.maxIncidentalCut);
  $("skinK").value = String(preset.k);
  $("skinFalloff").value = preset.falloff;
  $("skinSigma").value = String(preset.falloffSigma);
  $("skinMaxDist").value = String(preset.maxDistance);
  syncSkinRuleLabels();
}

function setSkinProgress(percent, message) {
  const clamped = Math.max(0, Math.min(100, Number(percent) || 0));
  $("skinProgress").hidden = false;
  $("skinProgressFill").style.width = `${clamped}%`;
  $("skinProgressLabel").textContent = `${clamped}%`;
  if (message) status(message);
}

async function applySkinRules() {
  if (!state.skinned || !state.payload) throw new Error("load a unit before applying skin rules");
  const joints = restJointsInMeshSpace();
  if (joints.some((point) => !Number.isFinite(point.x + point.y + point.z))) {
    throw new Error("bind joints are not finite; cannot apply skin rules");
  }
  const bones = state.skinned.skeleton.bones;
  const rules = currentSkinRules();
  $("rewriteWeightsBtn").disabled = true;
  setSkinProgress(0, `Applying ${rules.distance} / ${rules.falloff} / k=${rules.k}…`);
  try {
    const started = await (await fetch("/api/skin", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        unit: state.payload.id || state.unit,
        vertexCount: state.skinned.geometry.attributes.position.count,
        slots: readInfluences(0).joints.length,
        joints: joints.map((point) => [point.x, point.y, point.z]),
        parents: bones.map((_bone, index) => boneParentIndex(index)),
        names: bones.map((bone) => bone.name),
        skinRules: rules,
      }),
    })).json();
    if (!started.ok || !started.jobId) throw new Error(started.error || "skin job failed to start");
    let result = started;
    while (result.status === "running") {
      setSkinProgress(result.percent ?? 0, result.message || "Computing weights…");
      await new Promise((resolve) => setTimeout(resolve, 400));
      result = await (await fetch(`/api/skin-job?id=${encodeURIComponent(started.jobId)}`)).json();
    }
    if (result.status === "error" || !result.ok) throw new Error(result.error || "skin rules failed");
    const packed = result.weightOverride;
    if (!packed?.joints || packed.joints.length !== state.skinned.geometry.attributes.position.count) {
      throw new Error("skin rule result vertex count does not match the loaded mesh");
    }
    packed.joints.forEach((row, vertex) => {
      writeInfluences(vertex, row, packedRenormalize(packed.weights[vertex]));
    });
    state.weightRewriteFromBind = true;
    state.skinRules = result.rules;
    $("shading").value = "weights";
    applyShading();
    refreshWeightColors();
    setSkinProgress(100, `Applied skin rules to ${packed.joints.length} vertices. Old paint is gone.`);
  } finally {
    $("rewriteWeightsBtn").disabled = false;
  }
}

function affectedChain(index) {
  const chain = new Set([index, ...descendantIndices(index)]);
  const parent = boneParentIndex(index);
  if (parent >= 0) chain.add(parent);
  return Array.from(chain);
}

function commitBoneLength(newScale, { follow = false } = {}) {
  const name = state.selectedBone;
  const index = boneIndex(name);
  if (index < 0) return;
  if (state.bindLocalPos[index].length() <= 1e-6) {
    syncLengthSlider();
    status(`${name} has no bind offset to lengthen.`);
    return;
  }
  const previous = lengthScale(name);
  const ratio = newScale / previous;
  state.boneLengthScale[name] = newScale;
  if ($("lengthChildren").checked) {
    descendantIndices(index).forEach((child) => {
      const childName = state.skinned.skeleton.bones[child].name;
      state.boneLengthScale[childName] = lengthScale(childName) * ratio;
    });
  }
  prepareBindPositions();
  if (state.mixer) state.mixer.update(0);
  applyBoneLengthLocals();
  recomputeBindInverses();
  if (follow && $("weightsFollow").checked) followWeightsForChain(affectedChain(index));
  syncLengthSlider();
  status(`Length ${name} ×${newScale.toFixed(2)}. Rotations unchanged.`);
}

function currentWeightOverride() {
  const count = state.skinned.geometry.attributes.position.count;
  const joints = [];
  const weights = [];
  for (let vertex = 0; vertex < count; vertex += 1) {
    const packed = readInfluences(vertex);
    joints.push(Array.from(packed.joints));
    weights.push(Array.from(packed.weights));
  }
  return { joints, weights };
}

function sharedWeightsDirty() {
  return Boolean(state.skinned && (state.followDirty || state.weightRewriteFromBind || state.edits.length));
}

function applySharedWeights(packed) {
  const count = state.skinned.geometry.attributes.position.count;
  if (!packed?.joints || packed.joints.length !== count) {
    throw new Error(`shared skin has ${packed?.joints?.length || 0} vertices; this clip has ${count}`);
  }
  packed.joints.forEach((row, vertex) => {
    writeInfluences(vertex, row, packedRenormalize(packed.weights[vertex]));
  });
}

function currentBoneLengths() {
  const out = {};
  Object.entries(state.boneLengthScale).forEach(([name, scale]) => {
    if (Math.abs(scale - 1) > 1e-6) out[name] = scale;
  });
  return out;
}

function influenceLayers() {
  const geometry = state.skinned.geometry;
  const layers = [];
  if (geometry.attributes.skinIndex && geometry.attributes.skinWeight) {
    layers.push({ index: geometry.attributes.skinIndex, weight: geometry.attributes.skinWeight });
  }
  if (geometry.attributes.skinIndex1 && geometry.attributes.skinWeight1) {
    layers.push({ index: geometry.attributes.skinIndex1, weight: geometry.attributes.skinWeight1 });
  }
  if (!layers.length) throw new Error("mesh has no skinIndex/skinWeight attributes");
  return layers;
}

function readInfluences(vertex) {
  const joints = [];
  const weights = [];
  influenceLayers().forEach((layer) => {
    joints.push(layer.index.getX(vertex), layer.index.getY(vertex), layer.index.getZ(vertex), layer.index.getW(vertex));
    weights.push(layer.weight.getX(vertex), layer.weight.getY(vertex), layer.weight.getZ(vertex), layer.weight.getW(vertex));
  });
  return { joints: joints.map(Number), weights };
}

function writeInfluences(vertex, joints, weights) {
  const layers = influenceLayers();
  layers.forEach((layer, layerIndex) => {
    const offset = layerIndex * 4;
    layer.index.setXYZW(vertex, joints[offset], joints[offset + 1], joints[offset + 2], joints[offset + 3]);
    layer.weight.setXYZW(vertex, weights[offset], weights[offset + 1], weights[offset + 2], weights[offset + 3]);
    layer.index.needsUpdate = true;
    layer.weight.needsUpdate = true;
  });
}

function packedRenormalize(weights) {
  const total = weights.reduce((sum, value) => sum + Math.max(value, 0), 0);
  if (total <= 1e-12) throw new Error("vertex has no remaining bone influence after edit");
  return weights.map((value) => Math.max(value, 0) / total);
}

function packedSet(joints, weights, boneIdx, value) {
  const nextJoints = joints.slice();
  const nextWeights = weights.slice();
  const slots = [];
  nextJoints.forEach((joint, slot) => {
    if (joint === boneIdx) slots.push(slot);
  });
  if (value <= 1e-8) {
    slots.forEach((slot) => {
      nextWeights[slot] = 0;
    });
    return { joints: nextJoints, weights: packedRenormalize(nextWeights) };
  }
  if (slots.length) nextWeights[slots[0]] = value;
  else {
    let weakest = 0;
    for (let i = 1; i < nextWeights.length; i += 1) {
      if (nextWeights[i] < nextWeights[weakest]) weakest = i;
    }
    nextJoints[weakest] = boneIdx;
    nextWeights[weakest] = value;
  }
  return { joints: nextJoints, weights: packedRenormalize(nextWeights) };
}

function influenceOf(vertex, boneIdx) {
  const packed = readInfluences(vertex);
  let total = 0;
  packed.joints.forEach((joint, slot) => {
    if (joint === boneIdx) total += packed.weights[slot];
  });
  return total;
}

function brushTarget(current, mode, strength, falloff, replaceValue) {
  const amount = Math.min(1, Math.max(0, strength)) * Math.min(1, Math.max(0, falloff));
  if (mode === "add") return Math.min(1, current + amount);
  if (mode === "subtract") return Math.max(0, current - amount);
  if (mode === "replace") return current * (1 - amount) + replaceValue * amount;
  return current;
}

function applyVertexWeight(vertex, boneIdx, value, boneName) {
  const packed = readInfluences(vertex);
  const next = packedSet(packed.joints, packed.weights, boneIdx, value);
  writeInfluences(vertex, next.joints, next.weights);
  state.edits.push({ op: value <= 1e-8 ? "influence_trim" : "weight_set", vertex, bone: boneName, value });
}

function buildNeighbors(geometry) {
  const count = geometry.attributes.position.count;
  const lists = Array.from({ length: count }, () => new Set());
  const index = geometry.index;
  if (!index) return lists.map(() => []);
  const array = index.array;
  for (let i = 0; i < array.length; i += 3) {
    const a = array[i];
    const b = array[i + 1];
    const c = array[i + 2];
    lists[a].add(b);
    lists[a].add(c);
    lists[b].add(a);
    lists[b].add(c);
    lists[c].add(a);
    lists[c].add(b);
  }
  return lists.map((set) => Array.from(set));
}

function buildMirrorPairs(positions) {
  const count = positions.length / 3;
  const cell = Math.max(state.meshSize / 48, 0.01);
  const grid = new Map();
  const keyOf = (x, y, z) => `${Math.round(x / cell)}:${Math.round(y / cell)}:${Math.round(z / cell)}`;
  for (let i = 0; i < count; i += 1) {
    const key = keyOf(positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2]);
    if (!grid.has(key)) grid.set(key, []);
    grid.get(key).push(i);
  }
  const pairs = new Array(count).fill(-1);
  const limit = cell * 1.5;
  for (let i = 0; i < count; i += 1) {
    const x = positions[i * 3];
    const y = positions[i * 3 + 1];
    const z = positions[i * 3 + 2];
    const tx = -x;
    let best = -1;
    let bestDist = limit * limit;
    const cx = Math.round(tx / cell);
    const cy = Math.round(y / cell);
    const cz = Math.round(z / cell);
    for (let dx = -1; dx <= 1; dx += 1) {
      for (let dy = -1; dy <= 1; dy += 1) {
        for (let dz = -1; dz <= 1; dz += 1) {
          const bucket = grid.get(`${cx + dx}:${cy + dy}:${cz + dz}`);
          if (!bucket) continue;
          bucket.forEach((other) => {
            const ox = positions[other * 3] - tx;
            const oy = positions[other * 3 + 1] - y;
            const oz = positions[other * 3 + 2] - z;
            const dist = ox * ox + oy * oy + oz * oz;
            if (dist < bestDist) {
              bestDist = dist;
              best = other;
            }
          });
        }
      }
    }
    pairs[i] = best;
  }
  return pairs;
}

function mirrorBoneName(name) {
  if (name.includes("Left")) return name.replaceAll("Left", "Right");
  if (name.includes("Right")) return name.replaceAll("Right", "Left");
  return "";
}

function heatColor(value, target) {
  const t = Math.min(1, Math.max(0, value));
  if (t < 0.5) {
    target.setRGB(0.12 + t * 0.2, 0.28 + t * 1.2, 0.85 - t * 0.4);
  } else {
    const u = (t - 0.5) * 2;
    target.setRGB(0.25 + u * 0.7, 0.85 - u * 0.7, 0.2 - u * 0.15);
  }
  return target;
}

function refreshWeightColors() {
  const skinned = state.skinned;
  if (!skinned) return;
  const shading = $("shading").value;
  if (shading === "texture") return;
  const colors = skinned.geometry.attributes.color;
  if (!colors) return;
  const count = skinned.geometry.attributes.position.count;
  const scratch = new THREE.Color();
  const selected = boneIndex(state.selectedBone);
  for (let i = 0; i < count; i += 1) {
    if (shading === "weights") {
      heatColor(selected >= 0 ? influenceOf(i, selected) : 0, scratch);
    } else {
      const packed = readInfluences(i);
      let best = 0;
      let bestW = -1;
      packed.weights.forEach((weight, slot) => {
        if (weight > bestW) {
          bestW = weight;
          best = packed.joints[slot];
        }
      });
      scratch.setHex(PALETTE[best % PALETTE.length]);
    }
    colors.setXYZ(i, scratch.r, scratch.g, scratch.b);
  }
  colors.needsUpdate = true;
}

function applyShading() {
  const skinned = state.skinned;
  if (!skinned) return;
  const shading = $("shading").value;
  if (shading === "texture") {
    skinned.material = state.originalMaterial;
  } else {
    skinned.material = state.weightMaterial;
    refreshWeightColors();
  }
  applyXray();
}

function applyXray() {
  const skinned = state.skinned;
  if (!skinned) return;
  const opacity = Number($("xray").value);
  const materials = Array.isArray(skinned.material) ? skinned.material : [skinned.material];
  materials.forEach((material) => {
    material.transparent = opacity < 0.999;
    material.opacity = opacity;
    material.depthWrite = opacity > 0.85;
    material.needsUpdate = true;
  });
}

function disposeBoneView() {
  if (!state.boneView) return;
  scene.remove(state.boneView);
  state.boneView.traverse((obj) => {
    if (obj.geometry) obj.geometry.dispose();
    if (obj.material) obj.material.dispose();
  });
  state.boneView = null;
  state.boneSpheres = [];
  state.boneSticks = [];
}

function createBoneView(skinned) {
  disposeBoneView();
  const group = new THREE.Group();
  group.name = "BoneView";
  const bones = skinned.skeleton.bones;
  if (!bones.length) throw new Error("armature has no bones to draw");
  const jointRadius = Math.max(state.meshSize * 0.018, 0.012);
  const stickRadius = jointRadius * 0.28;
  bones.forEach((bone, index) => {
    const sphere = new THREE.Mesh(
      new THREE.SphereGeometry(jointRadius, 12, 10),
      new THREE.MeshBasicMaterial({ color: 0x7dd3fc, depthTest: false, depthWrite: false }),
    );
    sphere.renderOrder = 20;
    sphere.userData.boneIndex = index;
    sphere.userData.boneName = bone.name;
    group.add(sphere);
    state.boneSpheres.push(sphere);
    if (bone.parent && bones.includes(bone.parent)) {
      const stick = new THREE.Mesh(
        new THREE.CylinderGeometry(stickRadius, stickRadius, 1, 8),
        new THREE.MeshBasicMaterial({ color: 0x38bdf8, depthTest: false, depthWrite: false }),
      );
      stick.renderOrder = 19;
      stick.userData.parentName = bone.parent.name;
      stick.userData.childName = bone.name;
      group.add(stick);
      state.boneSticks.push(stick);
    }
  });
  const cursor = new THREE.Mesh(
    new THREE.SphereGeometry(1, 16, 12),
    new THREE.MeshBasicMaterial({ color: 0xfacc15, transparent: true, opacity: 0.28, depthTest: false }),
  );
  cursor.visible = false;
  cursor.renderOrder = 21;
  group.add(cursor);
  state.brushCursor = cursor;
  scene.add(group);
  state.boneView = group;
}

function updateBoneView() {
  if (!state.skinned || !state.boneView) return;
  const bones = state.skinned.skeleton.bones;
  const selected = state.selectedBone;
  const show = $("showBones").checked;
  state.boneView.visible = show;
  const positions = new Map();
  bones.forEach((bone) => {
    positions.set(bone.name, new THREE.Vector3().setFromMatrixPosition(displayBoneMatrix(bone)));
  });
  state.boneSpheres.forEach((sphere) => {
    const pos = positions.get(sphere.userData.boneName);
    if (pos) sphere.position.copy(pos);
    const active = sphere.userData.boneName === selected;
    sphere.material.color.setHex(active ? 0xf59e0b : 0x7dd3fc);
    sphere.scale.setScalar(active ? 1.35 : 1);
  });
  state.boneSticks.forEach((stick) => {
    const a = positions.get(stick.userData.parentName);
    const b = positions.get(stick.userData.childName);
    if (!a || !b) return;
    const dir = b.clone().sub(a);
    const length = dir.length();
    if (length <= 1e-6) {
      stick.visible = false;
      return;
    }
    stick.visible = show;
    stick.position.copy(a).add(b).multiplyScalar(0.5);
    stick.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.normalize());
    stick.scale.set(1, length, 1);
    const active = stick.userData.childName === selected || stick.userData.parentName === selected;
    stick.material.color.setHex(active ? 0xf59e0b : 0x38bdf8);
  });
  updateBoneLabels(positions);
}

function updateBoneLabels(positions) {
  const layer = $("boneLabels");
  layer.innerHTML = "";
  if (!$("labelBones").checked || !state.skinned) return;
  const rect = viewport.getBoundingClientRect();
  state.skinned.skeleton.bones.forEach((bone) => {
    if (!$("labelBones").checked && bone.name !== state.selectedBone) return;
    const pos = positions.get(bone.name);
    if (!pos) return;
    const projected = pos.clone().project(camera);
    if (projected.z < -1 || projected.z > 1) return;
    const label = document.createElement("div");
    label.className = "bone-label";
    label.textContent = bone.name.replace("mixamorig:", "");
    label.style.left = `${(projected.x * 0.5 + 0.5) * rect.width}px`;
    label.style.top = `${(-projected.y * 0.5 + 0.5) * rect.height}px`;
    layer.appendChild(label);
  });
}

function setPointerFromEvent(event) {
  const rect = renderer.domElement.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
}

function closestVertex(intersect) {
  const position = state.skinned.geometry.attributes.position;
  const face = intersect.face;
  const candidates = [face.a, face.b, face.c];
  let best = candidates[0];
  let bestDist = Infinity;
  const world = new THREE.Vector3();
  candidates.forEach((index) => {
    world.fromBufferAttribute(position, index);
    state.skinned.localToWorld(world);
    const dist = world.distanceTo(intersect.point);
    if (dist < bestDist) {
      bestDist = dist;
      best = index;
    }
  });
  return best;
}

function verticesInBrush(center, radius) {
  const positions = state.skinned.geometry.attributes.position;
  const found = [];
  const world = new THREE.Vector3();
  for (let i = 0; i < positions.count; i += 1) {
    world.fromBufferAttribute(positions, i);
    state.skinned.localToWorld(world);
    const dist = world.distanceTo(center);
    if (dist <= radius) found.push({ vertex: i, falloff: 1 - dist / radius });
  }
  return found;
}

function paintAt(intersect) {
  const mode = document.querySelector("input[name=brush]:checked")?.value || "add";
  const strength = Number($("brushStrength").value);
  const radius = Number($("brushRadius").value) * state.meshSize;
  const replaceValue = Number($("paintValue").value);
  const boneName = state.selectedBone;
  const boneIdx = boneIndex(boneName);
  if (boneIdx < 0) throw new Error("select a bone before painting");
  const hits = verticesInBrush(intersect.point, radius);
  if (!hits.length) hits.push({ vertex: closestVertex(intersect), falloff: 1 });
  hits.forEach((hit) => {
    if (mode === "smooth") {
      const neighborWeights = (state.neighbors[hit.vertex] || []).map((other) => influenceOf(other, boneIdx));
      const mean = neighborWeights.length
        ? neighborWeights.reduce((sum, value) => sum + value, 0) / neighborWeights.length
        : influenceOf(hit.vertex, boneIdx);
      const next = influenceOf(hit.vertex, boneIdx) * (1 - strength * hit.falloff) + mean * strength * hit.falloff;
      applyVertexWeight(hit.vertex, boneIdx, next, boneName);
    } else {
      const next = brushTarget(influenceOf(hit.vertex, boneIdx), mode, strength, hit.falloff, replaceValue);
      applyVertexWeight(hit.vertex, boneIdx, next, boneName);
    }
    if ($("mirrorPaint").checked) {
      const otherName = mirrorBoneName(boneName);
      const otherVertex = state.mirrorOf[hit.vertex];
      const otherBone = boneIndex(otherName);
      if (otherName && otherVertex >= 0 && otherBone >= 0) {
        const packed = readInfluences(otherVertex);
        const current = influenceOf(otherVertex, otherBone);
        const next = mode === "smooth" ? current : brushTarget(current, mode, strength, hit.falloff, replaceValue);
        const written = packedSet(packed.joints, packed.weights, otherBone, next);
        writeInfluences(otherVertex, written.joints, written.weights);
        state.edits.push({ op: "weight_set", vertex: otherVertex, bone: otherName, value: next });
      }
    }
  });
  refreshWeightColors();
  status(`Painted ${hits.length} vertices on ${boneName}.`);
}

function showInfluences(vertex) {
  const packed = readInfluences(vertex);
  const bones = state.skinned.skeleton.bones;
  const box = $("influenceList");
  box.innerHTML = "";
  packed.joints.forEach((joint, slot) => {
    if (packed.weights[slot] <= 1e-6) return;
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = `${bones[joint].name}  ${packed.weights[slot].toFixed(3)}`;
    button.addEventListener("click", () => {
      applyVertexWeight(vertex, joint, 0, bones[joint].name);
      showInfluences(vertex);
      refreshWeightColors();
      status(`Trimmed ${bones[joint].name} from vertex ${vertex}.`);
    });
    box.appendChild(button);
  });
}

function pickBone(event) {
  if (!state.boneView || !$("showBones").checked) return null;
  setPointerFromEvent(event);
  const hits = raycaster.intersectObjects(state.boneSpheres, false);
  return hits.length ? hits[0].object : null;
}

function updateBrushCursor(event) {
  if (!state.brushCursor || !state.skinned) return;
  if (state.mode !== "paint") {
    state.brushCursor.visible = false;
    return;
  }
  setPointerFromEvent(event);
  const hits = raycaster.intersectObject(state.skinned, false);
  if (!hits.length) {
    state.brushCursor.visible = false;
    return;
  }
  state.brushCursor.visible = true;
  state.brushCursor.position.copy(hits[0].point);
  const radius = Number($("brushRadius").value) * state.meshSize;
  state.brushCursor.scale.setScalar(radius);
}

function onPointerDown(event) {
  if (!state.skinned) return;
  if (event.altKey) return;
  const boneHit = pickBone(event);
  if (boneHit) {
    setSelectedBone(boneHit.userData.boneName);
    status(`Selected ${boneHit.userData.boneName}.`);
    if (state.mode !== "shift") return;
  }
  setPointerFromEvent(event);
  const hits = raycaster.intersectObject(state.skinned, false);
  if (!hits.length) return;
  if (state.mode === "shift") {
    const name = $("seatBone").value;
    const index = boneIndex(name);
    if (index < 0) return;
    const rest = new THREE.Vector3().setFromMatrixPosition(state.bindWorlds[index]);
    const d = currentDelta();
    const R = new THREE.Matrix4().makeRotationFromEuler(
      new THREE.Euler(
        THREE.MathUtils.degToRad(d.pitchDeg),
        THREE.MathUtils.degToRad(d.yawDeg),
        THREE.MathUtils.degToRad(d.rollDeg),
        "YXZ",
      ),
    );
    rest.applyMatrix4(R).multiplyScalar(d.scale);
    $("tx").value = (hits[0].point.x - rest.x).toFixed(3);
    $("ty").value = (hits[0].point.y - rest.y).toFixed(3);
    $("tz").value = (hits[0].point.z - rest.z).toFixed(3);
    syncDeltaLabels();
    status(`Seated ${name} at the click.`);
    return;
  }
  if (state.mode === "paint") {
    state.painting = true;
    controls.enabled = false;
    paintAt(hits[0]);
    return;
  }
  if (state.mode === "trim") {
    const vertex = closestVertex(hits[0]);
    state.pickedVertex = vertex;
    showInfluences(vertex);
    $("pickInfo").textContent = `vertex ${vertex}`;
  }
}

function onPointerMove(event) {
  updateBrushCursor(event);
  if (!state.painting || state.mode !== "paint") return;
  setPointerFromEvent(event);
  const hits = raycaster.intersectObject(state.skinned, false);
  if (hits.length) paintAt(hits[0]);
}

function onPointerUp() {
  state.painting = false;
  syncOrbitEnabled();
}

function syncOrbitEnabled() {
  controls.enabled = state.mode === "orbit" || Boolean(state._altOrbit);
}

function goToFrame(frame) {
  state.frame = frame;
  $("frameSlider").value = String(frame);
  $("frameLabel").textContent = `f${String(frame).padStart(2, "0")}`;
  if (!state.action || !state.clip) return;
  const time = Math.min(frame / state.fps, Math.max(state.clip.duration - 1e-4, 0));
  state.action.paused = true;
  state.action.time = time;
  prepareBindPositions();
  state.mixer.update(0);
  applyBoneLengthLocals();
  state.skinned.updateMatrixWorld(true);
}

function resize() {
  const width = viewport.clientWidth;
  const height = viewport.clientHeight;
  if (width < 2 || height < 2) return;
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  renderer.setSize(width, height, false);
}

function clearRoot() {
  while (root.children.length) root.remove(root.children[0]);
  disposeBoneView();
  $("boneLabels").innerHTML = "";
  state.mixer = null;
  state.action = null;
  state.clip = null;
  state.skinned = null;
  state.originalMaterial = null;
  state.weightMaterial = null;
}

function pickSkinned(gltf) {
  const meshes = [];
  gltf.scene.traverse((obj) => {
    if (obj.isSkinnedMesh) meshes.push(obj);
  });
  if (!meshes.length) throw new Error("clip has no skinned mesh");
  meshes.sort((a, b) => (b.skeleton?.bones.length || 0) - (a.skeleton?.bones.length || 0));
  return meshes[0];
}

async function loadClip(unit, clipName) {
  status(`Loading ${unit} ${clipName}…`);
  const keepWeights = sharedWeightsDirty() ? currentWeightOverride() : null;
  const keepEdits = keepWeights ? state.edits.slice() : [];
  clearRoot();
  const gltf = await loader.loadAsync(state.payload.clips[clipName]);
  root.add(gltf.scene);
  const skinned = pickSkinned(gltf);
  skinned.frustumCulled = false;
  const materials = Array.isArray(skinned.material) ? skinned.material : [skinned.material];
  materials.forEach((material) => {
    material.side = THREE.DoubleSide;
    material.metalness = 0;
    material.needsUpdate = true;
  });
  state.skinned = skinned;
  state.originalMaterial = skinned.material;
  const color = new Float32Array(skinned.geometry.attributes.position.count * 3);
  skinned.geometry.setAttribute("color", new THREE.BufferAttribute(color, 3));
  state.weightMaterial = new THREE.MeshLambertMaterial({
    vertexColors: true,
    side: THREE.DoubleSide,
    skinning: true,
  });
  state.originalInverses = skinned.skeleton.boneInverses.map((matrix) => matrix.clone());
  root.updateMatrixWorld(true);
  state.bindLocalPos = skinned.skeleton.bones.map((bone) => bone.position.clone());
  state.bindLocalQuat = skinned.skeleton.bones.map((bone) => bone.quaternion.clone());
  state.bindWorlds = skinned.skeleton.bones.map((bone) => bone.matrixWorld.clone());
  frameCamera(skinned);
  state.neighbors = buildNeighbors(skinned.geometry);
  state.restPositions = Array.from(skinned.geometry.attributes.position.array);
  state.mirrorOf = buildMirrorPairs(state.restPositions);
  createBoneView(skinned);
  window.__cleanupDebug = { camera, scene, state, skinned };
  if (gltf.animations.length) {
    state.mixer = new THREE.AnimationMixer(gltf.scene);
    state.clip = gltf.animations[0];
    state.action = state.mixer.clipAction(state.clip);
    state.action.play();
    state.action.paused = true;
    state.frameCount = Math.max(1, Math.round(state.clip.duration * state.fps));
    $("frameSlider").max = String(state.frameCount);
    goToFrame(0);
  } else {
    state.frameCount = 1;
    $("frameSlider").max = "0";
  }
  fillBoneSelects(boneNames());
  state.clipName = clipName;
  state.edits = keepEdits;
  if (Object.values(state.boneLengthScale).some((scale) => Math.abs(scale - 1) > 1e-6)) {
    applyBoneLengthLocals();
    recomputeBindInverses();
  }
  applyBindDelta();
  if (keepWeights) applySharedWeights(keepWeights);
  applyShading();
  syncLengthSlider();
  if (keepWeights) {
    status(`${unit} ${clipName} ready. Same bind skin as the other clips; this file is motion only.`);
  } else {
    status(`${unit} ${clipName} ready. Bones are the cyan joints; selected is gold.`);
  }
}

async function loadUnit(unit) {
  const payload = await (await fetch(`/api/unit?id=${encodeURIComponent(unit)}`)).json();
  if (payload.error) throw new Error(payload.error);
  state.unit = unit;
  state.payload = payload;
  state.boneLengthScale = {};
  state.followDirty = false;
  state.weightRewriteFromBind = false;
  state.skinRules = null;
  state.fps = payload.fps || 12;
  $("meta").textContent = `${payload.label || unit} — compare left sprite to 3D mesh. Cleanup preview only, not ship.`;
  $("spriteGif").src = payload.gifUrl || "";
  $("overlayImg").src = payload.overlayUrl || "";
  $("clipSelect").innerHTML = "";
  Object.keys(payload.clips).forEach((name) => {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    $("clipSelect").appendChild(option);
  });
  $("clipSelect").value = payload.defaultClip;
  await loadClip(unit, payload.defaultClip);
}

async function saveCandidate() {
  if (!state.payload) return;
  const body = {
    unit: state.payload.unit || state.unit,
    source: {
      bindGlb: state.payload.bindPath,
      bindSha256: state.payload.bindSha256,
      registration: state.payload.registrationPath,
      registrationSha256: state.payload.registrationSha256,
      clip: state.clipName,
    },
    skeletonDelta: currentDelta(),
    boneLengths: currentBoneLengths(),
    weightFollowJoints: Boolean(state.followDirty),
    weightRewriteFromBind: Boolean(state.weightRewriteFromBind),
    weightOverride: (state.followDirty || state.weightRewriteFromBind) ? currentWeightOverride() : null,
    skinRules: currentSkinRules(),
    edits: state.edits,
    notes: "human cleanup preview",
  };
  const response = await fetch("/api/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const result = await response.json();
  if (!result.ok) {
    status(result.error || "save failed");
    return;
  }
  status(`Saved ${result.path}. Generated-artifact only; scheduler will not consume this.`);
}

function tick() {
  requestAnimationFrame(tick);
  resize();
  if (state.playing && state.mixer && state.clip) {
    prepareBindPositions();
    state.mixer.update(state.clock.getDelta());
    applyBoneLengthLocals();
    const frame = Math.min(state.frameCount, Math.round(state.action.time * state.fps));
    $("frameSlider").value = String(frame);
    $("frameLabel").textContent = `f${String(frame).padStart(2, "0")}`;
  }
  if (state.skinned) {
    root.updateMatrixWorld(true);
    try {
      applyBindDelta();
    } catch (error) {
      status(error.message);
    }
    updateBoneView();
    state.skinned.visible = $("showMesh").checked;
  }
  renderer.render(scene, camera);
}

async function boot() {
  const params = new URLSearchParams(window.location.search);
  const requested = params.get("unit") || "h3_amalek";
  const units = await (await fetch("/api/units")).json();
  $("unitSelect").innerHTML = "";
  (units.units || []).forEach((row) => {
    const option = document.createElement("option");
    option.value = row.id || row.unit;
    option.textContent = `${row.label || row.unit} (${row.clips.length} clips)`;
    $("unitSelect").appendChild(option);
  });
  $("unitSelect").value = requested;
  $("unitSelect").addEventListener("change", () => loadUnit($("unitSelect").value).catch((error) => status(error.message)));
  $("clipSelect").addEventListener("change", () => loadClip(state.unit, $("clipSelect").value).catch((error) => status(error.message)));
  ["yaw", "pitch", "roll", "scale", "tx", "ty", "tz"].forEach((id) => $(id).addEventListener("input", syncDeltaLabels));
  document.querySelectorAll("input[name=mode]").forEach((input) => {
    input.addEventListener("change", () => setMode(input.value));
  });
  $("paintBone").addEventListener("change", () => setSelectedBone($("paintBone").value));
  $("seatBone").addEventListener("change", () => setSelectedBone($("seatBone").value));
  $("lengthBone").addEventListener("change", () => setSelectedBone($("lengthBone").value));
  $("boneLength").addEventListener("input", () => {
    $("boneLengthOut").textContent = Number($("boneLength").value).toFixed(2);
    commitBoneLength(Number($("boneLength").value), { follow: false });
  });
  $("boneLength").addEventListener("change", () => {
    commitBoneLength(Number($("boneLength").value), { follow: true });
  });
  $("weightsFollow").addEventListener("change", () => {
    const index = boneIndex(state.selectedBone);
    if ($("weightsFollow").checked && index >= 0) followWeightsForChain(affectedChain(index));
  });
  $("rewriteWeightsBtn").addEventListener("click", () => {
    applySkinRules().catch((error) => status(error.message));
  });
  $("skinPreset").addEventListener("change", () => applySkinPreset($("skinPreset").value));
  ["skinDistance", "skinOwnership", "skinSeed", "skinWeld", "skinConnection", "skinFalloff", "skinExclude"].forEach((id) => {
    $(id).addEventListener("change", () => {
      $("skinPreset").value = "custom";
      if (id === "skinDistance" && $("skinDistance").value === "geodesic") {
        $("skinConnection").value = "drop_narrow_incidental";
      }
      syncSkinRuleLabels();
    });
  });
  ["skinK", "skinSigma", "skinMaxDist", "skinCut"].forEach((id) => {
    $(id).addEventListener("input", () => {
      $("skinPreset").value = "custom";
      syncSkinRuleLabels();
    });
  });
  $("resetLengthsBtn").addEventListener("click", () => {
    state.boneLengthScale = {};
    prepareBindPositions();
    if (state.mixer) state.mixer.update(0);
    applyBoneLengthLocals();
    recomputeBindInverses();
    syncLengthSlider();
    status("All bone lengths reset to the bind offsets. Followed weights are not undone.");
  });
  $("shading").addEventListener("change", applyShading);
  $("xray").addEventListener("input", applyXray);
  $("brushStrength").addEventListener("input", () => {
    $("brushStrengthOut").textContent = Number($("brushStrength").value).toFixed(2);
  });
  $("brushRadius").addEventListener("input", () => {
    $("brushRadiusOut").textContent = Number($("brushRadius").value).toFixed(2);
  });
  $("paintValue").addEventListener("input", () => {
    $("paintValueOut").textContent = Number($("paintValue").value).toFixed(2);
  });
  $("resetDeltaBtn").addEventListener("click", () => {
    ["yaw", "pitch", "roll", "tx", "ty", "tz"].forEach((id) => {
      $(id).value = "0";
    });
    $("scale").value = "1";
    syncDeltaLabels();
  });
  $("toRestBtn").addEventListener("click", () => {
    state.playing = false;
    $("playBtn").textContent = "Play";
    goToFrame(0);
  });
  $("playBtn").addEventListener("click", () => {
    state.playing = !state.playing;
    $("playBtn").textContent = state.playing ? "Pause" : "Play";
    if (state.action) state.action.paused = !state.playing;
    if (state.playing) state.clock.getDelta();
  });
  $("frameSlider").addEventListener("input", () => {
    state.playing = false;
    $("playBtn").textContent = "Play";
    goToFrame(Number($("frameSlider").value));
  });
  $("saveBtn").addEventListener("click", () => saveCandidate().catch((error) => status(error.message)));
  renderer.domElement.addEventListener("pointerdown", onPointerDown);
  renderer.domElement.addEventListener("pointermove", onPointerMove);
  window.addEventListener("pointerup", onPointerUp);
  window.addEventListener("keydown", (event) => {
    if (event.key === "Alt") {
      state._altOrbit = true;
      controls.enabled = true;
    }
  });
  window.addEventListener("keyup", (event) => {
    if (event.key === "Alt") {
      state._altOrbit = false;
      syncOrbitEnabled();
    }
  });
  setMode("orbit");
  syncDeltaLabels();
  applySkinPreset("lab_fast");
  await loadUnit(requested);
}

tick();
boot().catch((error) => status(error.message));
