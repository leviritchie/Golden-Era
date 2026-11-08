const state = {
  manifests: [],
  templates: [],
  faction: null,
  mode: "units",
  unit: null,
  hero: null,
  law: null,
  overrides: null,
  heroOverrides: null,
  lawOverrides: null,
  currentTab: "logic",
  currentData: null,
  currentHeroData: null,
  currentLawData: null,
  effects: [],
  effectsSource: "",
  icons: [],
  iconRoots: [],
  iconWarnings: [],
  heroSkills: [],
  heroSpecializations: [],
  specializationBonusTemplates: [],
  focusedField: null,
  iconTarget: null,
  effectTarget: null,
  skillTarget: null,
  specializationTarget: null
};

const els = {
  factionSelect: document.querySelector("#factionSelect"),
  unitModeBtn: document.querySelector("#unitModeBtn"),
  heroModeBtn: document.querySelector("#heroModeBtn"),
  lawModeBtn: document.querySelector("#lawModeBtn"),
  unitSearch: document.querySelector("#unitSearch"),
  unitList: document.querySelector("#unitList"),
  unitTitle: document.querySelector("#unitTitle"),
  unitMeta: document.querySelector("#unitMeta"),
  sourceMeta: document.querySelector("#sourceMeta"),
  currentSpecials: document.querySelector("#currentSpecials"),
  heroPanel: document.querySelector("#heroPanel"),
  heroEditor: document.querySelector("#heroEditor"),
  lawPanel: document.querySelector("#lawPanel"),
  lawEditor: document.querySelector("#lawEditor"),
  abilityList: document.querySelector("#abilityList"),
  addAbilityBtn: document.querySelector("#addAbilityBtn"),
  effectsBtn: document.querySelector("#effectsBtn"),
  iconsBtn: document.querySelector("#iconsBtn"),
  saveBtn: document.querySelector("#saveBtn"),
  replaceAbilities: document.querySelector("#replaceAbilities"),
  replacePassives: document.querySelector("#replacePassives"),
  currentData: document.querySelector("#currentData"),
  abilityDialog: document.querySelector("#abilityDialog"),
  templateGrid: document.querySelector("#templateGrid"),
  cardTemplate: document.querySelector("#abilityCardTemplate"),
  effectsDialog: document.querySelector("#effectsDialog"),
  effectsSource: document.querySelector("#effectsSource"),
  effectSearch: document.querySelector("#effectSearch"),
  effectKind: document.querySelector("#effectKind"),
  effectList: document.querySelector("#effectList"),
  iconsDialog: document.querySelector("#iconsDialog"),
  iconsSource: document.querySelector("#iconsSource"),
  iconSearch: document.querySelector("#iconSearch"),
  iconGroup: document.querySelector("#iconGroup"),
  iconGrid: document.querySelector("#iconGrid"),
  skillDialog: document.querySelector("#skillDialog"),
  skillSearch: document.querySelector("#skillSearch"),
  skillList: document.querySelector("#skillList"),
  specializationDialog: document.querySelector("#specializationDialog"),
  specializationSearch: document.querySelector("#specializationSearch"),
  specializationList: document.querySelector("#specializationList")
};

function sidTemplate(value) {
  if (!state.unit) return value;
  return String(value).replaceAll("{unitSid}", state.unit.sid);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  }[char]));
}

const RESOURCE_OPTIONS = ["gold", "wood", "ore", "mercury", "crystals", "gemstones", "dust"];
const LAW_BONUS_TYPE_OPTIONS = [
  ["sideRes", "Daily resource income"],
  ["sideOneTimeAddRes", "One-time resource grant"],
  ["sideObjectViewRadius", "Object view radius"],
  ["sideStat", "Side stat"],
  ["heroStat", "Hero stat"],
  ["heroStatBattle", "Battle hero stat"],
  ["unitStat", "Unit stat"],
  ["cityUnitsIncrement", "Weekly unit growth"],
  ["unitHiringDiscount", "Unit hiring discount"],
  ["constructionDailyLimit", "Construction daily limit"],
  ["constructionDiscount", "Construction discount"],
  ["astrologyExp", "Astrology points"],
  ["battleSubskillBonus", "Battle subskill bonus"]
];
const HERO_STAT_OPTIONS = [
  "viewRadius", "offence", "defence", "spellPower", "intelligence", "moral", "movementBonus",
  "startEnergyLevelsBonus", "sideExpPerBonus", "diplomacyEfficiencyPerBonus", "maxEnergyLevelsBonus",
  "magicSchoolSet"
];
const UNIT_STAT_OPTIONS = [
  "damageMin", "damageMax", "hp", "offence", "defence", "initiative", "speed", "outAllDmgMod",
  "inAllDmgMod", "additionalActionChanceModifier", "inComingBuffDuration", "modifierSet"
];
const DAMAGE_MODIFIER_OPTIONS = ["outDmgMods", "inDmgMods"];
const DAMAGE_KIND_OPTIONS = ["shoot_attack", "melee_attack", "counter_attack", "magic_damage", "basic_attack", "overTime_effect"];
const RECEIVER_ALLEGIANCE_OPTIONS = ["", "ally", "enemy"];
const BIOME_OPTIONS = ["", "native"];
const SIDE_STAT_OPTIONS = [
  ["resPercentIncrementSet", "Resource income percent increase"],
  ["disableMarketsExtraCharge", "Disable market extra charge"]
];

function fillOptions(select, options, current = "") {
  select.innerHTML = "";
  const normalized = options.map(item => Array.isArray(item) ? item : [item, item]);
  if (current && !normalized.some(([value]) => value === current)) {
    normalized.unshift([current, current]);
  }
  for (const [value, label] of normalized) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    select.append(option);
  }
  select.value = current;
}

function lawUnitOptions(current = "") {
  const units = currentFaction()?.units || [];
  const options = units.map(unit => [unit.sid, `${unit.name || unit.sid} (${unit.sid})`]);
  if (current && !options.some(([value]) => value === current)) options.unshift([current, current]);
  return options;
}

function factionOptions(current = "") {
  const options = [["", "No faction filter"], ...state.manifests.map(manifest => [manifest.factionSid, `${manifest.displayName || manifest.factionSid} (${manifest.factionSid})`])];
  if (current && !options.some(([value]) => value === current)) options.unshift([current, current]);
  return options;
}

function labelForOption(options, value) {
  const found = options.find(item => (Array.isArray(item) ? item[0] : item) === value);
  if (!found) return value || "";
  return Array.isArray(found) ? found[1] : found;
}

function findIcon(key) {
  if (!key) return null;
  return state.icons.find(icon => icon.key === key) || state.icons.find(icon => icon.label === key) || null;
}

function iconPreviewHtml(key) {
  const icon = findIcon(key);
  if (icon?.url) {
    return `<img class="selected-icon-preview" src="${escapeHtml(icon.url)}" alt="">`;
  }
  return `<span class="selected-icon-preview selected-icon-placeholder">${escapeHtml(key ? key.slice(0, 2).toUpperCase() : "?")}</span>`;
}

function effectiveLawIconKey(law) {
  if (!law) return "";
  const entry = state.lawOverrides?.lawOverrides?.[law.id];
  if (entry?.enabled === false) return law.icon || "";
  return entry?.iconKey || law.icon || "";
}

function lawUnlockLabel(law) {
  const value = law?.tree?.unlockPoints;
  if (value === undefined || value === null || value === "") return "Unlock tier unknown";
  return `Unlocks after ${value} spent`;
}

function lawUnlockBadgeLabel(law) {
  const value = law?.tree?.unlockPoints;
  if (value === undefined || value === null || value === "") return "? pts";
  return `${value} pts`;
}

function lawTreePositionLabel(law) {
  const tree = law?.tree || {};
  const parts = [];
  if (tree.lineIndex !== undefined && tree.lineIndex !== null) parts.push(`row ${tree.lineIndex}`);
  if (tree.groupIndex !== undefined && tree.groupIndex !== null) parts.push(`group ${tree.groupIndex}`);
  if (tree.slotIndex !== undefined && tree.slotIndex !== null) parts.push(`slot ${tree.slotIndex}`);
  return parts.join(" / ");
}

function splitListText(value) {
  return String(value || "")
    .split(/[\n,]+/)
    .map(item => item.trim())
    .filter(Boolean);
}

function numericInputValue(value) {
  if (typeof value === "number") return value;
  const text = String(value ?? "");
  return text;
}

function valueFromNumericInput(input) {
  const text = input.value.trim();
  if (text === "") return "";
  const number = Number(text);
  return Number.isFinite(number) ? number : text;
}

function resolveDefaultFields(defaults) {
  const resolved = {};
  for (const [key, value] of Object.entries(defaults || {})) {
    resolved[key] = typeof value === "string" ? sidTemplate(value) : value;
  }
  return resolved;
}

const HIDDEN_FIELDS = new Set(["nameToken", "descriptionToken", "mechanicsDebt", "spellSid", "sourceUnitSid", "sourceSlotKind", "sourceSlotIndex"]);
const FIELD_LABELS = {
  displayName: "Name",
  description: "Description",
  abilityType: "Ability type",
  animationIndex: "Animation",
  turnBehavior: "Turn behavior",
  energyLevel: "Focus cost",
  cooldown: "Cooldown",
  rank: "Rank",
  buffSid: "Effect",
  buffDuration: "Effect duration",
  iconKey: "Icon",
  projectile: "Projectile",
  projectileSpeed: "Projectile speed",
  trajectory: "Projectile path",
  statDmgMult: "Damage multiplier",
  healPercent: "Heal percent",
  charges: "Charges",
  spellEffectKey: "Spell effect",
  spellTier: "Spell tier",
  spellEffectLevel: "Spell level",
  effectiveSpellPower: "Effective spell power",
  effectDuration: "Effect duration",
  unitSpecialKey: "Donor special"
};

