(() => {
  const state = {
    catalog: null,
    faction: "all",
    tier: "all",
    kind: "all",
    identityOnly: false,
    query: "",
    selectedSid: null,
  };

  const els = {
    heroStats: document.getElementById("heroStats"),
    factionFilters: document.getElementById("factionFilters"),
    tierFilters: document.getElementById("tierFilters"),
    kindFilters: document.getElementById("kindFilters"),
    identityOnly: document.getElementById("identityOnly"),
    searchInput: document.getElementById("searchInput"),
    resultCount: document.getElementById("resultCount"),
    unitList: document.getElementById("unitList"),
    detailPane: document.getElementById("detailPane"),
    generatedMeta: document.getElementById("generatedMeta"),
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function portraitUrl(unit) {
    return unit.portrait || `/portraits/${unit.sid}.png`;
  }

  function matchesQuery(unit, query) {
    if (!query) return true;
    const hay = [
      unit.name,
      unit.sid,
      unit.factionLabel,
      unit.branch,
      unit.sourceMechanic,
      unit.hireCost,
      ...(unit.actives || []).flatMap((a) => [a.name, a.description, a.buffSid, ...(a.tags || [])]),
      ...(unit.passives || []).flatMap((p) => [p.name, p.description, p.logicLabel]),
      ...(unit.altAttacks || []).flatMap((a) => [a.name, a.description]),
    ]
      .join(" ")
      .toLowerCase();
    return query.split(/\s+/).every((token) => token && hay.includes(token));
  }

  function filteredUnits() {
    const units = state.catalog?.units || [];
    return units.filter((unit) => {
      if (state.faction !== "all" && unit.factionSid !== state.faction) return false;
      if (state.tier !== "all" && String(unit.tier) !== String(state.tier)) return false;
      if (state.kind === "actives" && !unit.hasActives) return false;
      if (state.kind === "passives" && !(unit.passiveCount > 0)) return false;
      if (state.identityOnly && !unit.hasIdentityPassives) return false;
      if (!matchesQuery(unit, state.query)) return false;
      return true;
    });
  }

  function renderStats() {
    const stats = state.catalog?.stats || {};
    els.heroStats.innerHTML = [
      ["Units", stats.units ?? 0],
      ["With actives", stats.withActives ?? 0],
      ["Factions", stats.factions ?? 0],
    ]
      .map(
        ([label, value]) =>
          `<div class="stat"><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span></div>`
      )
      .join("");
    els.generatedMeta.textContent = `Generated ${state.catalog?.generated || "unknown"} · ${
      state.catalog?.source || "Core.zip"
    }`;
  }

  function makeChip(label, active, attrs = {}) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `chip${active ? " active" : ""}${attrs.className ? ` ${attrs.className}` : ""}`;
    button.textContent = label;
    if (attrs.dataset) {
      Object.entries(attrs.dataset).forEach(([key, value]) => {
        button.dataset[key] = value;
      });
    }
    button.addEventListener("click", attrs.onClick);
    return button;
  }

  function renderFilters() {
    els.factionFilters.innerHTML = "";
    els.factionFilters.appendChild(
      makeChip("All factions", state.faction === "all", {
        onClick: () => {
          state.faction = "all";
          refresh();
        },
      })
    );
    (state.catalog?.factions || []).forEach((faction) => {
      els.factionFilters.appendChild(
        makeChip(faction.label, state.faction === faction.sid, {
          className: "faction",
          dataset: { faction: faction.sid },
          onClick: () => {
            state.faction = faction.sid;
            refresh();
          },
        })
      );
    });

    els.tierFilters.innerHTML = "";
    ["all", 1, 2, 3, 4, 5, 6, 7].forEach((tier) => {
      const label = tier === "all" ? "All tiers" : `T${tier}`;
      els.tierFilters.appendChild(
        makeChip(label, String(state.tier) === String(tier), {
          onClick: () => {
            state.tier = tier;
            refresh();
          },
        })
      );
    });

    els.kindFilters.innerHTML = "";
    [
      ["all", "Any abilities"],
      ["actives", "Has active"],
      ["passives", "Has passive"],
    ].forEach(([value, label]) => {
      els.kindFilters.appendChild(
        makeChip(label, state.kind === value, {
          onClick: () => {
            state.kind = value;
            refresh();
          },
        })
      );
    });
  }

  function renderList() {
    const units = filteredUnits();
    els.resultCount.textContent = `${units.length} unit${units.length === 1 ? "" : "s"} shown`;

    if (!units.length) {
      els.unitList.innerHTML = `<p class="empty-note" style="padding:12px">No units match these filters.</p>`;
      return;
    }

    if (!units.some((unit) => unit.sid === state.selectedSid)) {
      state.selectedSid = units[0].sid;
    }

    els.unitList.innerHTML = units
      .map((unit) => {
        const active = unit.sid === state.selectedSid ? " active" : "";
        const activeBadge = unit.hasActives
          ? `<span class="badge active-kind">${unit.activeCount} active</span>`
          : "";
        const passiveBadge = unit.hasIdentityPassives
          ? `<span class="badge passive-kind">identity</span>`
          : "";
        return `
          <button class="unit-row${active}" data-sid="${escapeHtml(unit.sid)}" type="button">
            <img src="${escapeHtml(portraitUrl(unit))}" alt="" loading="lazy" onerror="this.style.opacity=0.25">
            <span class="meta">
              <span class="name">${escapeHtml(unit.name)}</span>
              <span class="sub">T${escapeHtml(unit.tier)} · ${escapeHtml(unit.factionLabel)} · ${escapeHtml(unit.hireCost)}</span>
            </span>
            <span class="badges">${activeBadge}${passiveBadge}</span>
          </button>
        `;
      })
      .join("");

    els.unitList.querySelectorAll(".unit-row").forEach((button) => {
      button.addEventListener("click", () => {
        state.selectedSid = button.dataset.sid;
        renderList();
        renderDetail();
      });
    });
  }

  function costPills(active) {
    const pills = [];
    if (active.dontUseEnergy) {
      pills.push(`<span class="pill">No Focus</span>`);
    } else if (active.focus != null) {
      pills.push(`<span class="pill focus">${escapeHtml(active.focus)} Focus</span>`);
    }
    if (active.cooldown != null) {
      pills.push(`<span class="pill cd">CD ${escapeHtml(active.cooldown)}</span>`);
    }
    if (active.rank != null) {
      pills.push(`<span class="pill">Rank ${escapeHtml(active.rank)}</span>`);
    }
    if (active.attackType) {
      pills.push(`<span class="pill">${escapeHtml(active.attackType)}</span>`);
    }
    if (active.charges != null && active.charges !== "") {
      pills.push(`<span class="pill">Charges ${escapeHtml(active.charges)}</span>`);
    }
    return pills.join("");
  }

  function renderAbilityCards(actives) {
    if (!actives?.length) {
      return `<p class="empty-note">No action-bar actives.</p>`;
    }
    return actives
      .map((active) => {
        const intended = active.intended
          ? `<div class="intended"><strong>Intended:</strong> ${escapeHtml(active.intended.name)} — ${escapeHtml(active.intended.description || "")}</div>`
          : "";
        const logic = active.logicLabel
          ? `<div class="logic"><strong>Logic:</strong> ${escapeHtml(active.logicLabel)}</div>`
          : "";
        return `
          <article class="ability">
            <div class="ability-top">
              <h4>${escapeHtml(active.name)}</h4>
              <div class="cost-pills">${costPills(active)}</div>
            </div>
            <p>${escapeHtml(active.description || "No English description in Core localization.")}</p>
            ${logic}
            ${intended}
          </article>
        `;
      })
      .join("");
  }

  function renderPassiveCards(passives) {
    if (!passives?.length) {
      return `<p class="empty-note">No passive cards.</p>`;
    }
    return passives
      .map((passive) => {
        const logic = passive.logicLabel
          ? `<div class="logic"><strong>Logic:</strong> ${escapeHtml(passive.logicLabel)}</div>`
          : "";
        return `
          <article class="ability${passive.generic ? " generic" : ""}">
            <div class="ability-top">
              <h4>${escapeHtml(passive.name)}</h4>
              <div class="cost-pills"><span class="pill">Passive</span></div>
            </div>
            <p>${escapeHtml(passive.description || "No English description in Core localization.")}</p>
            ${logic}
          </article>
        `;
      })
      .join("");
  }

  function renderAltCards(alts) {
    if (!alts?.length) return "";
    const cards = alts
      .map(
        (alt) => `
        <article class="ability generic">
          <div class="ability-top">
            <h4>${escapeHtml(alt.name)}</h4>
            <div class="cost-pills"><span class="pill">No Focus</span></div>
          </div>
          <p>${escapeHtml(alt.description || "Alternate attack mode.")}</p>
        </article>
      `
      )
      .join("");
    return `<section class="section"><h3>Alternate attacks</h3>${cards}</section>`;
  }

  function renderDetail() {
    const unit = (state.catalog?.units || []).find((row) => row.sid === state.selectedSid);
    if (!unit) {
      els.detailPane.innerHTML = `
        <div class="detail-empty">
          <h2>Select a unit</h2>
          <p>Pick a creature from the list to read its actives, passives, and costs.</p>
        </div>`;
      return;
    }

    const facts = [
      `Tier ${unit.tier}`,
      unit.hireCost ? `Hire ${unit.hireCost}` : null,
      unit.branch || null,
      unit.sourceMechanic ? `Source ${unit.sourceMechanic}` : null,
    ]
      .filter(Boolean)
      .map((fact) => `<span class="fact">${escapeHtml(fact)}</span>`)
      .join("");

    const notes = (unit.defaultAttackNotes || []).length
      ? `<section class="section"><h3>Default attack notes</h3><p class="empty-note">${escapeHtml(
          unit.defaultAttackNotes.join("; ")
        )}</p></section>`
      : "";

    els.detailPane.innerHTML = `
      <div class="detail-head">
        <img src="${escapeHtml(portraitUrl(unit))}" alt="${escapeHtml(unit.name)}" onerror="this.style.opacity=0.25">
        <div>
          <h2>${escapeHtml(unit.name)}</h2>
          <p class="sid">${escapeHtml(unit.factionLabel)} · <code>${escapeHtml(unit.sid)}</code></p>
          <div class="detail-facts">${facts}</div>
        </div>
      </div>
      <section class="section">
        <h3>Actives</h3>
        ${renderAbilityCards(unit.actives)}
      </section>
      <section class="section">
        <h3>Passives</h3>
        ${renderPassiveCards(unit.passives)}
      </section>
      ${renderAltCards(unit.altAttacks)}
      ${notes}
    `;
  }

  function refresh() {
    renderFilters();
    renderList();
    renderDetail();
  }

  function bindEvents() {
    let searchTimer = null;
    els.searchInput.addEventListener("input", () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        state.query = els.searchInput.value.trim().toLowerCase();
        refresh();
      }, 80);
    });
    els.identityOnly.addEventListener("change", () => {
      state.identityOnly = els.identityOnly.checked;
      refresh();
    });

    document.addEventListener("keydown", (event) => {
      if (event.target && ["INPUT", "TEXTAREA"].includes(event.target.tagName)) return;
      const units = filteredUnits();
      if (!units.length) return;
      const index = units.findIndex((unit) => unit.sid === state.selectedSid);
      if (event.key === "ArrowDown") {
        event.preventDefault();
        state.selectedSid = units[Math.min(units.length - 1, Math.max(0, index) + 1)].sid;
        refresh();
        els.unitList.querySelector(".unit-row.active")?.scrollIntoView({ block: "nearest" });
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        state.selectedSid = units[Math.max(0, index - 1)].sid;
        refresh();
        els.unitList.querySelector(".unit-row.active")?.scrollIntoView({ block: "nearest" });
      } else if (event.key === "/" && !event.ctrlKey && !event.metaKey) {
        event.preventDefault();
        els.searchInput.focus();
        els.searchInput.select();
      }
    });
  }

  async function boot() {
    bindEvents();
    const response = await fetch("./catalog.json", { cache: "no-store" });
    if (!response.ok) {
      els.detailPane.innerHTML = `
        <div class="detail-empty">
          <h2>Catalog JSON missing</h2>
          <p>Run <code>python tools/generate_homm3_custom_unit_ability_catalog.py</code> then restart the catalog server.</p>
        </div>`;
      return;
    }
    state.catalog = await response.json();
    state.selectedSid = state.catalog.units?.[0]?.sid || null;
    renderStats();
    refresh();
  }

  boot().catch((error) => {
    els.detailPane.innerHTML = `
      <div class="detail-empty">
        <h2>Failed to load catalog</h2>
        <p>${escapeHtml(error.message || String(error))}</p>
      </div>`;
  });
})();
