// Runner: loaded via browser_run_code_unsafe filename=...
// Edit UNIT_SID and STILL_PATH before each run.

const UNIT_SID = 'h3_infernal_troglodyte';
const STILL_PATH = 'C:/Users/<user>/.playwright-mcp/h3_infernal_troglodyte.png';

async function processMeshy7Unit(page, sid, stillPath) {
  const out = { sid, model: 'meshy7' };
  const credits = async () => parseInt((await page.locator('[data-testid=header-credit-btn]').innerText()).trim(), 10);
  const verts = () => page.evaluate(() => (document.body.innerText.match(/Vertices\s*[\n\r]*[\d,]+/) || [])[0]);
  const faces = () => page.evaluate(() => (document.body.innerText.match(/Faces\s*[\n\r]*[\d,]+/) || [])[0]);
  const vertNum = (s) => ((s || '').match(/[\d,]+/) || [''])[0].replace(/,/g, '');

  const ensureMeshy7 = async () => {
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);
    await page.locator('[data-testid=workspace-sidebar-model-btn]').click();
    await page.waitForTimeout(1200);
    await page.locator('[data-testid=workspace-image-to-3d-tab]').click().catch(() => {});
    await page.waitForTimeout(300);
    await page.locator('[data-testid=workspace-model-type-standard]').click({ force: true });
    await page.waitForTimeout(400);
    const modelLabel = await page.locator('[data-testid=workspace-ai-model-select]').innerText();
    if (!/Meshy 7/i.test(modelLabel)) {
      return { error: 'meshy7 not selected', modelLabel };
    }
    const ultra = page.locator('[data-testid=workspace-ultra-mode-toggle]');
    if (await ultra.count() && (await ultra.getAttribute('aria-checked')) !== 'true') {
      await ultra.click({ force: true });
      await page.waitForTimeout(300);
    }
    return { modelLabel: modelLabel.replace(/\s+/g, ' ').trim() };
  };

  const meshy7 = await ensureMeshy7();
  if (meshy7.error) return { ...out, ...meshy7 };
  out.modelLabel = meshy7.modelLabel;

  const rem = page.locator('[data-testid=workspace-uploader-remove-background-btn]');
  if (await rem.count()) await rem.first().click({ force: true }).catch(() => {});
  await page.waitForTimeout(400);
  const n = await page.locator('input[type=file]').count();
  for (let i = 0; i < n; i++) await page.locator('input[type=file]').nth(i).setInputFiles(stillPath);
  await page.waitForTimeout(1200);

  out.creditsBefore = await credits();
  if (out.creditsBefore < 30) return { ...out, error: 'insufficient credits', need: 30 };

  const gb = await page.evaluate(() => {
    const b = document.querySelector('[data-testid=workspace-generate-btn]');
    const r = b.getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  });
  await page.mouse.click(gb.x, gb.y);
  await page.waitForTimeout(3000);
  out.creditsAfterGen = await credits();
  out.creditsSpentMesh = out.creditsBefore - out.creditsAfterGen;

  let grayId = null;
  for (let i = 0; i < 25; i++) {
    if (i) await page.waitForTimeout(15000);
    const fc = await page.evaluate(() => {
      const c = document.querySelector('[data-testid=assets-card]');
      const img = c && c.querySelector('img[src*="/tasks/"]');
      const id = img && (img.src.match(/tasks\/([a-f0-9-]{13})/) || [])[1];
      const text = c ? c.innerText.replace(/\s+/g, ' ').trim() : '';
      return { id, text, pct: (text.match(/(\d+)%/) || [])[1] };
    });
    if (fc.id && !fc.pct && !/%/.test(fc.text)) { grayId = fc.id; break; }
    if (/fail/i.test(fc.text)) return { ...out, error: 'gray failed', fc };
  }
  if (!grayId) return { ...out, error: 'gray timeout' };
  out.grayId = grayId;

  await page.locator(`[data-testid=assets-card]:has(img[src*="${grayId}"])`).first().click({ force: true });
  await page.waitForTimeout(2000);
  out.grayVerts = await verts();
  out.grayFaces = await faces();
  const grayNum = vertNum(out.grayVerts);
  if (!grayNum || grayNum === '0') return { ...out, error: 'gray zero verts' };

  await page.locator('[data-testid=viewer-edit-texture-btn]').first().click({ force: true });
  await page.waitForTimeout(2000);
  await page.mouse.click(578, 44);
  await page.waitForTimeout(400);
  await page.locator('[data-testid=texture-resolution-4k-btn]').click({ force: true });
  await page.waitForTimeout(400);
  await page.locator('[data-testid=texture-art-style-pbr]').click({ force: true }).catch(() => {});
  for (let i = 0; i < await page.locator('input[type=file]').count(); i++) {
    await page.locator('input[type=file]').nth(i).setInputFiles(stillPath);
  }
  await page.waitForTimeout(1200);
  const vPre = await verts();
  if (!vPre || !vPre.includes(grayNum)) return { ...out, error: 'verts changed pre-texture', vPre };
  if ((await page.locator('[data-testid=texture-resolution-4k-btn]').getAttribute('aria-checked')) !== 'true') {
    return { ...out, error: '4k not set' };
  }
  await page.locator('[data-testid=viewer-confirm-texture-btn]').click({ force: true });
  await page.waitForTimeout(5000);
  out.creditsAfterTex = await credits();
  out.creditsSpentTex = out.creditsAfterGen - out.creditsAfterTex;

  let paintedId = null;
  for (let i = 0; i < 20; i++) {
    if (i) await page.waitForTimeout(15000);
    const fc = await page.evaluate((gid) => {
      const c = document.querySelector('[data-testid=assets-card]');
      const img = c && c.querySelector('img[src*="/tasks/"]');
      const id = img && (img.src.match(/tasks\/([a-f0-9-]{13})/) || [])[1];
      const text = c ? c.innerText.replace(/\s+/g, ' ').trim() : '';
      return { id, text, pct: (text.match(/(\d+)%/) || [])[1] };
    }, grayId);
    if (fc.id && fc.id !== grayId && !fc.pct && !/%/.test(fc.text)) { paintedId = fc.id; break; }
    if (/fail/i.test(fc.text)) return { ...out, error: 'paint failed', fc };
  }
  if (!paintedId) return { ...out, error: 'paint timeout' };
  out.paintedId = paintedId;

  await page.locator(`[data-testid=assets-card]:has(img[src*="${paintedId}"])`).first().click({ force: true });
  for (let i = 0; i < 16; i++) {
    await page.waitForTimeout(1500);
    const v = await verts();
    const hasRetex = await page.evaluate(() => !!document.querySelector('[data-testid=viewer-retexture-btn]'));
    if (v && !v.includes(grayNum) && hasRetex) break;
  }
  out.paintedVerts = await verts();
  out.paintedFaces = await faces();
  const paintNum = vertNum(out.paintedVerts);
  if (!paintNum || paintNum === '0') return { ...out, error: 'painted zero verts' };

  await page.locator('[data-testid=viewer-jump-to-animate-btn]').click();
  await page.waitForTimeout(5000);
  const vAnim = await verts();
  if (!vAnim || !vAnim.includes(paintNum)) return { ...out, error: 'animate jump wrong verts', vAnim };

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
  const fully = await page.evaluate(() => /Fully automatic rigging/i.test(document.querySelector('[role=dialog]').innerText));
  if (!fully) return { ...out, error: 'not fully auto' };
  if (!(await verts()).includes(paintNum)) return { ...out, error: 'verts changed pre-rig' };
  await page.locator('[data-testid=animate-confirm-btn]').click();
  await page.waitForTimeout(5000);

  let rigId = null;
  for (let i = 0; i < 24; i++) {
    if (i) await page.waitForTimeout(20000);
    const fc = await page.evaluate((pid) => {
      const c = document.querySelector('[data-testid=assets-card]');
      const img = c && c.querySelector('img[src*="/tasks/"]');
      const id = img && (img.src.match(/tasks\/([a-f0-9-]{13})/) || [])[1];
      const text = c ? c.innerText.replace(/\s+/g, ' ').trim() : '';
      return { id, text, pct: (text.match(/(\d+)%/) || [])[1] };
    }, paintedId);
    if (fc.id && fc.id !== paintedId && !fc.pct && !/%/.test(fc.text)) { rigId = fc.id; break; }
    if (/fail/i.test(fc.text)) return { ...out, error: 'rig failed', fc };
  }
  if (!rigId) return { ...out, error: 'rig timeout' };
  out.rigId = rigId;

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
  const dlPath = `C:/Users/<user>/.playwright-mcp/${sid}_smartrigged.glb`;
  await download.saveAs(dlPath);
  out.downloadPath = dlPath;
  out.creditsEnd = await credits();
  out.creditsSpentTotal = out.creditsBefore - out.creditsEnd;
  return out;
}

async (page) => {
  return await processMeshy7Unit(page, UNIT_SID, STILL_PATH);
}