const SELECT_OPTIONS = {
  abilityType: [
    ["Ability_type_special", "Special"],
    ["Ability_type_attack_mod", "Attack modifier"],
    ["Ability_type_active", "Active ability"],
    ["Ability_type_passive", "Passive ability"],
    ["Ability_type_attack", "Attack"],
    ["Ability_type_buff", "Positive effect"],
    ["Ability_type_debuff", "Negative effect"],
    ["Ability_type_movement", "Movement"],
    ["Ability_type_summon", "Summon"]
  ],
  animationIndex: [[0, "Attack"], [1, "Alternate attack"], [2, "Cast"], [3, "Special 1"], [4, "Special 2"], [5, "Special 3"]],
  turnBehavior: [["ends", "Ends turn"], ["free", "Does not end turn"]],
  energyLevel: [[0, "0 Focus"], [1, "1 Focus"], [2, "2 Focus"], [3, "3 Focus"], [4, "4 Focus"], [5, "5 Focus"]],
  cooldown: [[-1, "Native no cooldown"], [0, "No cooldown"], [1, "1 round"], [2, "2 rounds"], [3, "3 rounds"], [4, "4 rounds"], [5, "5 rounds"]],
  rank: [[1, "Rank 1"], [2, "Rank 2"], [3, "Rank 3"], [4, "Rank 4"], [5, "Rank 5"]],
  buffDuration: [[1, "1 round"], [2, "2 rounds"], [3, "3 rounds"], [4, "4 rounds"], [5, "5 rounds"]],
  projectileSpeed: [[10, "Slow"], [18, "Medium"], [25, "Fast"], [35, "Very fast"], [50, "Instant-feeling"]],
  trajectory: [["linear", "Linear"], ["arc", "Arc"], ["parabolic", "Parabolic"]],
  statDmgMult: [[1, "100% damage"], [1.1, "110% damage"], [1.2, "120% damage"], [1.5, "150% damage"], [2, "200% damage"]],
  healPercent: [["0.05", "5%"], ["0.10", "10%"], ["0.15", "15%"], ["0.20", "20%"], ["0.25", "25%"]],
  charges: [[1, "1 charge"], [2, "2 charges"], [3, "3 charges"], [4, "4 charges"], [5, "5 charges"]],
  spellTier: [[1, "Tier 1"], [2, "Tier 2"], [3, "Tier 3"], [4, "Tier 4"], [5, "Tier 5"]],
  spellEffectLevel: [[1, "Level 1"], [2, "Level 2"], [3, "Level 3"], [4, "Level 4"]],
  effectiveSpellPower: [[0, "0"], [3, "3"], [6, "6"], [9, "9"], [12, "12"], [15, "15"], [20, "20"], [25, "25"], [30, "30"]],
  effectDuration: [[-1, "Permanent"], [0, "Instant"], [1, "1 round"], [2, "2 rounds"], [3, "3 rounds"], [4, "4 rounds"], [5, "5 rounds"]]
};

const EFFECT_FIELD_KINDS = {
  abilityType: ["ability-type"],
  buffSid: ["buff", "mechanic-value"],
  projectile: ["projectile"],
  spellEffectKey: ["spell-effect"],
  unitSpecialKey: ["unit-special"]
};

function fieldLabel(key) {
  return FIELD_LABELS[key] || key.replace(/([A-Z])/g, " $1").replace(/^./, char => char.toUpperCase());
}

function selectLabel(key, value) {
  const option = (SELECT_OPTIONS[key] || []).find(item => String(item[0]) === String(value));
  return option ? option[1] : String(value || "Select");
}

async function api(path, options) {
  const response = await fetch(path, options);
  const json = await response.json();
  if (!response.ok || json.error) throw new Error(json.error || response.statusText);
  return json;
}

function currentFaction() {
  return state.manifests.find(item => item.factionSid === state.faction);
}

function unitOverride() {
  if (!state.overrides || !state.unit) return null;
  const bucket = state.overrides.unitOverrides[state.unit.sid] ||= {
    abilities: [],
    existingSpecials: [],
    replaceExistingAbilities: false,
    replaceExistingPassives: false
  };
  bucket.existingSpecials ||= [];
  return bucket;
}

function heroOverride() {
  if (!state.heroOverrides || !state.hero) return null;
  const bucket = state.heroOverrides.heroOverrides[state.hero.sid] ||= {
    enabled: true,
    nameText: state.hero.name || "",
    descriptionText: "",
    mottoText: "",
    iconKey: state.hero.icon || "",
    classType: state.hero.classType || "",
    className: state.hero.className || "",
    startSquad: [],
    startSquadAlt: [],
    startSkills: [],
    specialization: {
      mode: "custom",
      sourceSpecId: "",
      nameText: "",
      descriptionText: "",
      iconKey: "",
      bonuses: []
    },
    notes: ""
  };
  bucket.startSquad ||= [];
  bucket.startSquadAlt ||= [];
  bucket.startSkills ||= [];
  bucket.specialization ||= { mode: "custom", sourceSpecId: "", nameText: "", descriptionText: "", iconKey: "", bonuses: [] };
  bucket.specialization.bonuses ||= [];
  return bucket;
}

function lawOverride() {
  if (!state.lawOverrides || !state.law) return null;
  const existing = state.lawOverrides.lawOverrides[state.law.id];
  if (existing) {
    return existing;
  }
  return {
    enabled: true,
    nameText: "",
    descriptionText: "",
    iconKey: "",
    notes: ""
  };
}

function persistLawOverride(entry) {
  if (!state.lawOverrides || !state.law || !entry) return;
  state.lawOverrides.lawOverrides[state.law.id] = entry;
}

function editableLawLevels(entry) {
  if (Array.isArray(entry.parametersPerLevel)) return entry.parametersPerLevel;
  return JSON.parse(JSON.stringify(state.law?.parametersPerLevel || []));
}

function ensureEditableLawLevels(entry, levels) {
  if (!Array.isArray(entry.parametersPerLevel)) {
    entry.parametersPerLevel = levels;
  }
  return entry.parametersPerLevel;
}

async function loadOverrides() {
  state.overrides = await api(`/api/overrides?factionSid=${encodeURIComponent(state.faction)}`);
}

async function loadHeroOverrides() {
  state.heroOverrides = await api(`/api/hero_overrides?factionSid=${encodeURIComponent(state.faction)}`);
}

async function loadLawOverrides() {
  state.lawOverrides = await api(`/api/law_overrides?factionSid=${encodeURIComponent(state.faction)}`);
}

async function loadCurrentUnitData() {
  if (!state.unit) {
    state.currentData = null;
    renderCurrentData();
    return;
  }
  state.currentData = await api(`/api/unit?factionSid=${encodeURIComponent(state.faction)}&unitSid=${encodeURIComponent(state.unit.sid)}`);
  renderCurrentData();
}

async function loadCurrentHeroData() {
  if (!state.hero) {
    state.currentHeroData = null;
    return;
  }
  state.currentHeroData = await api(`/api/hero?factionSid=${encodeURIComponent(state.faction)}&heroSid=${encodeURIComponent(state.hero.sid)}`);
}

async function loadCurrentLawData() {
  if (!state.faction) {
    state.currentLawData = null;
    return;
  }
  state.currentLawData = await api(`/api/laws?factionSid=${encodeURIComponent(state.faction)}`);
  state.law ||= state.currentLawData.laws?.[0] || null;
}

async function loadEffects() {
  const catalog = await api("/api/effects");
  state.effects = catalog.effects || [];
  state.effectsSource = catalog.coreZip || "";
}

async function loadIcons() {
  const catalog = await api("/api/icons");
  state.icons = catalog.icons || [];
  state.iconRoots = catalog.roots || [];
  state.iconWarnings = catalog.warnings || [];
}

function renderFactions() {
  els.factionSelect.innerHTML = "";
  for (const manifest of state.manifests) {
    const option = document.createElement("option");
    option.value = manifest.factionSid;
    option.textContent = manifest.displayName;
    els.factionSelect.append(option);
  }
  els.factionSelect.value = state.faction;
}

function renderUnits() {
  const manifest = currentFaction();
  const query = els.unitSearch.value.trim().toLowerCase();
  els.unitList.innerHTML = "";
  if (state.mode === "laws") {
    for (const law of state.currentLawData?.laws || []) {
      const iconKey = effectiveLawIconKey(law);
      const haystack = `${law.id} ${law.name} ${law.description} ${law.icon} ${iconKey}`.toLowerCase();
      if (query && !haystack.includes(query)) continue;
      const button = document.createElement("button");
      button.className = "unit law-list-item" + (state.law?.id === law.id ? " active" : "");
      const positionLabel = lawTreePositionLabel(law);
      button.innerHTML = `<span class="law-list-icon">${iconPreviewHtml(iconKey)}</span><span>${escapeHtml(law.name || law.id)}</span><b class="badge">${escapeHtml(lawUnlockBadgeLabel(law))}</b><small>${escapeHtml([law.id, lawUnlockLabel(law), positionLabel].filter(Boolean).join(" / "))}</small>`;
      button.addEventListener("click", () => {
        state.law = law;
        render();
      });
      els.unitList.append(button);
    }
  } else if (state.mode === "heroes") {
    for (const hero of manifest?.heroes || []) {
      const haystack = `${hero.sid} ${hero.name} ${hero.classType} ${hero.className}`.toLowerCase();
      if (query && !haystack.includes(query)) continue;
      const button = document.createElement("button");
      button.className = "unit" + (state.hero?.sid === hero.sid ? " active" : "");
      button.innerHTML = `<span>${hero.name}</span><b class="badge">${hero.classType || "hero"}</b><small>${hero.sid}</small>`;
      button.addEventListener("click", async () => {
        state.hero = hero;
        await loadCurrentHeroData();
        render();
      });
      els.unitList.append(button);
    }
  } else {
    for (const unit of manifest?.units || []) {
      const haystack = `${unit.sid} ${unit.name} ${unit.variant}`.toLowerCase();
      if (query && !haystack.includes(query)) continue;
      const button = document.createElement("button");
      button.className = "unit" + (state.unit?.sid === unit.sid ? " active" : "");
      button.innerHTML = `<span>${unit.name}</span><b class="badge">T${unit.tier ?? "?"}</b><small>${unit.sid} / ${unit.variant}</small>`;
      button.addEventListener("click", async () => {
        state.unit = unit;
        await loadCurrentUnitData();
        render();
      });
      els.unitList.append(button);
    }
  }
}

