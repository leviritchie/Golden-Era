// Sibling retexture (10cr) + Smart Rig + download pipeline.
// Usage via browser_run_code_unsafe filename=... with UNIT_SID, BASE_TASK_SHORT, STILL_PATH set.
const UNIT_SID = 'h3_infernal_troglodyte';
const BASE_TASK_SHORT = '01a01352-8c0a'; // painted/textured base card task short prefix
const STILL_PATH = 'C:/Users/<user>/.playwright-mcp/h3_infernal_troglodyte.png';
const DOWNLOAD_PATH = `C:/Users/<user>/.playwright-mcp/${UNIT_SID}_smartrigged.glb`;
const EXPECT_VERTS = null; // optional pin e.g. '6076'

async function credits(page) {
  const t = (await page.locator('[data-testid=header-credit-btn]').innerText()).trim();
  return parseInt(t, 10);
}

function vertNum(s) {
  return ((s || '').match(/[\d,]+/) || [''])[0].replace(/,/g, '');
}

async function verts(page) {
  return page.evaluate(() => (document.body.innerText.match(/Vertices\s*[\n\r]*[\d,]+/) || [])[0]);
}

async function paginateAllAssets(page) {
  // Go to page 1, then click next until disabled
  const first = page.locator('button').filter({ hasText: /^1$/ }).first();
  if (await first.count()) await first.click({ force: true }).catch(() => {});
  await page.waitForTimeout(800);
  for (let p = 0; p < 50; p++) {
    const next = page.locator('button').filter({ has: page.locator('svg') }).last();
    const disabled = await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button'));
      const nav = btns.filter(b => b.closest('[class*="pagination"]') || /^\d+$/.test((b.innerText||'').trim()));
      const nextBtn = nav[nav.length - 1];
      return nextBtn ? nextBtn.disabled : true;
    });
    if (disabled) break;
    await page.locator('button:not([disabled])').filter({ hasText: /^\d+$/ }).last().click({ force: true }).catch(() => {});
    await page.waitForTimeout(600);
  }
}

async function openCardByTaskShort(page, taskShort) {
  await page.keyboard.press('Escape');
  await page.waitForTimeout(400);
  // Try direct URL first
  const fullUrl = `https://www.meshy.ai/workspace?taskId=${taskShort}`;
  // search via assets
  const search = page.locator('[data-testid=assets-search-input], input[placeholder*="Search"]').first();
  if (await search.count()) {
    await search.fill('');
    await page.waitForTimeout(200);
    const respP = page.waitForResponse(r => /api.*tasks|assets|search/i.test(r.url()) && r.status() === 200, { timeout: 15000 }).catch(() => null);
    await search.fill(taskShort.slice(0, 8));
    await page.waitForTimeout(1500);
    await respP;
  }
  let box = await page.evaluate((id) => {
    const img = document.querySelector(`img[src*="${id}"]`);
    if (!img) return null;
    const r = img.getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height * 0.62 };
  }, taskShort);
  if (!box) {
    // paginate all pages looking for task short
    for (let pageNum = 1; pageNum <= 40; pageNum++) {
      box = await page.evaluate((id) => {
        const img = document.querySelector(`img[src*="${id}"]`);
        if (!img) return null;
        const r = img.getBoundingClientRect();
        return { x: r.x + r.width / 2, y: r.y + r.height * 0.62 };
      }, taskShort);
      if (box) break;
      const nextBtn = page.locator('button:not([disabled])').filter({ hasText: /^\d+$/ });
      const cur = await page.evaluate(() => {
        const t = document.body.innerText.match(/(\d+)\/(\d+)/);
        return t ? { cur: +t[1], total: +t[2] } : null;
      });
      if (!cur || cur.cur >= cur.total) break;
      await page.locator('button').filter({ hasText: String(cur.cur + 1) }).first().click({ force: true }).catch(() => {});
      await page.waitForTimeout(800);
    }
  }
  if (!box) return { error: 'card not found', taskShort };
  await page.mouse.click(box.x, box.y);
  await page.waitForTimeout(3000);
  return { opened: taskShort };
}

