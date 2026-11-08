// Resume T2 pipeline from gray card already in asset library.
// Edit UNIT_SID and STILL_PATH before each run.
const UNIT_SID = 'h3_automaton_upg_alt';
const STILL_PATH = 'C:/Users/<user>/.playwright-mcp/h3_automaton_upg_alt.png';
const DOWNLOAD_PATH = `C:/Users/<user>/.playwright-mcp/${UNIT_SID}_smartrigged.glb`;

async (page) => {
  const out = { sid: UNIT_SID, resume: true };
  const credits = async () => parseInt((await page.locator('[data-testid=header-credit-btn]').innerText()).trim(), 10);
  const verts = () => page.evaluate(() => (document.body.innerText.match(/Vertices\s*[\n\r]*[\d,]+/) || [])[0]);
  const faces = () => page.evaluate(() => (document.body.innerText.match(/Faces\s*[\n\r]*[\d,]+/) || [])[0]);
  const vertNum = (s) => ((s || '').match(/[\d,]+/) || [''])[0].replace(/,/g, '');

  out.creditsBefore = await credits();

  await page.keyboard.press('Escape');
  await page.waitForTimeout(400);

  const grayMeta = await page.evaluate(() => {
    const c = document.querySelector('[data-testid=assets-card]');
    const img = c && c.querySelector('img[src*="/tasks/"]');
    const id = img && (img.src.match(/tasks\/([a-f0-9-]{13})/) || [])[1];
    const text = c ? c.innerText.replace(/\s+/g, ' ').trim() : '';
    return { id, text };
  });
  if (!grayMeta.id) return { ...out, error: 'no gray card on page 1', grayMeta };
  out.grayId = grayMeta.id;

  await page.locator(`[data-testid=assets-card]:has(img[src*="${grayMeta.id}"])`).first().click({ force: true });
  await page.waitForTimeout(2500);
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
    await page.locator('input[type=file]').nth(i).setInputFiles(STILL_PATH);
  }
  await page.waitForTimeout(1200);
  const vPre = await verts();
  if (!vPre || vertNum(vPre) !== grayNum) return { ...out, error: 'verts changed pre-texture', vPre, grayNum };
  if ((await page.locator('[data-testid=texture-resolution-4k-btn]').getAttribute('aria-checked')) !== 'true') {
    return { ...out, error: '4k not set' };
  }
  await page.locator('[data-testid=viewer-confirm-texture-btn]').click({ force: true });
  await page.waitForTimeout(5000);
  out.creditsAfterTex = await credits();
  out.creditsSpentTex = out.creditsBefore - out.creditsAfterTex;

  let paintedId = null;
  for (let i = 0; i < 20; i++) {
    if (i) await page.waitForTimeout(15000);
    const fc = await page.evaluate((gid) => {
      const c = document.querySelector('[data-testid=assets-card]');
      const img = c && c.querySelector('img[src*="/tasks/"]');
      const id = img && (img.src.match(/tasks\/([a-f0-9-]{13})/) || [])[1];
      const text = c ? c.innerText.replace(/\s+/g, ' ').trim() : '';
      return { id, text, pct: (text.match(/(\d+)%/) || [])[1] };
    }, grayMeta.id);
    if (fc.id && fc.id !== grayMeta.id && !fc.pct && !/%/.test(fc.text)) {
      paintedId = fc.id;
      break;
    }
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
  if (!vAnim || vertNum(vAnim) !== paintNum) return { ...out, error: 'animate jump wrong verts', vAnim, paintNum };

  await page.locator('[data-testid=viewer-bottom-bar]').locator('[data-testid=animate-rig-btn]').click();
  await page.waitForTimeout(2000);
  const smart = await page.evaluate(() => {
    const dialog = document.querySelector('[role=dialog]');
    const el = Array.from(dialog.querySelectorAll('*')).find(
      (e) => (e.innerText || '').replace(/\s+/g, ' ').trim() === 'NEW Smart Rig (Beta)'
    );
    const r = el.getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  });
  await page.mouse.click(smart.x, smart.y);
  await page.waitForTimeout(1000);
  const fully = await page.evaluate(() => /Fully automatic rigging/i.test(document.querySelector('[role=dialog]').innerText));
  if (!fully) return { ...out, error: 'not fully auto' };
  if (vertNum(await verts()) !== paintNum) return { ...out, error: 'verts changed pre-rig' };
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
    if (fc.id && fc.id !== paintedId && !fc.pct && !/%/.test(fc.text)) {
      rigId = fc.id;
      break;
    }
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
  await download.saveAs(DOWNLOAD_PATH);
  out.downloadPath = DOWNLOAD_PATH;
  out.creditsEnd = await credits();
  out.creditsSpentTotal = out.creditsBefore - out.creditsEnd;
  return out;
};