function renderUnitHeader() {
  els.unitModeBtn.classList.toggle("active", state.mode === "units");
  els.heroModeBtn.classList.toggle("active", state.mode === "heroes");
  els.lawModeBtn.classList.toggle("active", state.mode === "laws");
  const unitPanels = document.querySelectorAll(".current-specials-panel, .panel:not(.hero-panel):not(.law-panel):not(.advanced-panel)");
  els.heroPanel.classList.toggle("hidden", state.mode !== "heroes");
  els.lawPanel.classList.toggle("hidden", state.mode !== "laws");
  for (const panel of unitPanels) panel.classList.toggle("hidden", state.mode !== "units");
  if (state.mode === "laws") {
    els.addAbilityBtn.disabled = true;
    els.effectsBtn.disabled = false;
    els.iconsBtn.disabled = false;
    els.replaceAbilities.disabled = true;
    els.replacePassives.disabled = true;
    els.unitTitle.textContent = state.law?.name || "Select a law";
    els.unitMeta.textContent = state.law
      ? `${state.law.id} / law ${state.law.index} / ${lawUnlockLabel(state.law)}${lawTreePositionLabel(state.law) ? ` / ${lawTreePositionLabel(state.law)}` : ""}`
      : "";
    const warnings = state.currentLawData?.warnings || [];
    els.sourceMeta.textContent = [
      state.currentLawData?.sources?.laws ? `Laws: ${state.currentLawData.sources.laws}` : "",
      state.currentLawData?.sources?.faction ? `Tree: ${state.currentLawData.sources.faction}` : "",
      ...warnings.map(item => `Warning: ${item}`),
    ].filter(Boolean).join(" / ");
    renderLawEditor();
    return;
  }
  if (state.mode === "heroes") {
    els.addAbilityBtn.disabled = true;
    els.effectsBtn.disabled = false;
    els.iconsBtn.disabled = false;
    els.replaceAbilities.disabled = true;
    els.replacePassives.disabled = true;
    els.unitTitle.textContent = state.hero?.name || "Select a hero";
    els.unitMeta.textContent = state.hero ? `${state.hero.sid} / ${state.hero.classType || "hero"}` : "";
    els.sourceMeta.textContent = state.currentHeroData?.sources
      ? `Hero: ${state.currentHeroData.sources.hero || "missing"} / Specialization: ${state.currentHeroData.sources.specializations || "missing"}`
      : "";
    renderHeroEditor();
    return;
  }
  els.replaceAbilities.disabled = false;
  els.replacePassives.disabled = false;
  if (!state.unit) {
    els.unitTitle.textContent = "Select a unit";
    els.unitMeta.textContent = "";
    els.sourceMeta.textContent = "";
    els.addAbilityBtn.disabled = true;
    els.effectsBtn.disabled = true;
    els.iconsBtn.disabled = true;
    return;
  }
  els.addAbilityBtn.disabled = false;
  els.effectsBtn.disabled = false;
  els.iconsBtn.disabled = false;
  els.unitTitle.textContent = state.unit.name;
  els.unitMeta.textContent = `${state.unit.sid} / tier ${state.unit.tier ?? "?"} / donor ${state.unit.donorFactionSid ?? "?"}/${state.unit.donorBaseSid ?? "?"}`;
  els.sourceMeta.textContent = state.currentData?.sources
    ? `Logic: ${state.currentData.sources.logic || "missing"} / View: ${state.currentData.sources.view || "missing"}`
    : "";
  const override = unitOverride();
  els.replaceAbilities.checked = Boolean(override?.replaceExistingAbilities);
  els.replacePassives.checked = Boolean(override?.replaceExistingPassives);
}

function addField(container, ability, key, value) {
  if (HIDDEN_FIELDS.has(key)) return;
  const label = document.createElement("label");
  const numeric = typeof value === "number" || ["energyLevel", "cooldown", "rank", "animationIndex", "projectileSpeed", "charges", "spellTier", "spellEffectLevel", "effectiveSpellPower", "effectDuration"].includes(key);
  label.textContent = fieldLabel(key);
  if (SELECT_OPTIONS[key]) {
    const select = document.createElement("select");
    for (const [optionValue, text] of SELECT_OPTIONS[key]) {
      const option = document.createElement("option");
      option.value = optionValue;
      option.textContent = text;
      select.append(option);
    }
    select.value = value;
    select.addEventListener("change", () => {
      ability.fields[key] = numeric && select.value !== "" ? Number(select.value) : select.value;
    });
    label.append(select);
    container.append(label);
    return;
  }
  if (EFFECT_FIELD_KINDS[key]) {
    const valueRow = document.createElement("div");
    valueRow.className = "selected-value";
    const output = document.createElement("span");
    output.textContent = selectedEffectLabel(value);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "field-pick";
    button.textContent = `Select ${fieldLabel(key)}`;
    button.addEventListener("click", () => {
      openEffectSelector({
        allowedKinds: EFFECT_FIELD_KINDS[key],
        set(effect) {
          const selected = effectValueForField(key, effect);
          ability.fields[key] = selected;
          if (key === "spellEffectKey") {
            applySpellEffectDefaults(ability, effect);
          }
          if (key === "unitSpecialKey") {
            applyUnitSpecialDefaults(ability, effect);
          }
          output.textContent = selectedEffectLabel(selected, effect);
        }
      });
    });
    valueRow.append(output, button);
    label.append(valueRow);
    container.append(label);
    return;
  }
  if (key.toLowerCase().includes("icon")) {
    const valueRow = document.createElement("div");
    valueRow.className = "selected-value";
    const output = document.createElement("span");
    output.textContent = value || "No icon selected";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "field-pick";
    button.textContent = "Pick Icon";
    button.addEventListener("click", () => {
      state.iconTarget = {
        set(selected) {
          ability.fields[key] = selected;
          output.textContent = selected || "No icon selected";
        }
      };
      renderIcons();
      els.iconsDialog.showModal();
    });
    valueRow.append(output, button);
    label.append(valueRow);
    container.append(label);
    return;
  }
  const input = key === "description"
    ? document.createElement("textarea")
    : document.createElement("input");
  if (input.tagName === "TEXTAREA") input.rows = key === "description" ? 3 : 2;
  if (numeric) input.type = "number";
  input.value = sidTemplate(value);
  input.addEventListener("focus", () => {
    state.focusedField = { input, ability, key };
  });
  input.addEventListener("input", () => {
    ability.fields[key] = numeric && input.value !== "" ? Number(input.value) : input.value;
  });
  label.append(input);
  container.append(label);
}

function selectedEffectLabel(value, effect = null) {
  if (effect) return `${effect.label || effect.key}`;
  const match = state.effects.find(item => item.key === value || item.id === value);
  return match ? `${match.label || match.key}` : (value || "Nothing selected");
}

function effectValueForField(key, effect) {
  if (key === "abilityType") return effect.key;
  if (key === "projectile") return effect.key;
  if (key === "spellEffectKey") return effect.key;
  if (key === "unitSpecialKey") return effect.key;
  if (key === "buffSid" && effect.kind === "mechanic-value") {
    const parts = String(effect.key).split(":");
    return parts.length > 1 ? parts.slice(1).join(":") : effect.key;
  }
  return effect.key;
}

async function loadHeroSkills() {
  const catalog = await api("/api/hero_skills");
  state.heroSkills = catalog.skills || [];
}

async function loadHeroSpecializations() {
  const catalog = await api("/api/hero_specializations");
  state.heroSpecializations = catalog.specializations || [];
  state.specializationBonusTemplates = catalog.bonusTemplates || [];
}

function applyUnitSpecialDefaults(ability, effect) {
  const payload = effect.payload || {};
  if (payload.sourceUnitSid) ability.fields.sourceUnitSid = payload.sourceUnitSid;
  if (payload.slotKind) ability.fields.sourceSlotKind = payload.slotKind;
  if (payload.index !== undefined && payload.index !== null) ability.fields.sourceSlotIndex = Number(payload.index);
  if (payload.nameKey) ability.fields.nameToken = payload.nameKey;
  if (payload.descriptionKey) ability.fields.descriptionToken = payload.descriptionKey;
  if (payload.view?.abilityType) ability.fields.abilityType = payload.view.abilityType;
  if (payload.view?.animationIndex !== undefined) ability.fields.animationIndex = Number(payload.view.animationIndex);
  if (payload.logic?.rank !== undefined) ability.fields.rank = Number(payload.logic.rank);
  if (payload.logic?.energyLevel !== undefined) ability.fields.energyLevel = Number(payload.logic.energyLevel);
  if (payload.logic?.cd !== undefined) ability.fields.cooldown = Number(payload.logic.cd);
  ability.fields.turnBehavior = turnBehaviorFromLogic(payload.logic);
  if (payload.view?.icon && !isLikelyRuntimeIconKey(ability.fields.iconKey)) ability.fields.iconKey = payload.view.icon;
}

function isLikelyRuntimeIconKey(value) {
  const key = String(value || "").trim();
  if (!key) return false;
  if (key.includes("@") || key.includes("/") || key.includes("\\")) return false;
  if (key.endsWith("_name") || key.endsWith("_description")) return false;
  return /^[A-Za-z0-9_.-]+$/.test(key);
}

function applySpellEffectDefaults(ability, effect) {
  const payload = effect.payload || {};
  if (payload.spellSid) ability.fields.spellSid = payload.spellSid;
  if (payload.spellTier) ability.fields.spellTier = Number(payload.spellTier);
  if (payload.spellLevel) ability.fields.spellEffectLevel = Number(payload.spellLevel);
  if (payload.duration !== undefined && payload.duration !== null) ability.fields.effectDuration = Number(payload.duration);
  if (payload.buffSid) ability.fields.buffSid = payload.buffSid;
  if (payload.icon && !isLikelyRuntimeIconKey(ability.fields.iconKey)) ability.fields.iconKey = payload.icon;
}

function applySpecialEffectDefaults(entry, effect) {
  const payload = effect.payload || {};
  if (payload.view?.abilityType) entry.abilityType = payload.view.abilityType;
  if (payload.view?.animationIndex !== undefined) entry.animationIndex = Number(payload.view.animationIndex);
  if (payload.logic?.rank !== undefined) entry.rank = Number(payload.logic.rank);
  if (payload.logic?.energyLevel !== undefined) entry.energyLevel = Number(payload.logic.energyLevel);
  if (payload.logic?.cd !== undefined) entry.cooldown = Number(payload.logic.cd);
  if (payload.logic?.charges !== undefined) entry.charges = Number(payload.logic.charges);
  entry.turnBehavior = turnBehaviorFromLogic(payload.logic);
  if (payload.view?.icon && !isLikelyRuntimeIconKey(entry.iconKey)) entry.iconKey = payload.view.icon;
  if (payload.icon && !isLikelyRuntimeIconKey(entry.iconKey)) entry.iconKey = payload.icon;
}

function turnBehaviorFromLogic(logic) {
  return Number(logic?.actionCost) === 0 ? "free" : "ends";
}

function addSpecialSelect(container, entry, key, value, onChange) {
  const label = document.createElement("label");
  label.textContent = fieldLabel(key);
  const select = document.createElement("select");
  for (const [optionValue, text] of SELECT_OPTIONS[key] || []) {
    const option = document.createElement("option");
    option.value = optionValue;
    option.textContent = text;
    select.append(option);
  }
  select.value = value ?? "";
  select.addEventListener("change", () => {
    const numeric = typeof (SELECT_OPTIONS[key] || [])[0]?.[0] === "number";
    entry[key] = numeric && select.value !== "" ? Number(select.value) : select.value;
    onChange();
  });
  label.append(select);
  container.append(label);
  return select;
}

