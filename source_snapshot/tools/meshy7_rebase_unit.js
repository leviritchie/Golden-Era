// Meshy 7 full rebase: Image-to-3D (High Detail / Meshy 7 Flagship) + 10K remesh + Smart Rig + GLB download.
// Meshy 7 bundles PBR texture in mesh gen (~20 credits). Separate 4K texture step usually skipped.
// Remesh (free) required before rig — Meshy 7 outputs >300K polys.
// Smart Rig UI: animate-rig-btn → NEW Smart Rig (Beta) → animate-next-btn → animate-confirm-btn.
// Playwright MCP: run via filename= under C:/Users/<user>/.playwright-mcp/ (see meshy7_full_unit_template.js).

async function processMeshy7Unit(page, sid, stillPath, options = {}) {
  const out = { sid, model: 'meshy7' };
  const characterType = options.characterType || 'Humanoid'; // Quadruped for mammoth etc.
  const credits = async () => parseInt((await page.locator('[data-testid=header-credit-btn]').innerText()).trim(), 10);
  const waitCard = async (prevId, max = 24, interval = 20000) => {
    for (let i = 0; i < max; i++) {
      if (i) await page.waitForTimeout(interval);
      const fc = await page.evaluate(() => {
        const c = document.querySelector('[data-testid=assets-card]');
        const img = c && c.querySelector('img[src*="/tasks/"]');
        const id = img && (img.src.match(/tasks\/([a-f0-9-]{13})/) || [])[1];
        const text = c ? c.innerText.replace(/\s+/g, ' ').trim() : '';
        return { id, text, pct: (text.match(/(\d+)%/) || [])[1] };
      });
      if (fc.id && fc.id !== prevId && !fc.pct && !/%/.test(fc.text)) return fc.id;
      if (/fail/i.test(fc.text)) throw new Error('task failed: ' + JSON.stringify(fc));
    }
    throw new Error('task timeout');
  };
  const waitGray = async () => {
    for (let i = 0; i < 25; i++) {
      if (i) await page.waitForTimeout(15000);
      const fc = await page.evaluate(() => {
        const c = document.querySelector('[data-testid=assets-card]');
        const img = c && c.querySelector('img[src*="/tasks/"]');
        const id = img && (img.src.match(/tasks\/([a-f0-9-]{13})/) || [])[1];
        const text = c ? c.innerText.replace(/\s+/g, ' ').trim() : '';
        return { id, text, pct: (text.match(/(\d+)%/) || [])[1] };
      });
      if (fc.id && !fc.pct && !/%/.test(fc.text)) return fc.id;
      if (/fail/i.test(fc.text)) throw new Error('gray failed: ' + JSON.stringify(fc));
    }
    throw new Error('gray timeout');
  };
  const doRemesh = async (meshId) => {
    await page.locator('[data-testid=animate-rig-btn]').first().click();
    await page.waitForTimeout(1500);
    const dlg = await page.evaluate(() => (document.querySelector('[role=dialog]') || {}).innerText || '');
    if (!/Target Polycount/i.test(dlg)) {
      await page.keyboard.press('Escape');
      return meshId;
    }
    await page.getByRole('radio', { name: '10K' }).click({ force: true }).catch(() => {});
    await page.waitForTimeout(300);
    await page.locator('[data-testid=remesh-texture-confirm-btn]').click();
    await page.waitForTimeout(5000);
    const remeshId = await waitCard(meshId, 20, 15000);
    out.remeshId = remeshId;
    await page.locator(`[data-testid=assets-card]:has(img[src*="${remeshId}"])`).first().click({ force: true });
    await page.waitForTimeout(2000);
    return remeshId;
  };
  const doSmartRig = async (meshId) => {
    await page.locator('[data-testid=animate-rig-btn]').first().click();
    await page.waitForTimeout(2000);
    const dlg = await page.evaluate(() => (document.querySelector('[role=dialog]') || {}).innerText || '');
    if (/Target Polycount/i.test(dlg)) throw new Error('remesh still required');
    if (characterType !== 'Humanoid') {
      await page.getByRole('radio', { name: characterType }).click({ force: true }).catch(() => {});
    }
    const smart = await page.evaluate(() => {
      const dialog = document.querySelector('[role=dialog]');
      if (!dialog) return null;
      const el = Array.from(dialog.querySelectorAll('*')).find(e => ((e.innerText || '').replace(/\s+/g, ' ').trim() === 'NEW Smart Rig (Beta)'));
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
    });
    if (smart) {
      await page.mouse.click(smart.x, smart.y);
      await page.waitForTimeout(1000);
    }
    if (await page.locator('[data-testid=animate-next-btn]').count()) {
      await page.locator('[data-testid=animate-next-btn]').click();
      await page.waitForTimeout(1500);
    }
    if (await page.locator('[data-testid=animate-confirm-btn]').count()) {
      await page.locator('[data-testid=animate-confirm-btn]').click();
    }
    await page.waitForTimeout(5000);
    return await waitCard(meshId, 24, 20000);
  };

  await page.keyboard.press('Escape');
  await page.waitForTimeout(300);
  await page.locator('[data-testid=workspace-sidebar-model-btn]').click();
  await page.waitForTimeout(1200);
  await page.locator('[data-testid=workspace-image-to-3d-tab]').click().catch(() => {});
  await page.waitForTimeout(300);
  await page.locator('[data-testid=workspace-model-type-standard]').click({ force: true });
  await page.waitForTimeout(400);
  const modelLabel = await page.locator('[data-testid=workspace-ai-model-select]').innerText();
  if (!/Meshy 7/i.test(modelLabel)) return { ...out, error: 'meshy7 not selected', modelLabel };
  out.modelLabel = modelLabel.replace(/\s+/g, ' ').trim();

  const rem = page.locator('[data-testid=workspace-uploader-remove-background-btn]');
  if (await rem.count()) await rem.first().click({ force: true }).catch(() => {});
  await page.waitForTimeout(400);
  await page.locator('input[type=file]').first().setInputFiles(stillPath);
  await page.waitForTimeout(1200);

  out.creditsBefore = await credits();
  if (out.creditsBefore < 20) return { ...out, error: 'insufficient credits', need: 20 };

  const gb = await page.evaluate(() => {
    const b = document.querySelector('[data-testid=workspace-generate-btn]');
    const r = b.getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  });
  await page.mouse.click(gb.x, gb.y);
  await page.waitForTimeout(3000);
  out.creditsAfterGen = await credits();
  out.creditsSpentMesh = out.creditsBefore - out.creditsAfterGen;
  out.creditsSpentTex = 0;
  out.textureStep = 'skipped_meshy7_bundled';

  out.grayId = await waitGray();
  await page.locator(`[data-testid=assets-card]:has(img[src*="${out.grayId}"])`).first().click({ force: true });
  await page.waitForTimeout(3000);
  out.paintedId = out.grayId;

  await page.locator('[data-testid=viewer-jump-to-animate-btn]').click();
  await page.waitForTimeout(3000);

  let meshId = out.paintedId;
  meshId = await doRemesh(meshId);
  out.rigId = await doSmartRig(meshId);

  const card = page.locator(`[data-testid=assets-card]:has(img[src*="${out.rigId}"])`).first();
  await card.hover();
  await page.waitForTimeout(600);
  await card.locator('[data-testid=assets-hover-menu-btn]').click({ force: true });
  await page.waitForTimeout(800);
  const downloadPromise = page.waitForEvent('download', { timeout: 120000 });
  await page.getByRole('menuitem', { name: 'Download' }).click();
  await page.waitForTimeout(1500);
  await page.locator('[data-testid=download-confirm-btn]').click();
  const download = await downloadPromise;
  const dlPath = `C:/Users/<user>/.playwright-mcp/${sid}_smartrigged.glb`;
  await download.saveAs(dlPath);
  out.downloadPath = dlPath;
  out.creditsEnd = await credits();
  out.creditsSpentTotal = out.creditsBefore - out.creditsEnd;
  return out;
}