async function doRetexture4K(page, stillPath) {
  const retex = page.locator('[data-testid=viewer-retexture-btn]');
  if (await retex.count()) await retex.click({ force: true });
  else await page.locator('[data-testid=viewer-edit-texture-btn]').first().click({ force: true });
  await page.waitForTimeout(1500);
  const imgTab = page.getByText('Image Input', { exact: true }).first();
  if (await imgTab.count()) await imgTab.click({ force: true });
  const pbr = page.getByText('Generate PBR Maps', { exact: true });
  if (await pbr.count()) await pbr.click({ force: true });
  const fourk = page.locator('[data-testid=texture-resolution-4k-btn]');
  for (let i = 0; i < 8; i++) {
    if ((await fourk.getAttribute('aria-checked')) === 'true') break;
    await fourk.click({ force: true });
    await page.waitForTimeout(200);
  }
  const chooserP = page.waitForEvent('filechooser', { timeout: 15000 });
  await page.getByText('Re-upload', { exact: true }).first().click({ force: true });
  const chooser = await chooserP;
  await chooser.setFiles(stillPath);
  await page.waitForTimeout(1500);
  const cost = await page.evaluate(() => {
    const dlg = document.querySelector('[role=dialog]');
    const t = dlg ? dlg.innerText : document.body.innerText;
    const m = t.match(/(\d+)\s*(?:credit|cr)/i) || t.match(/[\n\r](\d+)[\n\r]/);
    return m ? +m[1] : null;
  });
  if (cost && cost > 10) return { error: 'texture cost >10', cost };
  const before = await credits(page);
  await page.locator('[data-testid=viewer-confirm-texture-btn]').click({ force: true });
  await page.waitForTimeout(5000);
  const after = await credits(page);
  const spent = before - after;
  if (spent !== 10) return { error: 'credit drop not 10', before, after, spent };
  return { before, after, spent };
}

async function waitNewPaintCard(page, baseShort, timeout = 20) {
  for (let i = 0; i < timeout; i++) {
    if (i) await page.waitForTimeout(15000);
    const fc = await page.evaluate((gid) => {
      const c = document.querySelector('[data-testid=assets-card]');
      const img = c && c.querySelector('img[src*="/tasks/"]');
      const id = img && (img.src.match(/tasks\/([a-f0-9-]{13})/) || [])[1];
      const text = c ? c.innerText.replace(/\s+/g, ' ').trim() : '';
      return { id, text, pct: (text.match(/(\d+)%/) || [])[1] };
    }, baseShort);
    if (fc.id && fc.id !== baseShort && !fc.pct && !/%/.test(fc.text)) return fc.id;
    if (/fail/i.test(fc.text)) return { error: 'paint failed', fc };
  }
  return { error: 'paint timeout' };
}

async function maybeRemesh(page, paintNum) {
  const v = vertNum(await verts(page));
  if (+v <= 15000) return { remesh: false, verts: v };
  // remesh 10K via bottom bar if available
  const remeshBtn = page.locator('[data-testid=viewer-remesh-btn], [data-testid=remesh-btn]').first();
  if (!(await remeshBtn.count())) return { remesh: false, verts: v, warn: 'high poly no remesh btn' };
  await remeshBtn.click({ force: true });
  await page.waitForTimeout(2000);
  const tenk = page.getByText('10K', { exact: true }).first();
  if (await tenk.count()) await tenk.click({ force: true });
  await page.locator('[data-testid=remesh-confirm-btn], [data-testid=viewer-confirm-remesh-btn]').first().click({ force: true }).catch(() => {});
  await page.waitForTimeout(20000);
  return { remesh: true, verts: vertNum(await verts(page)) };
}