function specialOverride(base) {
  const override = unitOverride();
  let entry = override.existingSpecials.find(item => item.key === base.key);
  if (!entry) {
    entry = {
      key: base.key,
      slotKind: base.slotKind,
      index: base.index,
      enabled: true,
      nameKey: base.nameKey,
      descriptionKey: base.descriptionKey,
      nameText: base.nameText,
      descriptionText: base.descriptionText,
      iconKey: base.view?.icon || "",
      abilityType: base.view?.abilityType || "",
      animationIndex: base.view?.animationIndex ?? 2,
      turnBehavior: turnBehaviorFromLogic(base.logic),
      energyLevel: base.logic?.energyLevel ?? 0,
      cooldown: base.logic?.cd ?? 0,
      rank: base.logic?.rank ?? 1,
      charges: base.logic?.charges ?? "",
      effectKey: "",
      effectLabel: "",
      effectPayload: {},
      notes: ""
    };
  }
  return entry;
}

function persistSpecialOverride(entry) {
  const override = unitOverride();
  const index = override.existingSpecials.findIndex(item => item.key === entry.key);
  if (index >= 0) override.existingSpecials[index] = entry;
  else override.existingSpecials.push(entry);
}

function currentHeroUnits() {
  return currentFaction()?.units || [];
}

function unitName(sid) {
  return currentHeroUnits().find(unit => unit.sid === sid)?.name || sid || "Select unit";
}

function addSquadRow(list, row = { sid: currentHeroUnits()[0]?.sid || "", min: 1, max: 1 }) {
  list.push(row);
  renderHeroEditor();
}

function renderSquadEditor(container, title, rows) {
  const section = document.createElement("section");
  section.className = "hero-section";
  section.innerHTML = `<h4>${escapeHtml(title)}</h4>`;
  const list = document.createElement("div");
  list.className = "row-list";
  for (const row of rows) {
    const item = document.createElement("div");
    item.className = "row-item";
    const unit = document.createElement("select");
    for (const optionUnit of currentHeroUnits()) {
      const option = document.createElement("option");
      option.value = optionUnit.sid;
      option.textContent = optionUnit.name;
      unit.append(option);
    }
    unit.value = row.sid || "";
    const min = document.createElement("input");
    min.type = "number";
    min.min = "0";
    min.value = row.min ?? 1;
    const max = document.createElement("input");
    max.type = "number";
    max.min = "0";
    max.value = row.max ?? row.min ?? 1;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "danger";
    remove.textContent = "Remove";
    unit.addEventListener("change", () => row.sid = unit.value);
    min.addEventListener("input", () => row.min = Number(min.value || 0));
    max.addEventListener("input", () => row.max = Number(max.value || 0));
    remove.addEventListener("click", () => {
      rows.splice(rows.indexOf(row), 1);
      renderHeroEditor();
    });
    item.append(unit, min, max, remove);
    list.append(item);
  }
  const add = document.createElement("button");
  add.type = "button";
  add.textContent = "Add Unit";
  add.addEventListener("click", () => addSquadRow(rows));
  section.append(list, add);
  container.append(section);
}

function skillName(sid) {
  return state.heroSkills.find(skill => skill.sid === sid)?.label || sid || "Select skill";
}

function renderSkillEditor(container, rows) {
  const section = document.createElement("section");
  section.className = "hero-section";
  section.innerHTML = `<h4>Starting Skills</h4>`;
  const list = document.createElement("div");
  list.className = "row-list";
  for (const row of rows) {
    const item = document.createElement("div");
    item.className = "row-item skill-row";
    const selected = document.createElement("div");
    selected.className = "selected-value";
    selected.innerHTML = `<span>${escapeHtml(skillName(row.sid))}</span>`;
    const pick = document.createElement("button");
    pick.type = "button";
    pick.className = "field-pick";
    pick.textContent = "Select Skill";
    pick.addEventListener("click", () => {
      state.skillTarget = {
        set(skill) {
          row.sid = skill.sid;
          renderHeroEditor();
        }
      };
      renderSkills();
      els.skillDialog.showModal();
    });
    selected.append(pick);
    const level = document.createElement("select");
    for (const value of [1, 2, 3]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = `Level ${value}`;
      level.append(option);
    }
    level.value = row.skillLevel || 1;
    level.addEventListener("change", () => row.skillLevel = Number(level.value));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "danger";
    remove.textContent = "Remove";
    remove.addEventListener("click", () => {
      rows.splice(rows.indexOf(row), 1);
      renderHeroEditor();
    });
    item.append(selected, level, remove);
    list.append(item);
  }
  const add = document.createElement("button");
  add.type = "button";
  add.textContent = "Add Skill";
  add.addEventListener("click", () => {
    rows.push({ sid: state.heroSkills[0]?.sid || "", skillLevel: 1 });
    renderHeroEditor();
  });
  section.append(list, add);
  container.append(section);
}

function renderHeroEditor() {
  const entry = heroOverride();
  els.heroEditor.innerHTML = "";
  if (!entry || !state.hero) {
    els.heroEditor.className = "hero-editor empty";
    els.heroEditor.textContent = "Select a hero.";
    return;
  }
  els.heroEditor.className = "hero-editor";
  const current = state.currentHeroData?.summary || {};
  const basics = document.createElement("section");
  basics.className = "hero-section";
  basics.innerHTML = `
    <h4>Identity</h4>
    <div class="field-grid">
      <label>Name<input class="hero-name"></label>
      <label>Description<textarea class="hero-description" rows="3"></textarea></label>
      <label>Motto<textarea class="hero-motto" rows="2"></textarea></label>
      <label>Class Type<select class="hero-class-type"><option value="might">Might</option><option value="magic">Magic</option></select></label>
      <label>Class Name<input class="hero-class-name"></label>
      <label>Icon<div class="selected-value"><span class="hero-icon-value"></span><button type="button" class="field-pick hero-icon-pick">Pick Icon</button></div></label>
    </div>
  `;
  const name = basics.querySelector(".hero-name");
  const desc = basics.querySelector(".hero-description");
  const motto = basics.querySelector(".hero-motto");
  const classType = basics.querySelector(".hero-class-type");
  const className = basics.querySelector(".hero-class-name");
  const iconValue = basics.querySelector(".hero-icon-value");
  const iconPick = basics.querySelector(".hero-icon-pick");
  name.value = entry.nameText || current.name || state.hero.name || "";
  desc.value = entry.descriptionText || current.description || "";
  motto.value = entry.mottoText || "";
  classType.value = entry.classType || current.classType || state.hero.classType || "might";
  className.value = entry.className || current.className || state.hero.className || "";
  iconValue.textContent = entry.iconKey || current.icon || state.hero.icon || "No icon selected";
  const syncBasics = () => {
    entry.nameText = name.value;
    entry.descriptionText = desc.value;
    entry.mottoText = motto.value;
    entry.classType = classType.value;
    entry.className = className.value;
  };
  for (const input of [name, desc, motto, classType, className]) {
    input.addEventListener("input", syncBasics);
    input.addEventListener("change", syncBasics);
  }
  iconPick.addEventListener("click", () => {
    state.iconTarget = {
      set(selected) {
        entry.iconKey = selected;
        iconValue.textContent = selected || "No icon selected";
      }
    };
    renderIcons();
    els.iconsDialog.showModal();
  });
  els.heroEditor.append(basics);
  if (entry.startSquad.length === 0 && Array.isArray(current.startSquad)) entry.startSquad = JSON.parse(JSON.stringify(current.startSquad));
  if (entry.startSquadAlt.length === 0 && Array.isArray(current.startSquadAlt)) entry.startSquadAlt = JSON.parse(JSON.stringify(current.startSquadAlt));
  if (entry.startSkills.length === 0 && Array.isArray(current.startSkills)) entry.startSkills = JSON.parse(JSON.stringify(current.startSkills));
  renderSquadEditor(els.heroEditor, "Starting Army", entry.startSquad);
  renderSquadEditor(els.heroEditor, "Alternate Starting Army", entry.startSquadAlt);
  renderSkillEditor(els.heroEditor, entry.startSkills);
  renderSpecializationEditor(els.heroEditor, entry);
}

function renderSpecializationEditor(container, entry) {
  const spec = entry.specialization;
  const section = document.createElement("section");
  section.className = "hero-section";
  section.innerHTML = `
    <h4>Specialization</h4>
    <div class="field-grid">
      <label>Mode<select class="spec-mode"><option value="custom">Custom bonuses</option><option value="copy">Copy vanilla specialization</option></select></label>
      <label>Name<input class="spec-name"></label>
      <label>Description<textarea class="spec-description" rows="3"></textarea></label>
      <label>Icon<div class="selected-value"><span class="spec-icon-value"></span><button type="button" class="field-pick spec-icon-pick">Pick Icon</button></div></label>
      <label>Vanilla source<div class="selected-value"><span class="spec-source-value"></span><button type="button" class="field-pick spec-source-pick">Select Source</button></div></label>
    </div>
    <div class="row-list spec-bonus-list"></div>
    <button type="button" class="spec-bonus-add">Add Bonus</button>
  `;
  const mode = section.querySelector(".spec-mode");
  const name = section.querySelector(".spec-name");
  const desc = section.querySelector(".spec-description");
  const iconValue = section.querySelector(".spec-icon-value");
  const sourceValue = section.querySelector(".spec-source-value");
  const bonuses = section.querySelector(".spec-bonus-list");
  mode.value = spec.mode || "custom";
  name.value = spec.nameText || state.currentHeroData?.summary?.specializationName || "";
  desc.value = spec.descriptionText || state.currentHeroData?.summary?.specializationDescription || "";
  iconValue.textContent = spec.iconKey || state.currentHeroData?.summary?.specializationIcon || "No icon selected";
  sourceValue.textContent = spec.sourceSpecId || "No source selected";
  const sync = () => {
    spec.mode = mode.value;
    spec.nameText = name.value;
    spec.descriptionText = desc.value;
  };
  for (const input of [mode, name, desc]) {
    input.addEventListener("input", sync);
    input.addEventListener("change", sync);
  }
  section.querySelector(".spec-icon-pick").addEventListener("click", () => {
    state.iconTarget = {
      set(selected) {
        spec.iconKey = selected;
        iconValue.textContent = selected || "No icon selected";
      }
    };
    renderIcons();
    els.iconsDialog.showModal();
  });
  section.querySelector(".spec-source-pick").addEventListener("click", () => {
    state.specializationTarget = {
      mode: "source",
      set(item) {
        spec.sourceSpecId = item.sid;
        spec.mode = "copy";
        spec.nameText ||= item.label || "";
        spec.descriptionText ||= item.description || "";
        spec.iconKey ||= item.icon || "";
        renderHeroEditor();
      }
    };
    renderSpecializations();
    els.specializationDialog.showModal();
  });
  for (const bonus of spec.bonuses) {
    const item = document.createElement("div");
    item.className = "row-item";
    const stat = document.createElement("select");
    for (const key of ["offence", "defence", "spellPower", "intelligence", "luck", "moral", "viewRadius"]) {
      const option = document.createElement("option");
      option.value = key;
      option.textContent = key;
      stat.append(option);
    }
    stat.value = bonus.stat || "offence";
    const increment = document.createElement("input");
    increment.type = "number";
    increment.value = bonus.increment ?? 1;
    const step = document.createElement("input");
    step.type = "number";
    step.value = bonus.levelStep ?? 5;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "danger";
    remove.textContent = "Remove";
    stat.addEventListener("change", () => bonus.stat = stat.value);
    increment.addEventListener("input", () => bonus.increment = Number(increment.value || 0));
    step.addEventListener("input", () => bonus.levelStep = Number(step.value || 1));
    remove.addEventListener("click", () => {
      spec.bonuses.splice(spec.bonuses.indexOf(bonus), 1);
      renderHeroEditor();
    });
    item.append(stat, increment, step, remove);
    bonuses.append(item);
  }
  section.querySelector(".spec-bonus-add").addEventListener("click", () => {
    spec.bonuses.push({ type: "heroStat", stat: "offence", base: 0, increment: 1, levelStep: 5 });
    renderHeroEditor();
  });
  container.append(section);
}

