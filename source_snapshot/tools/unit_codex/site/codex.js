/* Golden Era Codex: renders data/codex.json (built by tools/unit_codex/export_codex.py).
   No framework, no build step: GitHub Pages serves this folder as-is. */
'use strict';

const $ = (sel, el = document) => el.querySelector(sel);
const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ESC[c]);
const ico = (id, cls = 'i') => `<svg class="${cls}" aria-hidden="true"><use href="#${id}"/></svg>`;
const plain = h => String(h || '').replace(/<br>/g, ' ').replace(/<[^>]+>/g, '').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
const fold = s => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
const fmtSigned = n => (n > 0 ? '+' + n : String(n).replace('-', '−'));

const STATS = [
  ['hp', 'HP'], ['offence', 'Attack'], ['defence', 'Defense'], ['damage', 'Damage'],
  ['moral', 'Morale'], ['luck', 'Luck'], ['initiative', 'Initiative'], ['speed', 'Speed'],
];
const KIND = { base: 'Base', upg: 'Upgrade', alt: 'Alternate', fusion: 'Fusion', neutral: 'Neutral' };
const CARD_KIND = { active: 'Active', alternate: 'Alternate attack', passive: 'Trait' };
const MOVE = { fly: 'Flying', ground: 'Ground', teleport: 'Teleport' };
const SECTION = {
  mains: 'Town hall', taverns: 'Tavern', markets: 'Market', artifactMarkets: 'Artifact market', hires: 'Dwelling',
  magicGuilds: 'Mage guild', banks: 'Economy & special', walls: 'Fortifications', graals: 'Grail structure',
  heroBonusBanks: 'Hero bonus', artifactChangers: 'Artifact forge', rebirthShrines: 'Shrine', manaFountains: 'Mana fountain',
  unitsConverters: 'Creature converter', intelligences: 'Intelligence', trainingRanges: 'Training', gyms: 'Training', lyceums: 'Lyceum',
};
const SECTION_GLYPH = { mains: 'b-mains', taverns: 'b-taverns', markets: 'b-markets', artifactMarkets: 'b-artifactMarkets', artifactChangers: 'b-artifactMarkets', magicGuilds: 'b-magicGuilds', manaFountains: 'b-magicGuilds', banks: 'b-banks', heroBonusBanks: 'b-banks', walls: 'b-walls', graals: 'b-graals' };
const RES = { gold: 'Gold', wood: 'Wood', ore: 'Ore', mercury: 'Mercury', crystals: 'Crystals', gemstones: 'Gemstones', dust: 'Dust' };

let D = null;
const F = {};          // faction key -> faction
const NODE = {};       // faction key -> { nodeId -> node }
let INDEX = [];
const st = { route: 'home', f: null, v: 'units', q: '', u: null, b: null, move: 'all', atk: 'all', el: 'all' };
let lastNonSearch = '#/';
let returnFocus = null;

/* ------------------------------------------------------------ boot */
fetch('data/codex.json')
  .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
  .then(data => { D = data; prepare(); bind(); route(); })
  .catch(err => {
    $('#main').innerHTML = `<div class="empty">The codex data could not be loaded (${esc(err.message)}).<br>If you opened this file directly, serve the folder over HTTP instead.</div>`;
  });

function prepare() {
  for (const f of D.factions) {
    F[f.key] = f;
    NODE[f.key] = Object.fromEntries(f.buildings.map(n => [n.id, n]));
    for (const n of f.buildings) n.unlocks = [];
    for (const n of f.buildings) for (const r of n.req) NODE[f.key][r]?.unlocks.push(n.id);
  }
  for (const u of Object.values(D.units)) {
    u.fkey = u.faction === 'neutral' ? 'neutral' : u.faction.replace(/^homm3_/, '');
    u.lineIds = u.line ? (D.units[u.line]?.upgrades ? [u.line, ...D.units[u.line].upgrades] : [u.id]) : [u.id];
  }
  INDEX = [];
  for (const u of Object.values(D.units)) {
    const f = F[u.fkey];
    INDEX.push({
      t: 'u', id: u.id, f: u.fkey, name: fold(u.name),
      cards: u.cards.map(c => ({ n: fold(c.name), d: fold(plain(c.desc)), raw: c })),
      extra: fold(`${fname(f)} tier ${u.tier} ${KIND[u.kind] || ''} ${MOVE[u.move] || ''} ${u.ranged ? 'ranged shooter' : 'melee'} ${u.class?.name || ''}`),
    });
  }
  for (const f of D.factions) for (const n of f.buildings) {
    INDEX.push({ t: 'b', id: n.id, f: f.key, name: fold(n.name), desc: fold(plain(n.desc)), extra: fold(`${fname(f)} ${SECTION[n.section] || n.section}`) });
  }
  renderRail();
  renderFoot();
}