async function smartRig(page, paintedId, paintNum) {
  await page.locator('[data-testid=viewer-jump-to-animate-btn]').click();
  await page.waitForTimeout(5000);
  const vAnim = await verts(page);
  if (!vAnim || !vAnim.includes(paintNum)) return { error: 'animate jump wrong verts', vAnim };
  await page.locator('[data-testid=viewer-bottom-bar]').locator('[data-testid=animate-rig-btn]').click();
  await page.waitForTimeout(2000);
  const smart = await page.evaluate(() => {
    const dialog = document.querySelector('[role=dialog]');
    const el = Array.from(dialog.querySelectorAll('*')).find(e => ((e.innerText || '').replace(/\s+/g, ' ').trim() === 'NEW Smart Rig (Beta)'));
    const r = el.getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  });
  await page.mouse.click(smart.x, smart.y);
  await page.waitForTimeout(1000);
  if (!(await verts(page)).includes(paintNum)) return { error: 'verts changed pre-rig' };
  await page.locator('[data-testid=animate-confirm-btn]').click();
  await page.waitForTimeout(5000);
  for (let i = 0; i < 24; i++) {
    if (i) await page.waitForTimeout(20000);
    const fc = await page.evaluate((pid) => {
      const c = document.querySelector('[data-testid=assets-card]');
      const img = c && c.querySelector('img[src*="/tasks/"]');
      const id = img && (img.src.match(/tasks\/([a-f0-9-]{13})/) || [])[1];
      const text = c ? c.innerText.replace(/\s+/g, ' ').trim() : '';
      return { id, text, pct: (text.match(/(\d+)%/) || [])[1] };
    }, paintedId);
    if (fc.id && fc.id !== paintedId && !fc.pct && !/%/.test(fc.text)) return { rigId: fc.id };
    if (/fail/i.test(fc.text)) return { error: 'rig failed', fc };
  }
  return { error: 'rig timeout' };
}

async function downloadRig(page, rigId, destPath) {
  const card = page.locator(`[data-testid=assets-card]:has(img[src*="${rigId}"])`).first();
  await card.hover();
  await page.waitForTimeout(600);
  await card.locator('[data-testid=assets-hover-menu-btn]').click({ force: true });
  await page.waitForTimeout(800);
  const downloadPromise = page.waitForEvent('download', { timeout: 120000 });
  await page.getByRole('menuitem', { name: 'Download' }).click();
  await page.waitForTimeout(1500);
  await page.locator('[data-testid=download-confirm-btn]').click();
  const download = await downloadPromise;
  await download.saveAs(destPath);
  return { downloadPath: destPath };
}

async function processSiblingUnit(page, sid, baseTaskShort, stillPath, downloadPath) {
  const out = { sid, baseTaskShort };
  out.creditsStart = await credits(page);
  if (out.creditsStart < 12) return { ...out, error: 'STOP: credits < 12' };

  const open = await openCardByTaskShort(page, baseTaskShort);
  if (open.error) return { ...out, ...open };
  const baseVerts = vertNum(await verts(page));
  out.baseVerts = baseVerts;
  if (EXPECT_VERTS && baseVerts !== EXPECT_VERTS) return { ...out, error: 'vert pin mismatch', expect: EXPECT_VERTS, got: baseVerts };

  const tex = await doRetexture4K(page, stillPath);
  if (tex.error) return { ...out, ...tex };
  out.creditsAfterTex = tex.after;
  out.creditsSpentTex = tex.spent;

  const paintedId = await waitNewPaintCard(page, baseTaskShort);
  if (typeof paintedId !== 'string') return { ...out, ...paintedId };
  out.paintedId = paintedId;

  await page.locator(`[data-testid=assets-card]:has(img[src*="${paintedId}"])`).first().click({ force: true });
  for (let i = 0; i < 16; i++) {
    await page.waitForTimeout(1500);
    const hasRetex = await page.evaluate(() => !!document.querySelector('[data-testid=viewer-retexture-btn]'));
    if (hasRetex) break;
  }
  const paintNum = vertNum(await verts(page));
  out.paintedVerts = paintNum;

  const rem = await maybeRemesh(page, paintNum);
  out.remesh = rem;

  const rig = await smartRig(page, paintedId, paintNum);
  if (rig.error) return { ...out, ...rig };
  out.rigId = rig.rigId;

  await page.locator(`[data-testid=assets-card]:has(img[src*="${rig.rigId}"])`).first().click({ force: true });
  await page.waitForTimeout(2000);
  const dl = await downloadRig(page, rig.rigId, downloadPath);
  out.downloadPath = dl.downloadPath;
  out.creditsEnd = await credits(page);
  out.creditsSpentTotal = out.creditsStart - out.creditsEnd;
  return out;
}

async (page) => processSiblingUnit(page, UNIT_SID, BASE_TASK_SHORT, STILL_PATH, DOWNLOAD_PATH);