function describeLawBonusClient(bonus) {
  if (!bonus || typeof bonus !== "object") return "Malformed bonus row.";
  const type = bonus.type || "";
  const params = Array.isArray(bonus.parameters) ? bonus.parameters : [];
  const receivers = Array.isArray(bonus.receivers) ? bonus.receivers : [];
  const target = receivers.length ? `${receivers.length} listed unit(s)` : "matching target";
  if (type === "sideRes" && params.length >= 2) return `Daily ${params[0]} income changes by ${params[1]}.`;
  if (type === "sideOneTimeAddRes" && params.length >= 2) return `One-time grant: ${params[1]} ${params[0]}.`;
  if (type === "sideObjectViewRadius" && params.length) return `Object view radius changes by ${params[0]}.`;
  if (type === "cityUnitsIncrement" && params.length >= 2) return `Weekly growth for ${params[0]} changes by ${params[1]}.`;
  if (type === "unitHiringDiscount") return `Unit hiring discount: ${params.join(", ")}.`;
  if ((type === "heroStat" || type === "heroStatBattle") && params.length >= 2) return `${type} ${params[0]} changes by ${params[params.length - 1]}.`;
  if (type === "unitStat" && params.length) return `${target} stat ${params[0]} changes by ${params[params.length - 1]}.`;
  if (type === "astrologyExp" && params.length) return `Daily Astrology points: ${params[0]}.`;
  if (type === "battleSubskillBonus") return `Adds battle subskill bonus: ${params.join(", ")}.`;
  return type ? `${type}${params.length ? `: ${params.join(", ")}` : ""}` : "No effect type.";
}

function defaultLawBonus(type = "sideRes") {
  if (type === "sideOneTimeAddRes") return { type, parameters: ["gold", 1000] };
  if (type === "sideObjectViewRadius") return { type, parameters: [2] };
  if (type === "sideStat") return { type, parameters: ["resPercentIncrementSet", "gold", "0.10"] };
  if (type === "heroStat") return { type, parameters: ["offence", "1"] };
  if (type === "heroStatBattle") return { type, parameters: ["magicCdBonus", "1"] };
  if (type === "unitStat") return { type, receivers: [], parameters: ["offence", "1"] };
  if (type === "cityUnitsIncrement") return { type, parameters: [(currentFaction()?.units || [])[0]?.sid || "", 1] };
  if (type === "unitHiringDiscount") return { type, parameters: ["-0.10"] };
  if (type === "constructionDailyLimit") return { type, parameters: [1] };
  if (type === "constructionDiscount") return { type, parameters: ["wood", "-0.20"] };
  if (type === "astrologyExp") return { type, parameters: [250, 0.0] };
  if (type === "battleSubskillBonus") return { type, parameters: ["unit_buff", "power_of_the_dragon_father_item_set_bonus_1"] };
  return { type: "sideRes", parameters: ["gold", 250] };
}

function normalizeLawBonusForType(bonus, type) {
  const next = { ...defaultLawBonus(type), ...bonus, type };
  if (!Array.isArray(next.parameters)) next.parameters = defaultLawBonus(type).parameters;
  return next;
}

function renderLawTargetingFields(container, bonus, persist) {
  const target = document.createElement("details");
  target.className = "law-targeting";
  target.open = Boolean((bonus.receivers || []).length || bonus.fraction || bonus.biomeType || bonus.receiverAllegiance);
  target.innerHTML = `
    <summary>Targets and filters</summary>
    <div class="field-grid compact-grid">
      <label>Unit receivers<div class="law-receiver-picker"><select class="law-receiver-select"></select><button type="button" class="law-receiver-add">Add</button></div><div class="law-receiver-list"></div></label>
      <label>Faction<select class="law-fraction"></select></label>
      <label>Biome<select class="law-biome"></select></label>
      <label>Allegiance<select class="law-allegiance"></select></label>
    </div>
  `;
  const receiverSelect = target.querySelector(".law-receiver-select");
  const receiverAdd = target.querySelector(".law-receiver-add");
  const receiverList = target.querySelector(".law-receiver-list");
  const fraction = target.querySelector(".law-fraction");
  const biome = target.querySelector(".law-biome");
  const allegiance = target.querySelector(".law-allegiance");
  const renderReceivers = () => {
    const receivers = Array.isArray(bonus.receivers) ? bonus.receivers : [];
    const options = lawUnitOptions();
    receiverList.innerHTML = receivers.length ? "" : `<span class="muted-note">No specific units selected.</span>`;
    for (const [index, sid] of receivers.entries()) {
      const chip = document.createElement("span");
      chip.className = "law-chip";
      chip.innerHTML = `<span>${escapeHtml(labelForOption(options, sid))}</span><button type="button" aria-label="Remove ${escapeHtml(sid)}">x</button>`;
      chip.querySelector("button").addEventListener("click", () => {
        receivers.splice(index, 1);
        if (receivers.length) bonus.receivers = receivers;
        else delete bonus.receivers;
        persist();
        renderReceivers();
      });
      receiverList.append(chip);
    }
  };
  fillOptions(receiverSelect, lawUnitOptions(), (currentFaction()?.units || [])[0]?.sid || "");
  fillOptions(fraction, factionOptions(bonus.fraction || ""), bonus.fraction || "");
  fillOptions(biome, BIOME_OPTIONS, bonus.biomeType || "");
  fillOptions(allegiance, RECEIVER_ALLEGIANCE_OPTIONS, bonus.receiverAllegiance || "");
  renderReceivers();
  receiverAdd.addEventListener("click", () => {
    const sid = receiverSelect.value;
    if (!sid) return;
    const receivers = Array.isArray(bonus.receivers) ? bonus.receivers : [];
    if (!receivers.includes(sid)) receivers.push(sid);
    bonus.receivers = receivers;
    persist();
    renderReceivers();
  });
  fraction.addEventListener("change", () => {
    if (fraction.value) bonus.fraction = fraction.value;
    else delete bonus.fraction;
    persist();
  });
  biome.addEventListener("change", () => {
    if (biome.value) bonus.biomeType = biome.value;
    else delete bonus.biomeType;
    persist();
  });
  allegiance.addEventListener("change", () => {
    if (allegiance.value) bonus.receiverAllegiance = allegiance.value;
    else delete bonus.receiverAllegiance;
    persist();
  });
  container.append(target);
}

function appendLawInput(grid, label, value, onInput, options = {}) {
  const wrap = document.createElement("label");
  wrap.textContent = label;
  const input = document.createElement(options.select ? "select" : "input");
  if (options.select) {
    fillOptions(input, options.select, String(value ?? ""));
  } else {
    input.type = options.type || "text";
    input.value = value ?? "";
    if (options.placeholder) input.placeholder = options.placeholder;
  }
  input.addEventListener(options.select ? "change" : "input", () => onInput(input));
  wrap.append(input);
  grid.append(wrap);
  return input;
}