function bind() {
  window.addEventListener('hashchange', route);
  const q = $('#q');
  let t = 0;
  q.addEventListener('input', () => {
    clearTimeout(t);
    t = setTimeout(() => {
      const v = q.value.trim();
      if (v) {
        const target = '#/search?q=' + encodeURIComponent(v);
        if (st.route === 'search') history.replaceState(null, '', target); else history.pushState(null, '', target);
        route();
      } else if (st.route === 'search') {
        location.hash = lastNonSearch;
      }
    }, 120);
  });
  document.addEventListener('keydown', e => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName);
    if (e.key === '/' && !typing) { e.preventDefault(); q.focus(); q.select(); }
    else if (e.key === 'Escape') {
      if (!$('#dialog').hidden) closeUnit();
      else if (document.activeElement === q && q.value) { q.value = ''; q.dispatchEvent(new Event('input')); }
    } else if (e.key === 'Tab' && !$('#dialog').hidden) trapFocus(e);
  });
  $('#scrim').addEventListener('click', closeUnit);
  document.addEventListener('click', e => {
    const el = e.target.closest('[data-u],[data-b],[data-set],[data-close]');
    if (!el) return;
    if (el.dataset.close !== undefined) { closeUnit(); return; }
    if (el.dataset.u) { e.preventDefault(); returnFocus = $('#dialog').hidden ? el : returnFocus; setParam('u', el.dataset.u); return; }
    if (el.dataset.b) {
      e.preventDefault();
      const [fk, id] = el.dataset.b.split('|');
      location.hash = `#/${fk}/town?b=${encodeURIComponent(id)}`;
      return;
    }
    if (el.dataset.set) {
      const [k, v] = el.dataset.set.split('=');
      st[k] = v;
      render();
    }
  });
}