function renderLawBonusParameterFields(grid, bonus, persist, rerender = null) {
  const params = Array.isArray(bonus.parameters) ? bonus.parameters : [];
  const setParam = (index, value) => {
    bonus.parameters ||= [];
    bonus.parameters[index] = value;
    persist();
  };
  const setParams = values => {
    bonus.parameters = values;
    persist();
  };
  if (bonus.type === "sideRes" || bonus.type === "sideOneTimeAddRes") {
    appendLawInput(grid, "Resource", params[0] || "gold", input => setParam(0, input.value), { select: RESOURCE_OPTIONS });
    appendLawInput(grid, "Amount", numericInputValue(params[1]), input => setParam(1, valueFromNumericInput(input)), { type: "number" });
    return;
  }
  if (bonus.type === "sideObjectViewRadius") {
    appendLawInput(grid, "Radius", numericInputValue(params[0]), input => setParam(0, valueFromNumericInput(input)), { type: "number" });
    return;
  }
  if (bonus.type === "sideStat") {
    const operation = params[0] || "resPercentIncrementSet";
    appendLawInput(grid, "Side effect", operation, input => {
      if (input.value === "disableMarketsExtraCharge") setParams(["disableMarketsExtraCharge", "true"]);
      else setParams(["resPercentIncrementSet", RESOURCE_OPTIONS.includes(params[1]) ? params[1] : "gold", params[2] || "0.10"]);
      if (rerender) rerender();
    }, { select: SIDE_STAT_OPTIONS });
    if (operation === "disableMarketsExtraCharge") {
      appendLawInput(grid, "Enabled", params[1] || "true", input => setParam(1, input.value), { select: [["true", "True"], ["false", "False"]] });
    } else {
      appendLawInput(grid, "Resource", params[1] || "gold", input => setParam(1, input.value), { select: RESOURCE_OPTIONS });
      appendLawInput(grid, "Percent", params[2] || "", input => setParam(2, input.value), { placeholder: "0.10" });
    }
    return;
  }
  if (bonus.type === "heroStat" || bonus.type === "heroStatBattle") {
    appendLawInput(grid, "Hero stat", params[0] || "", input => setParam(0, input.value), { select: HERO_STAT_OPTIONS });
    appendLawInput(grid, "Value", params[1] || "", input => setParam(1, input.value));
    appendLawInput(grid, "Threshold/base", params[2] || "", input => {
      if (input.value === "" && bonus.parameters.length <= 3) bonus.parameters.splice(2, 1);
      else setParam(2, input.value);
      persist();
    });
    appendLawInput(grid, "Increment/extra", params[3] || "", input => {
      if (input.value === "" && bonus.parameters.length <= 4) bonus.parameters.splice(3, 1);
      else setParam(3, input.value);
      persist();
    });
    return;
  }
  if (bonus.type === "unitStat") {
    const stat = params[0] || "offence";
    appendLawInput(grid, "Unit stat", stat, input => {
      const newType = input.value;
      if (newType === "modifierSet") setParams(["modifierSet", params[1] || "outDmgMods", params[2] || "melee_attack", params[3] || "0.10"]);
      else setParams([newType, params[1] || "1"]);
      if (rerender) rerender();
    }, { select: UNIT_STAT_OPTIONS });
    if (stat === "modifierSet") {
      appendLawInput(grid, "Modifier set", params[1] || "outDmgMods", input => setParam(1, input.value), { select: DAMAGE_MODIFIER_OPTIONS });
      appendLawInput(grid, "Damage kind", params[2] || "melee_attack", input => setParam(2, input.value), { select: DAMAGE_KIND_OPTIONS });
      appendLawInput(grid, "Amount", params[3] || "", input => setParam(3, input.value));
    } else {
      appendLawInput(grid, "Amount", params[1] || "", input => setParam(1, input.value));
    }
    return;
  }
  if (bonus.type === "cityUnitsIncrement") {
    appendLawInput(grid, "Unit", params[0] || "", input => setParam(0, input.value), { select: lawUnitOptions(params[0] || "") });
    appendLawInput(grid, "Growth", numericInputValue(params[1]), input => setParam(1, valueFromNumericInput(input)), { type: "number" });
    return;
  }
  if (bonus.type === "unitHiringDiscount") {
    appendLawInput(grid, "Discount", params[0] || "", input => setParam(0, input.value), { placeholder: "-0.10" });
    return;
  }
  if (bonus.type === "constructionDailyLimit") {
    appendLawInput(grid, "Additional builds", numericInputValue(params[0]), input => setParam(0, valueFromNumericInput(input)), { type: "number" });
    return;
  }
  if (bonus.type === "constructionDiscount") {
    appendLawInput(grid, "Resource", params[0] || "wood", input => setParam(0, input.value), { select: RESOURCE_OPTIONS });
    appendLawInput(grid, "Discount", params[1] || "", input => setParam(1, input.value), { placeholder: "-0.20" });
    return;
  }
  if (bonus.type === "astrologyExp") {
    appendLawInput(grid, "Points", numericInputValue(params[0]), input => setParam(0, valueFromNumericInput(input)), { type: "number" });
    appendLawInput(grid, "Extra value", numericInputValue(params[1] ?? 0), input => setParam(1, valueFromNumericInput(input)), { type: "number" });
    return;
  }
  if (bonus.type === "battleSubskillBonus") {
    appendLawInput(grid, "Kind", params[0] || "", input => setParam(0, input.value));
    appendLawInput(grid, "Bonus SID", params[1] || "", input => setParam(1, input.value));
    return;
  }
  params.forEach((value, index) => {
    appendLawInput(grid, `Parameter ${index + 1}`, value, input => setParam(index, input.value));
  });
}

function renderLawBonusEditor(bonus, level, bonusIndex, persist, rerender) {
  const item = document.createElement("article");
  item.className = "law-bonus-card";
  item.innerHTML = `
    <header>
      <strong>Effect ${bonusIndex + 1}</strong>
      <button type="button" class="danger law-bonus-remove">Remove</button>
    </header>
    <div class="field-grid compact-grid">
      <label>Effect type<select class="law-bonus-type"></select></label>
    </div>
    <div class="field-grid compact-grid law-bonus-params"></div>
    <div class="law-effect-summary"></div>
  `;
  const type = item.querySelector(".law-bonus-type");
  const paramsGrid = item.querySelector(".law-bonus-params");
  const summary = item.querySelector(".law-effect-summary");
  fillOptions(type, LAW_BONUS_TYPE_OPTIONS, bonus.type || "sideRes");
  type.addEventListener("change", () => {
    for (const key of Object.keys(bonus)) delete bonus[key];
    Object.assign(bonus, normalizeLawBonusForType({}, type.value));
    persist();
    rerender();
  });
  renderLawBonusParameterFields(paramsGrid, bonus, () => {
    persist();
    summary.innerHTML = `<p>${escapeHtml(describeLawBonusClient(bonus))}</p>`;
  }, rerender);
  renderLawTargetingFields(item, bonus, () => {
    persist();
    summary.innerHTML = `<p>${escapeHtml(describeLawBonusClient(bonus))}</p>`;
  });
  summary.innerHTML = `<p>${escapeHtml(describeLawBonusClient(bonus))}</p>`;
  item.querySelector(".law-bonus-remove").addEventListener("click", () => {
    level.bonuses.splice(bonusIndex, 1);
    persist();
    rerender();
  });
  return item;
}

function renderLawEditor() {
  const entry = lawOverride();
  els.lawEditor.innerHTML = "";
  if (!entry || !state.law) {
    els.lawEditor.className = "law-editor empty";
    els.lawEditor.textContent = "Select a law.";
    return;
  }
  els.lawEditor.className = "law-editor";
  const basics = document.createElement("section");
  basics.className = "hero-section";
  basics.innerHTML = `
    <h4>Law Identity</h4>
    <div class="field-grid">
      <label>Enabled<label class="switch inline-switch"><input class="law-enabled" type="checkbox"> Apply override</label></label>
      <label>Name<input class="law-name"></label>
      <label>Description<textarea class="law-description" rows="3"></textarea></label>
      <label>Icon<div class="selected-value icon-selected-value"><span class="law-icon-preview"></span><span class="law-icon-value"></span><button type="button" class="field-pick law-icon-pick">Pick Icon</button></div></label>
      <label>Tree tier<input class="law-tree-tier" readonly></label>
      <label>Tree position<input class="law-tree-position" readonly></label>
      <label>Notes<textarea class="law-notes" rows="2"></textarea></label>
    </div>
  `;
  const enabled = basics.querySelector(".law-enabled");
  const name = basics.querySelector(".law-name");
  const description = basics.querySelector(".law-description");
  const iconValue = basics.querySelector(".law-icon-value");
  const iconPreview = basics.querySelector(".law-icon-preview");
  const treeTier = basics.querySelector(".law-tree-tier");
  const treePosition = basics.querySelector(".law-tree-position");
  const notes = basics.querySelector(".law-notes");
  enabled.checked = entry.enabled !== false;
  name.value = entry.nameText || state.law.name || "";
  description.value = entry.descriptionText || state.law.description || "";
  treeTier.value = lawUnlockLabel(state.law);
  treePosition.value = lawTreePositionLabel(state.law) || "Not found in faction law tree";
  const setLawIconDisplay = () => {
    const key = effectiveLawIconKey(state.law);
    iconPreview.innerHTML = iconPreviewHtml(key);
    iconValue.textContent = key || "No icon selected";
  };
  setLawIconDisplay();
  notes.value = entry.notes || "";
  const syncEnabled = () => {
    entry.enabled = enabled.checked;
    persistLawOverride(entry);
    setLawIconDisplay();
    renderUnits();
  };
  enabled.addEventListener("input", syncEnabled);
  enabled.addEventListener("change", syncEnabled);
  name.addEventListener("input", () => {
    entry.nameText = name.value;
    persistLawOverride(entry);
  });
  name.addEventListener("change", () => {
    entry.nameText = name.value;
    persistLawOverride(entry);
  });
  description.addEventListener("input", () => {
    entry.descriptionText = description.value;
    persistLawOverride(entry);
  });
  description.addEventListener("change", () => {
    entry.descriptionText = description.value;
    persistLawOverride(entry);
  });
  notes.addEventListener("input", () => {
    entry.notes = notes.value;
    persistLawOverride(entry);
  });
  notes.addEventListener("change", () => {
    entry.notes = notes.value;
    persistLawOverride(entry);
  });
  basics.querySelector(".law-icon-pick").addEventListener("click", () => {
    state.iconTarget = {
      set(selected) {
        entry.iconKey = selected;
        persistLawOverride(entry);
        setLawIconDisplay();
        renderUnits();
      }
    };
    renderIcons();
    els.iconsDialog.showModal();
  });
  els.lawEditor.append(basics);

  const levelsSection = document.createElement("section");
  levelsSection.className = "hero-section";
  levelsSection.innerHTML = `<h4>Law Levels And Effects</h4>`;
  const list = document.createElement("div");
  list.className = "law-level-list";
  const levels = editableLawLevels(entry);
  for (const [levelIndex, level] of levels.entries()) {
    const card = document.createElement("article");
    card.className = "law-level-card";
    card.innerHTML = `
      <header>
        <h4>Level ${levelIndex + 1}</h4>
        <button type="button" class="danger law-level-remove">Remove</button>
      </header>
      <div class="field-grid">
        <label>Cost<input class="law-level-cost" type="number"></label>
      </div>
      <div class="law-bonus-list"></div>
      <button type="button" class="law-bonus-add">Add Effect</button>
    `;
    const cost = card.querySelector(".law-level-cost");
    const bonusList = card.querySelector(".law-bonus-list");
    cost.value = level.cost ?? 0;
    const persistLevel = () => {
      ensureEditableLawLevels(entry, levels);
      persistLawOverride(entry);
    };
    const renderLevelBonuses = () => {
      bonusList.innerHTML = "";
      const bonuses = Array.isArray(level.bonuses) ? level.bonuses : [];
      level.bonuses = bonuses;
      for (const [bonusIndex, bonus] of bonuses.entries()) {
        bonusList.append(renderLawBonusEditor(bonus, level, bonusIndex, persistLevel, renderLawEditor));
      }
      if (!bonuses.length) {
        bonusList.innerHTML = `<div class="empty">No effects in this level.</div>`;
      }
    };
    renderLevelBonuses();
    cost.addEventListener("input", () => {
      ensureEditableLawLevels(entry, levels);
      level.cost = Number(cost.value || 0);
      persistLawOverride(entry);
    });
    card.querySelector(".law-level-remove").addEventListener("click", () => {
      ensureEditableLawLevels(entry, levels);
      levels.splice(levelIndex, 1);
      persistLawOverride(entry);
      renderLawEditor();
    });
    card.querySelector(".law-bonus-add").addEventListener("click", () => {
      ensureEditableLawLevels(entry, levels);
      level.bonuses ||= [];
      level.bonuses.push(defaultLawBonus());
      persistLawOverride(entry);
      renderLawEditor();
    });
    list.append(card);
  }
  const add = document.createElement("button");
  add.type = "button";
  add.textContent = "Add Level";
  add.addEventListener("click", () => {
    ensureEditableLawLevels(entry, levels);
    levels.push({ cost: 1, bonuses: [] });
    persistLawOverride(entry);
    renderLawEditor();
  });
  levelsSection.append(list, add);
  els.lawEditor.append(levelsSection);
}

function renderCurrentSpecials() {
  const override = unitOverride();
  const specials = state.currentData?.summary || [];
  els.currentSpecials.innerHTML = "";
  if (!override || specials.length === 0) {
    els.currentSpecials.className = "current-specials empty";
    els.currentSpecials.textContent = "No current special abilities found.";
    return;
  }
  els.currentSpecials.className = "current-specials";
  for (const base of specials) {
    const entry = specialOverride(base);
    const card = document.createElement("article");
    card.className = "special-card" + (entry.enabled === false ? " disabled-special" : "");
    const mechanics = (base.mechanics || []).join(", ");
    card.innerHTML = `
      <header>
        <div>
          <h4>${escapeHtml(entry.nameText || base.nameText || base.nameKey || base.key)}</h4>
          <p>${escapeHtml(base.slotKind)} #${base.index + 1}${base.abilityType ? ` / ${escapeHtml(base.abilityType)}` : ""}${mechanics ? ` / ${escapeHtml(mechanics)}` : ""}</p>
        </div>
        <label class="switch"><input type="checkbox" class="special-enabled"> Keep</label>
      </header>
      <div class="field-grid">
        <label>Name text<input class="special-name" value=""></label>
        <label>Description text<textarea class="special-description" rows="3"></textarea></label>
        <label>Effect<div class="selected-value"><span class="special-effect-value"></span><button type="button" class="field-pick special-effect-pick">Select Effect</button></div></label>
        <label>Icon<div class="selected-value"><span class="special-icon-value"></span><button type="button" class="field-pick special-icon-pick">Pick Icon</button></div></label>
        <div class="special-envelope"></div>
      </div>
    `;
    const enabled = card.querySelector(".special-enabled");
    const name = card.querySelector(".special-name");
    const desc = card.querySelector(".special-description");
    const effectValue = card.querySelector(".special-effect-value");
    const effectPick = card.querySelector(".special-effect-pick");
    const iconValue = card.querySelector(".special-icon-value");
    const iconPick = card.querySelector(".special-icon-pick");
    const envelope = card.querySelector(".special-envelope");
    enabled.checked = entry.enabled !== false;
    name.value = entry.nameText || "";
    desc.value = entry.descriptionText || "";
    effectValue.textContent = entry.effectLabel || entry.effectKey || "Current effect";
    iconValue.textContent = entry.iconKey || "No icon selected";
    const sync = () => {
      entry.enabled = enabled.checked;
      entry.nameText = name.value;
      entry.descriptionText = desc.value;
      persistSpecialOverride(entry);
      card.classList.toggle("disabled-special", entry.enabled === false);
    };
    const animationSelect = addSpecialSelect(envelope, entry, "animationIndex", entry.animationIndex ?? base.view?.animationIndex ?? 2, sync);
    const turnBehaviorSelect = addSpecialSelect(envelope, entry, "turnBehavior", entry.turnBehavior ?? turnBehaviorFromLogic(base.logic), sync);
    const focusSelect = addSpecialSelect(envelope, entry, "energyLevel", entry.energyLevel ?? base.logic?.energyLevel ?? 0, sync);
    const cooldownSelect = addSpecialSelect(envelope, entry, "cooldown", entry.cooldown ?? base.logic?.cd ?? 0, sync);
    const rankSelect = addSpecialSelect(envelope, entry, "rank", entry.rank ?? base.logic?.rank ?? 1, sync);
    const chargesSelect = addSpecialSelect(envelope, entry, "charges", entry.charges ?? base.logic?.charges ?? "", sync);
    effectPick.addEventListener("click", () => {
      openEffectSelector({
        set(effect) {
          entry.effectKey = effect.key;
          entry.effectKind = effect.kind;
          entry.effectLabel = effect.label || effect.key;
          entry.effectPayload = effect.payload || {};
          if (entry.effectPayload.nameKey) entry.nameKey = entry.effectPayload.nameKey;
          if (entry.effectPayload.descriptionKey) entry.descriptionKey = entry.effectPayload.descriptionKey;
          applySpecialEffectDefaults(entry, effect);
          animationSelect.value = entry.animationIndex ?? "";
          turnBehaviorSelect.value = entry.turnBehavior ?? "";
          focusSelect.value = entry.energyLevel ?? "";
          cooldownSelect.value = entry.cooldown ?? "";
          rankSelect.value = entry.rank ?? "";
          chargesSelect.value = entry.charges ?? "";
          effectValue.textContent = entry.effectLabel;
          persistSpecialOverride(entry);
        }
      });
    });
    iconPick.addEventListener("click", () => {
      state.iconTarget = {
        set(selected) {
          entry.iconKey = selected;
          iconValue.textContent = selected || "No icon selected";
          persistSpecialOverride(entry);
        }
      };
      renderIcons();
      els.iconsDialog.showModal();
    });
    for (const input of [enabled, name, desc]) {
      input.addEventListener("input", sync);
      input.addEventListener("change", sync);
    }
    els.currentSpecials.append(card);
  }
}

function renderAbilities() {
  const override = unitOverride();
  els.abilityList.innerHTML = "";
  if (!override || override.abilities.length === 0) {
    els.abilityList.className = "ability-list empty";
    els.abilityList.textContent = "No override abilities selected.";
    return;
  }
  els.abilityList.className = "ability-list";
  for (const ability of override.abilities) {
    const template = state.templates.find(item => item.id === ability.templateId);
    const fragment = els.cardTemplate.content.cloneNode(true);
    const card = fragment.querySelector(".ability-card");
    fragment.querySelector("h4").textContent = ability.fields.displayName || template?.label || ability.templateId;
    fragment.querySelector("p").textContent = template?.summary || "";
    const enabled = fragment.querySelector(".enabled");
    enabled.checked = ability.enabled !== false;
    enabled.addEventListener("change", () => ability.enabled = enabled.checked);
    const fields = fragment.querySelector(".field-grid");
    const defaults = template?.defaults || {};
    ability.fields = { ...defaults, ...ability.fields };
    for (const [key, value] of Object.entries(ability.fields)) {
      addField(fields, ability, key, value);
    }
    const notes = fragment.querySelector(".notes");
    notes.value = ability.notes || "";
    notes.addEventListener("input", () => ability.notes = notes.value);
    fragment.querySelector(".duplicate").addEventListener("click", () => {
      override.abilities.push(JSON.parse(JSON.stringify({ ...ability, id: `${ability.id}_copy` })));
      renderAbilities();
    });
    fragment.querySelector(".remove").addEventListener("click", () => {
      const index = override.abilities.indexOf(ability);
      if (index >= 0) override.abilities.splice(index, 1);
      renderAbilities();
    });
    els.abilityList.append(card);
  }
}

function renderTemplates() {
  els.templateGrid.innerHTML = "";
  for (const template of state.templates) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "template-card";
    button.innerHTML = `<strong>${template.label}</strong><span>${template.summary}</span><span class="risk">${template.risk}</span>`;
    button.addEventListener("click", () => {
      const override = unitOverride();
      override.abilities.push({
        id: `${state.unit.sid}_${template.id}_${Date.now()}`,
        templateId: template.id,
        enabled: true,
        fields: resolveDefaultFields(template.defaults || {}),
        notes: ""
      });
      els.abilityDialog.close();
      renderAbilities();
    });
    els.templateGrid.append(button);
  }
}

function renderEffectKinds() {
  const current = els.effectKind.value;
  const allowedKinds = state.effectTarget?.allowedKinds || null;
  const kinds = [...new Set(state.effects.map(effect => effect.kind))]
    .filter(kind => !allowedKinds || allowedKinds.includes(kind))
    .sort();
  els.effectKind.innerHTML = `<option value="">All kinds</option>`;
  for (const kind of kinds) {
    const option = document.createElement("option");
    option.value = kind;
    option.textContent = kind;
    els.effectKind.append(option);
  }
  els.effectKind.value = kinds.includes(current) ? current : "";
}

function openEffectSelector(target) {
  state.effectTarget = target;
  els.effectSearch.value = "";
  els.effectKind.value = "";
  renderEffects();
  els.effectsDialog.showModal();
}

function effectMatches(effect, query, kind) {
  const allowedKinds = state.effectTarget?.allowedKinds || null;
  if (allowedKinds && !allowedKinds.includes(effect.kind)) return false;
  if (kind && effect.kind !== kind) return false;
  if (!query) return true;
  const text = [
    effect.kind,
    effect.key,
    effect.label,
    ...(effect.tags || []),
    ...(effect.sources || [])
  ].join(" ").toLowerCase();
  return text.includes(query);
}

function applyEffect(effect) {
  if (state.effectTarget) {
    state.effectTarget.set(effect);
    state.effectTarget = null;
    els.effectsDialog.close();
    renderCurrentSpecials();
    renderAbilities();
    return;
  }
  if (!state.focusedField) return;
  const { input, ability, key } = state.focusedField;
  let value = effect.key;
  if (key === "mechanicsDebt") {
    value = `${ability.fields[key] || ""}${ability.fields[key] ? "; " : ""}Selected ${effect.kind}:${effect.key} from ${effect.sources?.[0] || "effect browser"}`;
  }
  input.value = value;
  ability.fields[key] = input.type === "number" && value !== "" ? Number(value) : value;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  els.effectsDialog.close();
}