/* ------------------------------------------------------------ routing */
function parseHash() {
  const h = location.hash.replace(/^#\/?/, '');
  const [path, query = ''] = h.split('?');
  const parts = path.split('/').filter(Boolean);
  const p = new URLSearchParams(query);
  return { parts, p };
}

function route() {
  const { parts, p } = parseHash();
  const prevF = st.f;
  st.u = p.get('u') && D.units[p.get('u')] ? p.get('u') : null;
  st.b = p.get('b');
  if (parts[0] === 'search') {
    st.route = 'search';
    st.q = p.get('q') || '';
    if ($('#q').value.trim() !== st.q) $('#q').value = st.q;
  } else if (parts[0] && F[parts[0]]) {
    st.route = 'faction';
    st.f = parts[0];
    st.v = parts[1] === 'town' && F[st.f].buildings.length ? 'town' : 'units';
    if (prevF !== st.f) { st.move = 'all'; st.atk = 'all'; st.el = 'all'; }
    lastNonSearch = location.hash.split('?')[0] || '#/';
  } else {
    st.route = 'home';
    st.f = null;
    lastNonSearch = '#/';
  }
  if (st.route !== 'search' && $('#q').value) $('#q').value = '';
  render();
  if (st.u) openUnit(st.u); else hideDialog();
}

function setParam(k, v) {
  const { parts, p } = parseHash();
  if (v == null) p.delete(k); else p.set(k, v);
  const qs = p.toString();
  location.hash = '#/' + parts.join('/') + (qs ? '?' + qs : '');
}

/* ------------------------------------------------------------ chrome */
function fname(f) { return f ? f.name.replace(/\s*\(homm3\)\s*$/i, '') : ''; }
function crest(f, cls = '') {
  return f.crest ? `<img class="${cls}" src="${esc(f.crest)}" alt="" loading="lazy">` : `<span class="crest-ph ${cls}">${ico(f.key === 'neutral' ? 'c-rune' : 'g-defence')}</span>`;
}
function unitCount(f) { return f.lines.reduce((n, l) => n + l.units.length, 0) + f.extras.length; }

function renderRail() {
  $('#rail').innerHTML = `<div class="rail-head">Factions</div>` + D.factions.map(f =>
    `<a href="#/${f.key}" data-key="${f.key}">${crest(f)}<span>${esc(fname(f))}</span><span class="n">${unitCount(f)}</span></a>`).join('');
}

function renderFoot() {
  $('#foot').innerHTML = `<p>Built from the Golden Era mod's own game data, <b>${esc(D.label)}</b>, on ${esc(D.generated)}. Every number and description here is read from the files the game loads.</p>
  <p>Golden Era is an unofficial fan mod for Heroes of Might and Magic: Olden Era. It is not affiliated with or endorsed by the game's publishers.</p>`;
}

function render() {
  for (const a of document.querySelectorAll('#rail a')) a.setAttribute('aria-current', String(a.dataset.key === st.f));
  const main = $('#main');
  if (st.route === 'search') main.innerHTML = renderSearch();
  else if (st.route === 'faction') main.innerHTML = renderFaction(F[st.f]);
  else main.innerHTML = renderHome();
  if (st.route === 'faction' && st.v === 'town') layoutTree();
  document.title = st.route === 'faction' ? `${fname(F[st.f])} · Golden Era Codex` : st.route === 'search' ? `Search: ${st.q} · Golden Era Codex` : 'Golden Era Codex';
}

/* ------------------------------------------------------------ home */
function renderHome() {
  const fac = D.factions.filter(f => f.key !== 'neutral');
  const lineUnits = fac.reduce((n, f) => n + f.lines.reduce((m, l) => m + l.units.length, 0), 0);
  const fusions = fac.reduce((n, f) => n + f.extras.length, 0);
  const neutral = F.neutral ? F.neutral.extras.length : 0;
  const blds = fac.reduce((n, f) => n + f.buildings.length, 0);
  return `<section class="hero frame">
    <h1>Golden Era Codex</h1>
    <p>Every custom creature, upgrade branch and town building in the Golden Era mod. Pick a faction, or search for a creature, an ability or a building. Press <kbd>/</kbd> to search from anywhere.</p>
    <div class="counts">
      <div><b>${fac.length}</b><span>factions</span></div>
      <div><b>${lineUnits}</b><span>town creatures</span></div>
      ${fusions ? `<div><b>${fusions}</b><span>fusion forms</span></div>` : ''}
      ${neutral ? `<div><b>${neutral}</b><span>neutral creatures</span></div>` : ''}
      <div><b>${blds}</b><span>building levels</span></div>
    </div>
  </section>
  <div class="fgrid">${D.factions.map(f => `<a class="fcard frame" href="#/${f.key}">${crest(f)}<span class="nm">${esc(fname(f))}</span>
    <span class="meta">${f.key === 'neutral' ? `${f.extras.length} creatures` : `${f.lines.length} dwellings · ${unitCount(f)} creatures`}</span></a>`).join('')}</div>`;
}

/* ------------------------------------------------------------ faction */
function renderFaction(f) {
  const chips = [];
  if (f.skill) chips.push(`<span class="chip"><b>Faction skill</b> ${esc(f.skill)}</span>`);
  if (f.biome) chips.push(`<span class="chip"><b>Native terrain</b> ${esc(f.biome)}</span>`);
  const head = `<section class="fhead frame">${crest(f)}<div><h1>${esc(fname(f))}</h1>${f.desc ? `<p>${f.desc}</p>` : ''}${chips.length ? `<div class="chips">${chips.join('')}</div>` : ''}</div></section>`;
  const tabs = f.buildings.length ? `<nav class="tabs" aria-label="View">
      <a href="#/${f.key}" ${st.v === 'units' ? 'aria-current="page"' : ''}>Creatures</a>
      <a href="#/${f.key}/town" ${st.v === 'town' ? 'aria-current="page"' : ''}>Town buildings</a></nav>` : '';
  if (st.v === 'town') return head + `<div class="toolbar">${tabs}</div>` + renderTown(f);
  const filters = `${seg('Movement', 'move', [['all', 'All'], ['ground', 'Ground'], ['fly', 'Flying']])}${seg('Attack', 'atk', [['all', 'All'], ['melee', 'Melee'], ['ranged', 'Ranged']])}`;
  return head + `<div class="toolbar">${tabs}${filters}</div>` + renderUnits(f);
}

function seg(label, key, opts) {
  return `<span class="seg-label">${label}</span><div class="seg" role="group" aria-label="${label}">${opts.map(([v, t]) =>
    `<button type="button" data-set="${key}=${v}" aria-pressed="${st[key] === v}">${t}</button>`).join('')}</div>`;
}

function passes(u) {
  if (st.move !== 'all' && (st.move === 'fly' ? u.move !== 'fly' : u.move === 'fly')) return false;
  if (st.atk !== 'all' && (st.atk === 'ranged') !== !!u.ranged) return false;
  return true;
}

function renderUnits(f) {
  let out = '';
  if (f.lines.length) {
    out += `<div class="lines">${f.lines.map(l => lineRow(f, l)).join('')}</div>`;
  }
  if (f.extras.length) {
    const isFusion = f.extras.some(id => D.units[id].kind === 'fusion');
    let ids = f.extras;
    let tools = '';
    if (isFusion) {
      const lineNames = f.lines.filter(l => ids.some(id => (D.units[id].parents || []).some(p => D.units[p]?.line === l.units[0])))
        .map(l => [l.units[0], D.units[l.units[0]].name.replace(/ Elemental$/, '')]);
      tools = `<div class="fusion-tools">${seg('Contains', 'el', [['all', 'Any'], ...lineNames])}</div>`;
      if (st.el !== 'all') ids = ids.filter(id => (D.units[id].parents || []).some(p => D.units[p]?.line === st.el));
    }
    const tiers = [...new Set(ids.map(id => D.units[id].tier))].sort((a, b) => a - b);
    out += `${isFusion ? `<h2 class="section-title">Elemental fusions</h2><p class="empty" style="padding:0 0 12px;text-align:center">Forms two Conflux elementals can fuse into during battle. ${ids.length} shown.</p>` : ''}${tools}
      ${tiers.map(t => `<div class="tier-group"><div class="label" style="margin:0 0 8px">Tier ${t}</div><div class="fusion-grid">${ids.filter(id => D.units[id].tier === t).map(id => unitCard(D.units[id])).join('')}</div></div>`).join('')}`;
  }
  return out || '<p class="empty">No creatures.</p>';
}

function lineRow(f, l) {
  const [baseId, ...ups] = l.units;
  const base = D.units[baseId];
  const node = NODE[f.key][`${l.dwelling}@1`];
  const anyPass = l.units.some(id => passes(D.units[id]));
  return `<section class="line frame ${anyPass ? '' : 'is-dim'}" aria-label="Tier ${l.tier}: ${esc(base.name)}">
    <div class="tier"><span class="t">Tier</span><span class="v">${l.tier ?? '?'}</span>
      ${base.growth ? `<span class="g" title="Weekly growth">${ico('g-growth')}+${base.growth}/wk</span>` : ''}
      ${node ? `<button class="linkbtn" style="font-size:13px" data-b="${f.key}|${esc(node.id)}">${esc(node.name)}</button>` : ''}</div>
    ${unitCard(base)}
    ${ups.length ? `<svg class="fork" viewBox="0 0 40 100" preserveAspectRatio="none" aria-hidden="true"><path d="M0 50 H18 M18 50 C24 50 26 30 40 30 M18 50 C24 50 26 70 40 70" fill="none" stroke="currentColor" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>
    <div class="branches"><span class="lbl">Upgrades to (pick one)</span>${ups.map(id => unitCard(D.units[id])).join('')}</div>` : ''}
  </section>`;
}

function stage(u, big = false) {
  const p = u.parents && D.units[u.parents[0]];
  const g = u.parents && D.units[u.parents[1]];
  const src = u.portrait || p?.portrait;
  const main = src ? `<img src="${esc(src)}" alt="${big ? esc(u.name) : ''}" loading="lazy">` : `<span class="ph">${ico(u.move === 'fly' ? 'c-wing' : 'g-offence')}</span>`;
  const inset = !u.portrait && g?.portrait ? `<span class="guest" title="${esc(g.name)}"><img src="${esc(g.portrait)}" alt="" loading="lazy"></span>` : '';
  return `<div class="stage">${main}${inset}</div>`;
}

function miniStats(u) {
  const s = u.stats;
  return `<div class="mini">
    <span title="HP">${ico('g-hp')}${s.hp ?? '?'}</span>
    <span title="Attack">${ico('g-offence')}${s.offence ?? '?'}</span>
    <span title="Defense">${ico('g-defence')}${s.defence ?? '?'}</span>
    <span title="Damage">${ico('g-damage')}${dmg(s)}</span></div>`;
}
const dmg = s => (s.damageMin === s.damageMax ? `${s.damageMin}` : `${s.damageMin}–${s.damageMax}`);

function costHtml(cost) {
  if (!cost?.length) return '<span class="none">Free</span>';
  return cost.map(c => `<span title="${esc(RES[c.res] || c.res)}">${ico('r-' + (RES[c.res] ? c.res : 'gold'))}${c.n.toLocaleString('en-US')}</span>`).join('');
}

function cardIcon(c, cls = '') {
  return `<span class="ic k-${c.kind} ${cls}">${c.icon ? `<img src="${esc(c.icon)}" alt="" loading="lazy">` : ico('c-' + c.glyph)}</span>`;
}

function unitCard(u) {
  const show = u.cards.filter(c => c.kind !== 'passive');
  const pick = (show.length ? show : u.cards).slice(0, 5);
  const tags = `${u.move === 'fly' ? `<span title="Flying">${ico('c-wing')}</span>` : ''}${u.ranged ? `<span title="Ranged">${ico('c-bow')}</span>` : ''}`;
  const parents = u.parents ? `<div class="parents">${u.parents.map(p => esc(D.units[p]?.name)).join(' + ')}</div>` : '';
  return `<button type="button" class="ucard ${passes(u) ? '' : 'is-dim'}" data-u="${u.id}" aria-label="${esc(u.name)}, ${KIND[u.kind] || ''} tier ${u.tier}">
    <span class="kind k-${u.kind}">${KIND[u.kind] || ''}</span><span class="tags">${tags}</span>
    ${stage(u)}
    <div class="body"><div class="nm">${esc(u.name)}</div>${parents}${miniStats(u)}
      <div class="cost">${costHtml(u.cost)}</div>
      <div class="abil">${pick.map(c => `<span title="${esc(c.name)}">${cardIcon(c)}</span>`).join('')}</div></div>
  </button>`;
}

/* ------------------------------------------------------------ unit window */
function openUnit(id) {
  const u = D.units[id];
  const dlg = $('#dialog');
  const line = u.line ? [u.line, ...(D.units[u.line].upgrades || [])].map(x => D.units[x]) : null;
  const base = line && u.kind !== 'base' ? line[0] : null;
  const f = F[u.fkey];
  const s = u.stats;
  const delta = k => {
    if (!base) return '';
    const a = k === 'damage' ? (s.damageMin + s.damageMax) / 2 : s[k];
    const b = k === 'damage' ? (base.stats.damageMin + base.stats.damageMax) / 2 : base.stats[k];
    if (a == null || b == null || a === b) return '';
    const d = Math.round((a - b) * 10) / 10;
    return `<span class="${d > 0 ? 'd-up' : 'd-down'}">${fmtSigned(d)}</span>`;
  };
  const statVal = k => (k === 'damage' ? dmg(s) : (k === 'moral' || k === 'luck') ? fmtSigned(s[k] ?? 0) : (s[k] ?? '?'));
  const facts = [
    `<span class="chip">${ico(u.move === 'fly' ? 'c-wing' : 'g-speed')} ${MOVE[u.move] || esc(u.move)}</span>`,
    `<span class="chip">${ico(u.ranged ? 'c-bow' : 'g-offence')} ${u.ranged ? 'Ranged' : 'Melee'}</span>`,
    s.numCounters != null ? `<span class="chip">${ico('g-numCounters')} ${s.numCounters} retaliation${s.numCounters === 1 ? '' : 's'}</span>` : '',
    s.shots != null ? `<span class="chip">${ico('g-shots')} ${s.shots} shots</span>` : '',
    `<span class="chip cost" style="display:inline-flex">${costHtml(u.cost)}</span>`,
    u.value ? `<span class="chip" title="The game's power rating for one creature">Value ${u.value.toLocaleString('en-US')}</span>` : '',
  ].join('');
  const cls = u.class ? `<div class="card"><span class="ic">${ico('c-class')}</span><div class="nm">${esc(u.class.name)}<span class="ty">Creature type</span></div><div class="ds">${u.class.desc}</div></div>` : '';
  const cards = u.cards.map(c => `<div class="card">${cardIcon(c)}<div class="nm">${esc(c.name)}<span class="ty k-${c.kind}">${CARD_KIND[c.kind]}${c.type ? ' · ' + esc(c.type) : ''}</span></div><div class="ds">${c.desc || '<span class="none">No description in the game data.</span>'}</div></div>`).join('');

  let right = stage(u, true);
  if (line && line.length > 1) {
    right += `<div class="switcher" role="group" aria-label="Upgrade branch">${line.map(x => `<button type="button" data-u="${x.id}" aria-pressed="${x.id === u.id}"><small>${KIND[x.kind]}</small><span>${esc(x.name)}</span></button>`).join('')}</div>`;
    right += compareTable(line, u.id);
  }
  if (u.parents) {
    right += `<div><div class="label" style="margin-bottom:6px">Fused from</div><div class="chips">${u.parents.map(p => pill(D.units[p])).join('')}</div></div>`;
  }
  const node = u.dwelling && NODE[u.fkey]?.[`${u.dwelling}@1`];
  if (node) right += `<div><button type="button" class="btn" data-b="${u.fkey}|${esc(node.id)}">${ico('b-default')} ${esc(node.name)} in the town tree</button></div>`;

  dlg.innerHTML = `<div class="title-bar"><span id="dlg-title">${esc(u.name)}</span><button type="button" class="x" data-close aria-label="Close">✕</button></div>
  <div class="dlg-body">
    <div class="dlg-left">
      <div class="metarow"><span class="grow">${u.growth ? `${ico('g-growth')} +${u.growth} per week` : `<span class="none">${esc(fname(f))}</span>`}</span><span class="label">${esc(KIND[u.kind] || '')} · Tier: ${u.tier ?? '?'}</span></div>
      <div class="statbar">${STATS.map(([k, label]) => `<div title="${label}">${ico('g-' + k)}<b>${statVal(k)}</b>${delta(k) || `<small>${label}</small>`}</div>`).join('')}</div>
      <div class="facts">${facts}</div>
      ${base ? `<p class="none" style="font-size:13.5px;margin:6px 0 0">Coloured numbers compare with the base ${esc(base.name)}.</p>` : ''}
      <h3 class="section-title">Abilities</h3>
      <div class="cards">${cls}${cards || '<p class="none">No ability cards.</p>'}</div>
    </div>
    <div class="dlg-right">${right}</div>
  </div>`;
  dlg.className = 'dialog frame';
  if (dlg.hidden) {
    returnFocus = returnFocus || document.activeElement;
    dlg.hidden = false;
    $('#scrim').hidden = false;
    document.body.style.overflow = 'hidden';
  }
  $('.dlg-body', dlg).scrollTop = 0;
  $('.x', dlg).focus({ preventScroll: true });
}

function compareTable(line, cur) {
  const rows = [
    ['HP', x => x.stats.hp], ['Attack', x => x.stats.offence], ['Defense', x => x.stats.defence],
    ['Damage', x => (x.stats.damageMin + x.stats.damageMax) / 2, x => dmg(x.stats)],
    ['Initiative', x => x.stats.initiative], ['Speed', x => x.stats.speed],
    ['Retaliations', x => x.stats.numCounters], ['Gold', x => x.cost.find(c => c.res === 'gold')?.n, null, true],
  ];
  return `<table class="cmp"><caption class="label" style="text-align:left;padding-bottom:4px">Compare the line</caption>
    <thead><tr><th></th>${line.map(x => `<th scope="col"${x.id === cur ? ' style="color:var(--gold-hi)"' : ''}>${esc(x.name)}</th>`).join('')}</tr></thead>
    <tbody>${rows.map(([label, get, show, noBest]) => {
      const vals = line.map(get);
      const best = noBest ? null : Math.max(...vals.filter(v => v != null));
      return `<tr><th scope="row">${label}</th>${line.map((x, i) => `<td class="${vals[i] === best && vals.filter(v => v === best).length < line.length ? 'best' : ''}">${vals[i] == null ? '–' : esc(show ? show(x) : vals[i].toLocaleString('en-US'))}</td>`).join('')}</tr>`;
    }).join('')}</tbody></table>`;
}

function pill(u) {
  return `<button type="button" class="pill" data-u="${u.id}">${u.portrait ? `<img src="${esc(u.portrait)}" alt="">` : `<span class="pi">${ico('g-offence')}</span>`}${esc(u.name)}</button>`;
}

function closeUnit() { setParam('u', null); }
function hideDialog() {
  const dlg = $('#dialog');
  if (dlg.hidden) return;
  dlg.hidden = true;
  $('#scrim').hidden = true;
  document.body.style.overflow = '';
  if (returnFocus && document.contains(returnFocus)) returnFocus.focus({ preventScroll: true });
  returnFocus = null;
}
function trapFocus(e) {
  const els = [...$('#dialog').querySelectorAll('button, [href], [tabindex]:not([tabindex="-1"])')];
  if (!els.length) return;
  const first = els[0], last = els[els.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}

/* ------------------------------------------------------------ town tree */
const COLW = 104, ROWH = 116, NODEW = 92, NODEH = 98;

function nodeIcon(f, n) {
  if (n.recruits.length) {
    const u = D.units[n.recruits[Math.min(n.level - 1, n.recruits.length - 1)]] || D.units[n.recruits[0]];
    if (u?.portrait) return `<img src="${esc(u.portrait)}" alt="" loading="lazy">`;
  }
  return ico(SECTION_GLYPH[n.section] || 'b-default');
}

function renderTown(f) {
  const nodes = f.buildings;
  const cols = Math.max(...nodes.map(n => n.x ?? 0)) + 1;
  const rows = Math.max(...nodes.map(n => n.y ?? 0)) + 1;
  const sel = st.b && NODE[f.key][st.b] ? NODE[f.key][st.b] : null;
  const anc = new Set(), desc = new Set();
  if (sel) {
    const up = id => { for (const r of NODE[f.key][id]?.req || []) if (!anc.has(r)) { anc.add(r); up(r); } };
    const down = id => { for (const r of NODE[f.key][id]?.unlocks || []) if (!desc.has(r)) { desc.add(r); down(r); } };
    up(sel.id); down(sel.id);
  }
  const tiles = nodes.map(n => {
    const cls = !sel ? '' : n.id === sel.id ? '' : anc.has(n.id) ? 'is-req' : desc.has(n.id) ? 'is-unl' : 'is-dim';
    return `<button type="button" class="node ${cls}" style="left:${(n.x ?? 0) * COLW + (COLW - NODEW) / 2}px;top:${(n.y ?? 0) * ROWH}px;height:${NODEH}px"
      data-b="${f.key}|${esc(n.id)}" aria-pressed="${sel?.id === n.id}" title="${esc(n.name)}">
      ${n.start ? '<span class="st" title="Built at game start"></span>' : ''}${n.levels > 1 ? `<span class="lv">${roman(n.level)}</span>` : ''}
      <span class="bi">${nodeIcon(f, n)}</span><span class="nn">${esc(n.name)}</span></button>`;
  }).join('');
  return `<div class="town">
    <div class="tree-wrap frame">
      <div class="legend" style="margin-bottom:12px"><span><span class="dot"></span>Built at start</span><span><i style="background:var(--gold)"></i>Required first</span><span><i style="background:#6c8fc7"></i>Unlocked by it</span><span class="none">Select a building to trace its chain.</span></div>
      <div class="tree" id="tree" data-f="${f.key}" style="width:${cols * COLW}px;height:${(rows - 1) * ROWH + NODEH}px">
        <svg class="edges" id="edges" width="${cols * COLW}" height="${(rows - 1) * ROWH + NODEH}" aria-hidden="true"></svg>${tiles}</div>
    </div>
    ${sel ? buildingDetail(f, sel) : `<div class="bdetail frame"><h2>${esc(fname(f))} town</h2><p class="desc">${nodes.length} building levels in ${new Set(nodes.map(n => n.sid)).size} structures. Each tile is one level as the in-game build screen lays it out; select one for its cost, requirements and what it unlocks.</p></div>`}
  </div>`;
}

function layoutTree() {
  const tree = $('#tree');
  if (!tree) return;
  const fk = tree.dataset.f;
  const map = NODE[fk];
  const sel = st.b && map[st.b] ? map[st.b] : null;
  const anc = new Set(), desc = new Set();
  if (sel) {
    const up = id => { for (const r of map[id]?.req || []) if (!anc.has(r)) { anc.add(r); up(r); } };
    const down = id => { for (const r of map[id]?.unlocks || []) if (!desc.has(r)) { desc.add(r); down(r); } };
    up(sel.id); down(sel.id);
  }
  const cx = n => (n.x ?? 0) * COLW + COLW / 2;
  const top = n => (n.y ?? 0) * ROWH;
  const paths = [];
  for (const n of Object.values(map)) {
    for (const rid of n.req) {
      const r = map[rid];
      if (!r) continue;
      let d;
      if (top(n) > top(r)) {
        const y1 = top(r) + NODEH, y2 = top(n), m = Math.max(14, (y2 - y1) / 2);
        d = `M${cx(r)} ${y1} C${cx(r)} ${y1 + m} ${cx(n)} ${y2 - m} ${cx(n)} ${y2}`;
      } else {
        const dir = cx(n) > cx(r) ? 1 : -1;
        const x1 = cx(r) + dir * NODEW / 2, x2 = cx(n) - dir * NODEW / 2, y1 = top(r) + NODEH / 2, y2 = top(n) + NODEH / 2;
        d = `M${x1} ${y1} C${(x1 + x2) / 2} ${y1} ${(x1 + x2) / 2} ${y2} ${x2} ${y2}`;
      }
      let cls = '';
      if (sel && (anc.has(rid) && (anc.has(n.id) || n.id === sel.id))) cls = 'on-req';
      else if (sel && (desc.has(n.id) && (desc.has(rid) || rid === sel.id))) cls = 'on-unl';
      paths.push(`<path class="${cls}" d="${d}"/>`);
    }
  }
  // highlighted edges last so they draw on top
  paths.sort((a, b) => (a.includes('class=""') ? 0 : 1) - (b.includes('class=""') ? 0 : 1));
  $('#edges').innerHTML = paths.join('');
  const pressed = tree.querySelector('[aria-pressed="true"]');
  if (pressed) pressed.scrollIntoView({ block: 'nearest', inline: 'center' });
}

function roman(n) { return ['', 'I', 'II', 'III', 'IV', 'V', 'VI'][n] || String(n); }

function buildingDetail(f, n) {
  const map = NODE[f.key];
  const nodePill = id => {
    const m = map[id];
    if (!m) return `<span class="chip">${esc(id)}</span>`;
    return `<button type="button" class="pill" data-b="${f.key}|${esc(m.id)}"><span class="pi">${m.recruits.length ? nodeIcon(f, m) : ico(SECTION_GLYPH[m.section] || 'b-default')}</span>${esc(m.name)}</button>`;
  };
  const recruits = n.recruits.map(id => D.units[id]).filter(Boolean);
  return `<section class="bdetail frame" aria-live="polite">
    <h2>${esc(n.name)}</h2>
    <div class="sub">${esc(SECTION[n.section] || n.section)}${n.levels > 1 ? ` · level ${n.level} of ${n.levels}` : ''}${n.start ? ' · built at game start' : ''}</div>
    ${n.desc ? `<p class="desc">${n.desc}</p>` : ''}
    <dl>
      <dt>Cost</dt><dd class="cost">${n.start ? '<span class="none">Already built</span>' : costHtml(n.cost)}</dd>
      <dt>Requires</dt><dd>${n.req.length ? n.req.map(nodePill).join('') : '<span class="none">Nothing</span>'}</dd>
      <dt>Unlocks</dt><dd>${n.unlocks.length ? n.unlocks.map(nodePill).join('') : '<span class="none">Nothing further</span>'}</dd>
      ${recruits.length ? `<dt>Recruits</dt><dd>${recruits.map(pill).join('')}</dd>` : ''}
      ${n.growth ? `<dt>Growth</dt><dd>+${n.growth} creatures per week</dd>` : ''}
    </dl>
  </section>`;
}

/* ------------------------------------------------------------ search */
function hl(text, toks) {
  let out = esc(text);
  for (const t of toks) {
    if (!t) continue;
    const re = new RegExp(esc(t).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
    out = out.replace(re, m => `<mark>${m}</mark>`);
  }
  return out;
}

function snippet(text, toks, len = 150) {
  const f = fold(text);
  let i = -1;
  for (const t of toks) { i = f.indexOf(t); if (i >= 0) break; }
  if (i < 0 || text.length <= len) return text.length > len ? text.slice(0, len) + '…' : text;
  let start = Math.max(0, i - 40), end = Math.min(text.length, start + len);
  if (start) { const sp = text.indexOf(' ', start); if (sp >= 0 && sp < i) start = sp + 1; }
  if (end < text.length) { const sp = text.lastIndexOf(' ', end); if (sp > i) end = sp; }
  return (start ? '…' : '') + text.slice(start, end) + (end < text.length ? '…' : '');
}

function renderSearch() {
  const toks = fold(st.q).split(/\s+/).filter(Boolean);
  if (!toks.length) return '<p class="empty">Type to search.</p>';
  const units = [], blds = [];
  for (const e of INDEX) {
    let score = 0, ok = true, hit = null;
    for (const t of toks) {
      let s = 0;
      if (e.name.includes(t)) s = e.name.startsWith(t) ? 30 : 20;
      if (e.t === 'u') {
        for (const c of e.cards) {
          if (c.n.includes(t)) { s = Math.max(s, 12); hit = hit || c.raw; }
          else if (c.d.includes(t)) { s = Math.max(s, 4); hit = hit || c.raw; }
        }
      } else if (e.desc.includes(t)) s = Math.max(s, 4);
      if (!s && e.extra.includes(t)) s = 2;
      if (!s) { ok = false; break; }
      score += s;
    }
    if (!ok) continue;
    (e.t === 'u' ? units : blds).push({ e, score, hit });
  }
  units.sort((a, b) => b.score - a.score || D.units[a.e.id].tier - D.units[b.e.id].tier);
  blds.sort((a, b) => b.score - a.score);
  if (!units.length && !blds.length) return `<div class="results"><h2>No matches for “${esc(st.q)}”</h2><p class="none">Try a creature name, an ability such as “stun” or “retaliation”, or a building.</p></div>`;
  const UL = 80, BL = 40;
  const uRows = units.slice(0, UL).map(({ e, hit }) => {
    const u = D.units[e.id];
    const sub = hit && !e.name.includes(toks[0])
      ? `<b>${hl(hit.name, toks)}</b> — ${hl(snippet(plain(hit.desc), toks), toks)}`
      : esc(u.cards.filter(c => c.kind !== 'passive').map(c => c.name).join(' · ') || u.cards.map(c => c.name).join(' · '));
    return `<button type="button" class="rrow" data-u="${u.id}"><span class="th">${u.portrait ? `<img src="${esc(u.portrait)}" alt="" loading="lazy">` : ico('g-offence')}</span>
      <span><span class="t1">${hl(u.name, toks)}</span><span class="t2">${sub}</span></span>
      <span class="t3">${esc(fname(F[u.fkey]))}<br>${KIND[u.kind] || ''} · tier ${u.tier}</span></button>`;
  }).join('');
  const bRows = blds.slice(0, BL).map(({ e }) => {
    const f = F[e.f];
    const n = NODE[e.f][e.id];
    return `<button type="button" class="rrow" data-b="${e.f}|${esc(n.id)}"><span class="th">${nodeIcon(f, n)}</span>
      <span><span class="t1">${hl(n.name, toks)}</span><span class="t2">${hl(snippet(plain(n.desc), toks), toks)}</span></span>
      <span class="t3">${esc(fname(f))}<br>${esc(SECTION[n.section] || n.section)}</span></button>`;
  }).join('');
  return `<div class="results">
    ${units.length ? `<div class="grp"><h2>Creatures <span class="none">(${units.length}${units.length > UL ? `, first ${UL} shown` : ''})</span></h2><div class="rlist">${uRows}</div></div>` : ''}
    ${blds.length ? `<div class="grp"><h2>Buildings <span class="none">(${blds.length}${blds.length > BL ? `, first ${BL} shown` : ''})</span></h2><div class="rlist">${bRows}</div></div>` : ''}
  </div>`;
}