function renderEffects() {
  renderEffectKinds();
  const mode = state.effectTarget ? "Select an effect for the active field" : "Browse indexed vanilla and generated effects";
  els.effectsSource.textContent = `${mode}. ${state.effectsSource ? `Indexed from ${state.effectsSource}` : "No Core.zip found"}`;
  const query = els.effectSearch.value.trim().toLowerCase();
  const kind = els.effectKind.value;
  const visible = state.effects.filter(effect => effectMatches(effect, query, kind)).slice(0, 250);
  els.effectList.innerHTML = "";
  for (const effect of visible) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "effect-card";
    const sources = (effect.sources || []).slice(0, 3).join(" | ");
    const description = (effect.tags || []).find(tag => typeof tag === "string" && tag.length > 24) || "";
    button.innerHTML = `<strong>${escapeHtml(effect.label)}</strong><span class="badge">${escapeHtml(effect.kind)}</span><code>${escapeHtml(effect.key)}</code>${description ? `<p>${escapeHtml(description)}</p>` : ""}<small>${escapeHtml(sources)}</small>`;
    button.addEventListener("click", () => applyEffect(effect));
    els.effectList.append(button);
  }
  if (visible.length === 0) {
    els.effectList.innerHTML = `<div class="empty">No matching effects.</div>`;
  }
}

function renderIconGroups() {
  const current = els.iconGroup.value;
  const groups = [...new Set(state.icons.map(icon => icon.group))].sort();
  els.iconGroup.innerHTML = `<option value="">All groups</option>`;
  for (const group of groups) {
    const option = document.createElement("option");
    option.value = group;
    option.textContent = group;
    els.iconGroup.append(option);
  }
  els.iconGroup.value = groups.includes(current) ? current : "";
}

function iconMatches(icon, query, group) {
  if (group && icon.group !== group) return false;
  if (!query) return true;
  return `${icon.key} ${icon.label} ${icon.path} ${icon.group}`.toLowerCase().includes(query);
}

function applyIcon(icon) {
  if (icon.runtimeSafe === false) return;
  if (state.iconTarget) {
    state.iconTarget.set(icon.key || icon.label);
    state.iconTarget = null;
    els.iconsDialog.close();
    return;
  }
  const target = state.focusedField;
  if (!target) return;
  const { input, ability, key } = target;
  const value = icon.key || icon.label;
  input.value = value;
  ability.fields[key] = value;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  els.iconsDialog.close();
}

function renderIcons() {
  renderIconGroups();
  const warningText = state.iconWarnings.length ? ` Warnings: ${state.iconWarnings.join(" / ")}` : "";
  els.iconsSource.textContent = state.iconRoots.length ? `Indexed ${state.icons.length} icons from repo assets and current law runtime keys.${warningText}` : `No icon roots found.${warningText}`;
  const query = els.iconSearch.value.trim().toLowerCase();
  const group = els.iconGroup.value;
  const visible = state.icons.filter(icon => iconMatches(icon, query, group)).slice(0, 400);
  els.iconGrid.innerHTML = "";
  for (const icon of visible) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "icon-card" + (icon.runtimeSafe === false ? " icon-card-disabled" : "");
    button.disabled = icon.runtimeSafe === false;
    const note = icon.runtimeSafe === false ? "Preview only: not a runtime sprite key" : (icon.path || "Runtime key from current law rows");
    const image = icon.url
      ? `<img loading="lazy" src="${escapeHtml(icon.url)}" alt="">`
      : `<span class="icon-card-placeholder">${escapeHtml((icon.key || "?").slice(0, 2).toUpperCase())}</span>`;
    button.innerHTML = `${image}<strong>${escapeHtml(icon.key)}</strong><small>${escapeHtml(note)}</small>`;
    button.addEventListener("click", () => applyIcon(icon));
    els.iconGrid.append(button);
  }
  if (visible.length === 0) {
    els.iconGrid.innerHTML = `<div class="empty">No matching icons.</div>`;
  }
}

function renderSkills() {
  const query = els.skillSearch.value.trim().toLowerCase();
  const visible = state.heroSkills.filter(skill => {
    if (!query) return true;
    return `${skill.sid} ${skill.label} ${skill.description}`.toLowerCase().includes(query);
  }).slice(0, 250);
  els.skillList.innerHTML = "";
  for (const skill of visible) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "effect-card";
    button.innerHTML = `<strong>${escapeHtml(skill.label)}</strong><code>${escapeHtml(skill.sid)}</code>${skill.description ? `<p>${escapeHtml(skill.description)}</p>` : ""}<small>${escapeHtml(skill.source || "")}</small>`;
    button.addEventListener("click", () => {
      if (state.skillTarget) state.skillTarget.set(skill);
      state.skillTarget = null;
      els.skillDialog.close();
    });
    els.skillList.append(button);
  }
  if (visible.length === 0) els.skillList.innerHTML = `<div class="empty">No matching skills.</div>`;
}

function renderSpecializations() {
  const query = els.specializationSearch.value.trim().toLowerCase();
  const rows = [
    ...state.specializationBonusTemplates.map(item => ({ ...item, catalogKind: "bonus" })),
    ...state.heroSpecializations.map(item => ({ ...item, catalogKind: "source" }))
  ];
  const visible = rows.filter(item => {
    if (state.specializationTarget?.mode === "source" && item.catalogKind !== "source") return false;
    if (!query) return true;
    return `${item.id || item.sid} ${item.label} ${item.description || item.summary}`.toLowerCase().includes(query);
  }).slice(0, 250);
  els.specializationList.innerHTML = "";
  for (const item of visible) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "effect-card";
    const key = item.sid || item.id;
    const description = item.description || item.summary || "";
    button.innerHTML = `<strong>${escapeHtml(item.label)}</strong><span class="badge">${escapeHtml(item.catalogKind)}</span><code>${escapeHtml(key)}</code>${description ? `<p>${escapeHtml(description)}</p>` : ""}<small>${escapeHtml(item.source || "")}</small>`;
    button.addEventListener("click", () => {
      if (state.specializationTarget) state.specializationTarget.set(item);
      state.specializationTarget = null;
      els.specializationDialog.close();
    });
    els.specializationList.append(button);
  }
  if (visible.length === 0) els.specializationList.innerHTML = `<div class="empty">No matching specializations.</div>`;
}

function renderCurrentData() {
  if (state.mode === "laws") {
    els.currentData.textContent = JSON.stringify(state.law || {}, null, 2);
    return;
  }
  if (!state.currentData) {
    els.currentData.textContent = "";
    return;
  }
  if (state.mode === "heroes") {
    els.currentData.textContent = JSON.stringify(state.currentHeroData || {}, null, 2);
  } else {
    els.currentData.textContent = JSON.stringify(state.currentData[state.currentTab], null, 2);
  }
}

function render() {
  renderFactions();
  renderUnits();
  renderUnitHeader();
  renderCurrentSpecials();
  renderAbilities();
  renderTemplates();
  renderEffects();
  renderIcons();
  renderSkills();
  renderSpecializations();
  renderCurrentData();
}

els.factionSelect.addEventListener("change", async () => {
  state.faction = els.factionSelect.value;
  await loadOverrides();
  await loadHeroOverrides();
  await loadLawOverrides();
  await loadCurrentLawData();
  state.unit = currentFaction()?.units?.[0] || null;
  state.hero = currentFaction()?.heroes?.[0] || null;
  state.law = state.currentLawData?.laws?.[0] || null;
  await loadCurrentUnitData();
  await loadCurrentHeroData();
  render();
});

els.unitSearch.addEventListener("input", renderUnits);

els.unitModeBtn.addEventListener("click", async () => {
  state.mode = "units";
  state.unit ||= currentFaction()?.units?.[0] || null;
  await loadCurrentUnitData();
  render();
});

els.heroModeBtn.addEventListener("click", async () => {
  state.mode = "heroes";
  state.hero ||= currentFaction()?.heroes?.[0] || null;
  await loadCurrentHeroData();
  render();
});

els.lawModeBtn.addEventListener("click", async () => {
  state.mode = "laws";
  if (!state.currentLawData) await loadCurrentLawData();
  state.law ||= state.currentLawData?.laws?.[0] || null;
  render();
});

els.replaceAbilities.addEventListener("change", () => {
  const override = unitOverride();
  if (override) override.replaceExistingAbilities = els.replaceAbilities.checked;
});

els.replacePassives.addEventListener("change", () => {
  const override = unitOverride();
  if (override) override.replaceExistingPassives = els.replacePassives.checked;
});

els.addAbilityBtn.addEventListener("click", () => {
  if (state.unit) els.abilityDialog.showModal();
});

els.effectsBtn.addEventListener("click", () => {
  state.effectTarget = null;
  els.effectSearch.value = "";
  els.effectKind.value = "";
  renderEffects();
  els.effectsDialog.showModal();
});

els.effectSearch.addEventListener("input", renderEffects);
els.effectKind.addEventListener("change", renderEffects);
els.effectsDialog.addEventListener("close", () => {
  state.effectTarget = null;
  renderEffects();
});

els.iconsBtn.addEventListener("click", () => {
  state.iconTarget = null;
  renderIcons();
  els.iconsDialog.showModal();
});

els.iconSearch.addEventListener("input", renderIcons);
els.iconGroup.addEventListener("change", renderIcons);
els.skillSearch.addEventListener("input", renderSkills);
els.specializationSearch.addEventListener("input", renderSpecializations);
els.skillDialog.addEventListener("close", () => state.skillTarget = null);
els.specializationDialog.addEventListener("close", () => state.specializationTarget = null);

document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(item => item.classList.remove("active"));
    tab.classList.add("active");
    state.currentTab = tab.dataset.tab;
    renderCurrentData();
  });
});

els.saveBtn.addEventListener("click", async () => {
  const endpoint = state.mode === "heroes"
    ? "/api/hero_overrides"
    : state.mode === "laws"
      ? "/api/law_overrides"
      : "/api/overrides";
  const payload = state.mode === "heroes" ? state.heroOverrides : state.mode === "laws" ? state.lawOverrides : state.overrides;
  const result = await api(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  els.saveBtn.textContent = `Saved ${result.path}`;
  setTimeout(() => els.saveBtn.textContent = "Save Overrides", 2400);
});

async function init() {
  const data = await api("/api/state");
  state.manifests = data.manifests;
  state.templates = data.templates;
  await loadEffects();
  await loadIcons();
  await loadHeroSkills();
  await loadHeroSpecializations();
  state.faction = state.manifests[0]?.factionSid || null;
  if (state.faction) {
    await loadOverrides();
    await loadHeroOverrides();
    await loadLawOverrides();
    await loadCurrentLawData();
    state.unit = currentFaction()?.units?.[0] || null;
    state.hero = currentFaction()?.heroes?.[0] || null;
    state.law = state.currentLawData?.laws?.[0] || null;
    await loadCurrentUnitData();
    await loadCurrentHeroData();
  }
  render();
}

init().catch(error => {
  document.body.innerHTML = `<main class="panel" style="margin:24px"><h1>Ability editor failed to load</h1><p>${error.message}</p></main>`;
});
