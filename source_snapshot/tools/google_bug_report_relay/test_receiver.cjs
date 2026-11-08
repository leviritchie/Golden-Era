'use strict';

// Run as a single-process node:test fixture: node tools/google_bug_report_relay/test_receiver.cjs

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const zlib = require('node:zlib');

const source = fs.readFileSync(path.join(__dirname, 'Code.gs'), 'utf8');
const FOLDER_ID = 'pilot-folder-id-123456';
const FOLDER_OWNER = '<email>';
const PRODUCT_FOLDER_ID = 'product-folder-id-123456';
const PRODUCT_OWNER = FOLDER_OWNER;
const NOW = '2026-10-04T12:00:00.000Z';
const CONTRACT = JSON.parse(fs.readFileSync(path.join(__dirname, 'bundle_contract.json'), 'utf8'));
const CLIENT_TOKEN = 'golden-era-mod-report-1';
const PNG_1PX = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aJ1sAAAAASUVORK5CYII=', 'base64');

function crc32(bytes) {
  let value = 0xffffffff;
  for (const byte of bytes) {
    value ^= byte;
    for (let bit = 0; bit < 8; bit++) {
      value = (value >>> 1) ^ ((value & 1) ? 0xedb88320 : 0);
    }
  }
  return (value ^ 0xffffffff) >>> 0;
}

function syntheticZip(entries, zipOptions = {}) {
  const localParts = [];
  const centralParts = [];
  let offset = 0;

  for (const [filename, plain, entryOptions = {}] of entries) {
    const name = Buffer.from(filename, 'ascii');
    const crc = crc32(plain);
    const deflate = entryOptions.deflate || zipOptions.deflate;
    const body = deflate ? zlib.deflateRawSync(plain) : plain;
    const method = deflate ? 8 : 0;
    const flags = entryOptions.flags || 0;
    const declaredSize = entryOptions.declaredSize ?? plain.length;

    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(flags, 6);
    local.writeUInt16LE(method, 8);
    local.writeUInt16LE(0, 10);
    local.writeUInt16LE(33, 12);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(body.length, 18);
    local.writeUInt32LE(declaredSize, 22);
    local.writeUInt16LE(name.length, 26);

    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(flags, 8);
    central.writeUInt16LE(method, 10);
    central.writeUInt16LE(0, 12);
    central.writeUInt16LE(33, 14);
    central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(body.length, 20);
    central.writeUInt32LE(declaredSize, 24);
    central.writeUInt16LE(name.length, 28);
    central.writeUInt32LE(0x01800000, 38);
    central.writeUInt32LE(offset, 42);

    localParts.push(local, name, body);
    centralParts.push(central, name);
    offset += local.length + name.length + body.length;
  }

  const centralDirectory = Buffer.concat(centralParts);
  const centralOffset = offset;
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(entries.length, 8);
  end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(centralDirectory.length, 12);
  end.writeUInt32LE(centralOffset, 16);
  return Buffer.concat([...localParts, centralDirectory, end, zipOptions.trailer || Buffer.alloc(0)]);
}

// Minimal Utilities.unzip stand-in: walks the central directory and inflates each entry.
function unzipEntries(bytes) {
  let eocd = -1;
  for (let at = bytes.length - 22; at >= 0; at--) {
    if (bytes.readUInt32LE(at) === 0x06054b50) { eocd = at; break; }
  }
  if (eocd < 0) throw new Error('not a zip');
  const count = bytes.readUInt16LE(eocd + 10);
  let cursor = bytes.readUInt32LE(eocd + 16);
  const result = [];
  for (let i = 0; i < count; i++) {
    const method = bytes.readUInt16LE(cursor + 10);
    const compressed = bytes.readUInt32LE(cursor + 20);
    const nameLength = bytes.readUInt16LE(cursor + 28);
    const extraLength = bytes.readUInt16LE(cursor + 30);
    const commentLength = bytes.readUInt16LE(cursor + 32);
    const localOffset = bytes.readUInt32LE(cursor + 42);
    const name = bytes.subarray(cursor + 46, cursor + 46 + nameLength).toString('latin1');
    const localName = bytes.readUInt16LE(localOffset + 26);
    const localExtra = bytes.readUInt16LE(localOffset + 28);
    const start = localOffset + 30 + localName + localExtra;
    const raw = bytes.subarray(start, start + compressed);
    result.push([name, method === 8 ? zlib.inflateRawSync(raw) : Buffer.from(raw)]);
    cursor += 46 + nameLength + extraLength + commentLength;
  }
  return result;
}

function reportJson(reportId, overrides = {}) {
  return {
    schema: 'oe_mod_bug_report.v3',
    createdUtc: '2026-10-04T11:59:00.0000000Z',
    reportId,
    source: 'native_form',
    reportHash: 'c'.repeat(64),
    pluginVersion: '1.0.0',
    title: 'SYNTHETIC ONLY',
    description: 'Synthetic fixture text, not a player report.',
    category: 'Gameplay',
    tag: 'Bug',
    gameId: 'synthetic',
    contactProvided: 'false',
    os: 'Microsoft Windows NT 10.0.26200.0',
    nativeAttachmentsOmitted: 'none',
    screenshot: 'none',
    limits: 'log tails 2097152 / 262144 bytes, screenshot 4194304 bytes, bundle 8388608 bytes',
    scrubbing: 'synthetic',
    ...overrides
  };
}

// A player-shaped bundle that satisfies bundle_contract.json for the given report ID.
function playerBundle(reportId, options = {}) {
  const report = reportJson(reportId, options.report || {});
  if (options.screenshot && !(options.report && options.report.screenshot)) report.screenshot = 'included';
  if (options.dropReportKey) delete report[options.dropReportKey];
  const entries = [
    ['report.json', Buffer.from(options.reportText ?? JSON.stringify(report), 'utf8')],
    ['bepinex_log_tail.txt', options.log ?? Buffer.from('SYNTHETIC ONLY: not a game log.\n', 'ascii')],
    ['payload_manifest.json', Buffer.from(options.manifestText ?? '{"pluginVersion":"1.0.0","Core.zip":"missing"}', 'utf8')]
  ];
  if (options.nativeLog) entries.push(['native_log.txt', options.nativeLog]);
  if (options.screenshot) entries.push(['screenshot.png', options.screenshot === true ? PNG_1PX : options.screenshot]);
  for (const extra of options.extraEntries || []) entries.push(extra);
  return syntheticZip(entries, { deflate: options.deflate, trailer: options.trailer });
}

function probeBundle(atLimit = false, unknown = false, targetBytes = 8 * 1024 * 1024) {
  const entries = [
    ['metadata.json', Buffer.from('{"synthetic": true, "purpose": "Google pilot"}', 'ascii')],
    ['bepinex-log-tail.txt', Buffer.from(unknown ? 'SYNTHETIC UNKNOWN ZIP\n' : 'SYNTHETIC ONLY: not a game log.\n', 'ascii')],
    ['native-log-tail.txt', Buffer.from('SYNTHETIC ONLY: not a native log.\n', 'ascii')],
    ['screenshot.png', Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aJ1sAAAAASUVORK5CYII=', 'base64')],
    ['synthetic-padding.bin', Buffer.alloc(0)]
  ];
  const small = syntheticZip(entries);
  if (!atLimit) return small;
  entries[4][1] = Buffer.alloc(targetBytes - small.length, 0x78);
  return syntheticZip(entries);
}

const ZIP = probeBundle();
const MAX_ZIP = probeBundle(true);

process.on('exit', () => {
  process.stdout.write(`# fixture peak RSS: ${process.resourceUsage().maxRSS} KiB\n`);
});

function uuid(index) {
  return `123e4567-e89b-42d3-a456-${index.toString(16).padStart(12, '0')}`;
}

function driveFileId(index) {
  return `1AbCdEfGhIjKlMnOpQrStUvWxYz_${index.toString().padStart(6, '0')}`;
}

function requestFor(bytes = ZIP, reportId = uuid(1), purpose = 'synthetic-pilot') {
  return {
    version: 1,
    purpose,
    reportId,
    sha256: crypto.createHash('sha256').update(bytes).digest('hex'),
    bundleBase64: bytes.toString('base64')
  };
}

// Client envelope v2 for the player route; bytes default to a valid player bundle for the ID.
function playerRequest(reportId, bytes = playerBundle(reportId), token = CLIENT_TOKEN) {
  return {
    version: 2,
    purpose: 'player-report',
    reportId,
    clientToken: token,
    sha256: crypto.createHash('sha256').update(bytes).digest('hex'),
    bundleBase64: bytes.toString('base64')
  };
}

function eventFor(request, overrides = {}) {
  const contents = typeof request === 'string' ? request : JSON.stringify(request);
  const length = Buffer.byteLength(contents, 'utf8');
  return {
    contentLength: overrides.contentLength ?? length,
    postData: {
      type: overrides.type ?? 'application/json',
      length: overrides.postLength ?? length,
      contents
    }
  };
}

function makeHarness(options = {}) {
  const state = {
    now: options.now || NOW,
    properties: new Map(),
    files: [],
    filesById: new Map(),
    mail: [],
    unzipCalls: 0,
    createCalls: 0,
    folderLookups: 0,
    locked: false,
    nestedResult: null,
    sandbox: null
  };
  state.properties.set('PILOT_ACCEPTANCE_ENABLED', options.enabled === false ? 'false' : 'true');
  state.properties.set('PILOT_PRIVATE_FOLDER_ID', FOLDER_ID);
  state.properties.set('PILOT_OWNER_EMAIL', FOLDER_OWNER);
  state.properties.set('PILOT_LEDGER_SCHEMA', '1');

  const privateAccess = options.folderAccess ?? 'PRIVATE';
  const driveAccess = { PRIVATE: 'PRIVATE' };
  const owner = { getEmail: () => FOLDER_OWNER };

  function shareable(options) {
    return {
      getSharingAccess: () => options.fileAccess ?? 'PRIVATE',
      getEditors: () => options.fileEditors || [],
      getViewers: () => options.fileViewers || []
    };
  }

  function makeFolder(folderId, folderOwner) {
    return {
      getOwner: () => folderOwner,
      getSharingAccess: () => privateAccess,
      getEditors: () => options.folderEditors || [],
      getViewers: () => options.folderViewers || [],
      createFile(blob) {
        state.createCalls++;
        if (options.reenterDuringSave && !state.nestedResult) {
          const nested = requestFor(ZIP, uuid(900));
          state.nestedResult = state.sandbox.doPost(eventFor(nested));
        }
        if (options.failSave) {
          throw new Error('private fixture failure text');
        }
        const file = storedFile(driveFileId(state.createCalls), folderId, blob.bytes, blob.name, blob.type);
        state.files.push(file);
        return file;
      }
    }
  }

  function storedFile(id, parentId, bytes = Buffer.alloc(0), name = 'stored.zip', type = 'application/zip') {
    const file = {
      id,
      parentId,
      name,
      type,
      bytes: Buffer.from(bytes),
      trashed: false,
      getId() { return this.id; },
      getParents() {
        const parents = [{ getId: () => file.parentId }];
        return { hasNext: () => parents.length > 0, next: () => parents.shift() };
      },
      setTrashed(value) {
        if (options.failTrash) throw new Error('private trash failure text');
        file.trashed = !!value;
        return file;
      },
      ...shareable(options)
    };
    state.filesById.set(id, file);
    return file;
  }
  state.storeFile = storedFile;

  function blobFor(bytes, type, name) {
    const copy = Buffer.from(bytes);
    return {
      bytes: copy,
      type,
      name,
      getName: () => name,
      getBytes: () => Buffer.from(copy),
      getDataAsString: (charset) => copy.toString(charset === 'UTF-8' ? 'utf8' : 'latin1')
    };
  }

  const folders = new Map([
    [FOLDER_ID, makeFolder(FOLDER_ID, owner)],
    [PRODUCT_FOLDER_ID, makeFolder(PRODUCT_FOLDER_ID, {
      getEmail: () => options.productFolderOwner || PRODUCT_OWNER
    })]
  ]);

  const scriptProperties = {
    getProperty(key) {
      return state.properties.has(key) ? state.properties.get(key) : null;
    },
    setProperty(key, value) {
      if (options.failPropertyWrite && options.failPropertyWrite(key, value)) {
        throw new Error('private property failure text');
      }
      state.properties.set(key, String(value));
      return this;
    },
    deleteProperty(key) {
      if (options.failPropertyDelete && options.failPropertyDelete(key)) {
        throw new Error('private property delete failure text');
      }
      state.properties.delete(key);
      return this;
    },
    getProperties() {
      return Object.fromEntries(state.properties);
    }
  };

  const nativeDate = Date;
  class PilotDate extends nativeDate {
    constructor(...args) {
      super(...(args.length ? args : [state.now]));
    }
    static now() {
      return nativeDate.parse(state.now);
    }
  }

  const sandbox = {
    Date: PilotDate,
    PropertiesService: { getScriptProperties: () => scriptProperties },
    LockService: {
      getScriptLock: () => ({
        tryLock() {
          if (options.beforeLockAcquire) options.beforeLockAcquire(state);
          if (options.lockUnavailable || state.locked) return false;
          state.locked = true;
          return true;
        },
        releaseLock() { state.locked = false; }
      })
    },
    Session: { getEffectiveUser: () => ({ getEmail: () => FOLDER_OWNER }) },
    DriveApp: {
      Access: driveAccess,
      getFolderById(id) {
        state.folderLookups++;
        if (!folders.has(id)) throw new Error('unexpected folder id');
        if (options.folderUnavailable) throw new Error('private drive failure text');
        return folders.get(id);
      },
      getRootFolder() {
        throw new Error('setup must not create a second folder');
      },
      getFileById(id) {
        const file = state.filesById.get(id);
        if (!file || file.trashed) throw new Error('private missing file text');
        return file;
      }
    },
    MailApp: {
      sendEmail(recipient, subject, body) {
        if (options.failMail) throw new Error('private mail failure text');
        state.mail.push({ recipient, subject, body });
      }
    },
    Utilities: {
      DigestAlgorithm: { SHA_256: 'sha256' },
      base64Decode(value) { return Buffer.from(value, 'base64'); },
      base64Encode(value) { return Buffer.from(value).toString('base64'); },
      computeDigest(algorithm, value) {
        assert.equal(algorithm, 'sha256');
        return crypto.createHash('sha256').update(Buffer.from(value)).digest();
      },
      newBlob(bytes, type, name) {
        return blobFor(bytes, type, name);
      },
      unzip(blob) {
        state.unzipCalls++;
        return unzipEntries(Buffer.from(blob.bytes)).map(([name, bytes]) => blobFor(bytes, null, name));
      }
    },
    ContentService: {
      MimeType: { JSON: 'application/json' },
      createTextOutput(text) {
        return {
          text,
          mimeType: null,
          setMimeType(type) { this.mimeType = type; return this; }
        };
      }
    }
  };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox, { filename: 'Code.gs' });
  state.sandbox = sandbox;
  return state;
}

function makeProductHarness(options = {}) {
  const state = makeHarness({ ...options, enabled: false });
  state.properties.set('PRODUCT_ACCEPTANCE_ENABLED', options.productEnabled === false ? 'false' : 'true');
  state.properties.set('PRODUCT_PRIVATE_FOLDER_ID', PRODUCT_FOLDER_ID);
  state.properties.set('PRODUCT_OWNER_EMAIL', PRODUCT_OWNER);
  state.properties.set('PRODUCT_LEDGER_SCHEMA', '1');
  return state;
}

function post(state, request, overrides) {
  const output = state.sandbox.doPost(eventFor(request, overrides));
  assert.equal(output.mimeType, 'application/json');
  return JSON.parse(output.text);
}

function configuredFixtureAllowlist() {
  return makeHarness().sandbox.PILOT_RELAY_.syntheticFixtures;
}

function addLedgerRecord(state, index, bytes, day, stateName = 'committed') {
  const id = uuid(index);
  state.properties.set(`pilot.report.${id}`, JSON.stringify({
    v: 1,
    id,
    sha256: 'a'.repeat(64),
    bytes,
    day,
    state: stateName,
    ...(stateName === 'committed' ? { fileId: driveFileId(index) } : {})
  }));
}

function addProductLedgerRecord(state, index, bytes, day, stateName = 'committed') {
  const id = uuid(index);
  state.properties.set(`product.report.${id}`, JSON.stringify({
    v: 1,
    id,
    sha256: 'b'.repeat(64),
    bytes,
    day,
    state: stateName,
    ...(stateName === 'committed' ? { fileId: driveFileId(index) } : {})
  }));
}

test('disabled by default and returns a safe JSON error before Drive access', () => {
  const state = makeHarness({ enabled: false });
  const response = post(state, '{not-json');
  assert.deepEqual(response, { ok: false, error: 'disabled' });
  assert.equal(state.folderLookups, 0);
  assert.equal(state.files.length, 0);

  const absent = makeHarness();
  absent.properties.delete('PILOT_ACCEPTANCE_ENABLED');
  assert.deepEqual(post(absent, '{not-json'), { ok: false, error: 'disabled' });
  assert.equal(absent.folderLookups, 0);
  assert.equal(absent.files.length, 0);
});

test('setupPilot binds only an explicitly configured owner folder and does not reset the ledger', () => {
  const state = makeHarness();
  addLedgerRecord(state, 12, ZIP.length, '2026-10-03', 'pending');
  const result = state.sandbox.setupPilot();
  assert.deepEqual(JSON.parse(JSON.stringify(result)), { ok: true, enabled: false });
  assert.equal(state.properties.get('PILOT_ACCEPTANCE_ENABLED'), 'false');
  assert.equal(state.properties.get('PILOT_PRIVATE_FOLDER_ID'), FOLDER_ID);
  assert.equal(state.properties.get('PILOT_LEDGER_SCHEMA'), '1');
  assert.equal(state.properties.has(`pilot.report.${uuid(12)}`), true);
  assert.equal(state.files.length, 0);
});

test('setupPlayerReports verifies its separate private folder, disables intake, and preserves pilot state', () => {
  const state = makeProductHarness({ productEnabled: true });
  state.properties.set('PILOT_ACCEPTANCE_ENABLED', 'true');
  addLedgerRecord(state, 12, ZIP.length, '2026-10-03', 'pending');
  addProductLedgerRecord(state, 13, ZIP.length, '2026-10-03', 'pending');
  const pilotBefore = [...state.properties.entries()].filter(([key]) =>
    key === 'PILOT_ACCEPTANCE_ENABLED' || key.startsWith('pilot.report.'));

  const result = state.sandbox.setupPlayerReports();
  assert.deepEqual(JSON.parse(JSON.stringify(result)), { ok: true, enabled: false });
  assert.equal(state.properties.get('PRODUCT_ACCEPTANCE_ENABLED'), 'false');
  assert.equal(state.properties.get('PRODUCT_PRIVATE_FOLDER_ID'), PRODUCT_FOLDER_ID);
  assert.equal(state.properties.get('PRODUCT_OWNER_EMAIL'), PRODUCT_OWNER);
  assert.equal(state.properties.get('PRODUCT_LEDGER_SCHEMA'), '1');
  assert.equal(state.properties.has(`product.report.${uuid(13)}`), true);
  assert.deepEqual(
    [...state.properties.entries()].filter(([key]) =>
      key === 'PILOT_ACCEPTANCE_ENABLED' || key.startsWith('pilot.report.')),
    pilotBefore
  );
  assert.equal(state.files.length, 0);

  const missing = makeProductHarness();
  missing.properties.delete('PRODUCT_PRIVATE_FOLDER_ID');
  assert.throws(() => missing.sandbox.setupPlayerReports(), /PRODUCT_PRIVATE_FOLDER_ID/);
  assert.equal(missing.properties.get('PRODUCT_ACCEPTANCE_ENABLED'), 'false');
  assert.equal(missing.folderLookups, 0);

  const shared = makeProductHarness({ folderAccess: 'ANYONE' });
  assert.throws(() => shared.sandbox.setupPlayerReports(), /private and owned/);
  assert.equal(shared.properties.get('PRODUCT_ACCEPTANCE_ENABLED'), 'false');

  const wrongOwner = makeProductHarness({ productFolderOwner: '<email>' });
  assert.throws(() => wrongOwner.sandbox.setupPlayerReports(), /private and owned/);
  assert.equal(wrongOwner.properties.get('PRODUCT_ACCEPTANCE_ENABLED'), 'false');

  const sameFolder = makeProductHarness();
  sameFolder.properties.set('PRODUCT_PRIVATE_FOLDER_ID', FOLDER_ID);
  assert.throws(() => sameFolder.sandbox.setupPlayerReports(), /separate from the synthetic pilot/);
  assert.equal(sameFolder.properties.get('PRODUCT_ACCEPTANCE_ENABLED'), 'false');
  assert.equal(sameFolder.folderLookups, 0);
});

test('valid synthetic ZIP is saved privately before a positive acknowledgement', () => {
  const state = makeHarness();
  const request = requestFor(ZIP, uuid(2));
  const response = post(state, request);
  assert.deepEqual(response, {
    ok: true,
    reportId: request.reportId,
    sha256: request.sha256,
    duplicate: false
  });
  assert.equal(state.files.length, 1);
  assert.deepEqual(state.files[0].bytes, ZIP);
  assert.equal(state.files[0].type, 'application/zip');
  assert.equal(state.files[0].getSharingAccess(), 'PRIVATE');
  assert.equal(state.properties.get(`pilot.report.${request.reportId}`).includes(driveFileId(1)), true);
  assert.equal(JSON.stringify(response).includes(driveFileId(1)), false);
  assert.equal(JSON.stringify(response).includes(FOLDER_ID), false);
  assert.equal(JSON.stringify(response).includes('https://'), false);
});

test('player-report submissions use only the production folder and product ledger', () => {
  const state = makeProductHarness();
  const request = playerRequest(uuid(601));
  const response = post(state, request);
  assert.deepEqual(response, {
    ok: true,
    reportId: request.reportId,
    sha256: request.sha256,
    duplicate: false
  });
  assert.equal(state.files.length, 1);
  assert.equal(state.files[0].parentId, PRODUCT_FOLDER_ID);
  assert.deepEqual(state.files[0].bytes, playerBundle(uuid(601)));
  assert.equal(state.unzipCalls, 1);
  assert.equal(state.properties.has(`product.report.${request.reportId}`), true);
  assert.equal([...state.properties.keys()].some(key => key.startsWith('pilot.report.')), false);
  assert.equal(state.properties.get('PILOT_ACCEPTANCE_ENABLED'), 'false');
});

test('only the two immutable root-probe ZIPs are allowlisted, including exactly 8 MiB', () => {
  const expectedSmall = '28d8e8f21838f93dad9271c9b38481b053c8da62f7bdef8fb58f3cc27c88dbf5';
  const expectedLimit = 'f1cbcbb95c1ee9cf5124b17311704000859eaf2e28df15bcb14994a2c04c49dd';
  assert.equal(ZIP.length, 756);
  assert.equal(crypto.createHash('sha256').update(ZIP).digest('hex'), expectedSmall);
  assert.equal(MAX_ZIP.length, 8 * 1024 * 1024);
  assert.equal(crypto.createHash('sha256').update(MAX_ZIP).digest('hex'), expectedLimit);
  assert.deepEqual(
    Object.keys(configuredFixtureAllowlist()).sort(),
    [expectedLimit, expectedSmall].sort()
  );

  const smallState = makeHarness();
  assert.equal(post(smallState, requestFor(ZIP, uuid(80))).ok, true);

  const limitState = makeHarness();
  const limitResponse = post(limitState, requestFor(MAX_ZIP, uuid(81)));
  assert.equal(limitResponse.ok, true);
  assert.equal(limitState.files[0].bytes.length, 8 * 1024 * 1024);

  const unknownState = makeHarness();
  const unknownZip = probeBundle(false, true);
  assert.equal(post(unknownState, requestFor(unknownZip, uuid(82))).error, 'synthetic_fixture_required');
  assert.equal(unknownState.files.length, 0);
  assert.equal([...unknownState.properties.keys()].filter(key => key.startsWith('pilot.report.')).length, 0);
});

test('player-report accepts a contract bundle with every entry at its cap and refuses an 8 MiB plus one byte body', () => {
  const state = makeProductHarness();
  const largest = playerBundle(uuid(602), {
    log: Buffer.alloc(CONTRACT.entries['bepinex_log_tail.txt'].maxBytes, 0x61),
    nativeLog: Buffer.alloc(CONTRACT.entries['native_log.txt'].maxBytes, 0x62),
    screenshot: Buffer.concat([PNG_1PX, Buffer.alloc(CONTRACT.entries['screenshot.png'].maxBytes - PNG_1PX.length)])
  });
  assert.ok(largest.length > 6 * 1024 * 1024 && largest.length <= 8 * 1024 * 1024);
  const exactLimit = playerRequest(uuid(602), largest);
  const accepted = post(state, exactLimit);
  assert.equal(accepted.ok, true);
  assert.equal(accepted.sha256, exactLimit.sha256);
  assert.equal(state.files[0].bytes.length, largest.length);
  assert.equal(state.files[0].parentId, PRODUCT_FOLDER_ID);

  const overLimitZip = probeBundle(true, false, 8 * 1024 * 1024 + 1);
  assert.equal(overLimitZip.length, 8 * 1024 * 1024 + 1);
  const refused = post(state, playerRequest(uuid(603), overLimitZip));
  assert.deepEqual(refused, { ok: false, error: 'bundle_too_large' });
  assert.equal(state.files.length, 1);
  assert.equal(state.properties.has(`product.report.${uuid(603)}`), false);
});

test('player-report strict envelope and digest refusals do not reserve admission or touch Drive', () => {
  const state = makeProductHarness();
  const request = playerRequest(uuid(604));
  assert.equal(post(state, { ...request, extra: true }).error, 'invalid_request');
  assert.equal(post(state, request, { type: 'application/jsonp' }).error, 'invalid_request');
  assert.equal(post(state, request, { contentLength: 12 * 1024 * 1024 + 1 }).error, 'request_too_large');

  const mismatch = { ...request, reportId: uuid(605), sha256: '0'.repeat(64) };
  assert.deepEqual(post(state, mismatch), { ok: false, error: 'hash_mismatch' });
  assert.equal(state.files.length, 0);
  assert.equal([...state.properties.keys()].filter(key => key.startsWith('product.report.')).length, 0);

  const unconfigured = makeHarness({ enabled: false });
  assert.deepEqual(post(unconfigured, request), { ok: false, error: 'disabled' });
  assert.equal(unconfigured.folderLookups, 0);
  assert.equal(unconfigured.files.length, 0);
});

test('same UUID and SHA retry is idempotent while a UUID conflict is rejected', () => {
  const state = makeHarness();
  const request = requestFor(ZIP, uuid(3));
  assert.equal(post(state, request).duplicate, false);
  assert.equal(post(state, request).duplicate, true);
  assert.equal(state.files.length, 1);

  assert.deepEqual(post(state, requestFor(MAX_ZIP, request.reportId)), {
    ok: false,
    error: 'report_id_conflict'
  });
  assert.equal(state.files.length, 1);
});

test('player-report retries are idempotent in the product ledger and conflict on changed bytes', () => {
  const state = makeProductHarness();
  const request = playerRequest(uuid(606));
  assert.equal(post(state, request).duplicate, false);
  assert.equal(post(state, request).duplicate, true);
  assert.equal(state.files.length, 1);
  assert.equal(state.properties.has(`pilot.report.${request.reportId}`), false);

  assert.deepEqual(post(state, playerRequest(request.reportId, playerBundle(request.reportId, { deflate: true }))), {
    ok: false,
    error: 'report_id_conflict'
  });
  assert.equal(state.files.length, 1);
});

test('storage failures retain a pending reservation and never acknowledge', () => {
  const state = makeHarness({ failSave: true });
  const request = requestFor(ZIP, uuid(4));
  assert.deepEqual(post(state, request), { ok: false, error: 'storage_failed' });
  const pending = JSON.parse(state.properties.get(`pilot.report.${request.reportId}`));
  assert.equal(pending.state, 'pending');
  assert.deepEqual(post(state, request), { ok: false, error: 'pending_reconciliation' });
  assert.equal(state.createCalls, 1);
});

test('player-report storage failures retain only a product pending reservation', () => {
  const state = makeProductHarness({ failSave: true });
  const request = playerRequest(uuid(607));
  assert.deepEqual(post(state, request), { ok: false, error: 'storage_failed' });
  const pending = JSON.parse(state.properties.get(`product.report.${request.reportId}`));
  assert.equal(pending.state, 'pending');
  assert.deepEqual(post(state, request), { ok: false, error: 'pending_reconciliation' });
  assert.equal(state.createCalls, 1);
  assert.equal(state.properties.has(`pilot.report.${request.reportId}`), false);
});

test('a saved file without a durable committed ledger entry is not acknowledged', () => {
  const state = makeHarness({
    failPropertyWrite(key, value) {
      return key.startsWith('pilot.report.') && JSON.parse(value).state === 'committed';
    }
  });
  const request = requestFor(ZIP, uuid(5));
  assert.deepEqual(post(state, request), { ok: false, error: 'storage_failed' });
  assert.equal(state.files.length, 1);
  assert.equal(JSON.parse(state.properties.get(`pilot.report.${request.reportId}`)).state, 'pending');
  assert.deepEqual(post(state, request), { ok: false, error: 'pending_reconciliation' });
  assert.equal(state.files.length, 1);
});

test('player-report saved file without durable commit is not acknowledged', () => {
  const state = makeProductHarness({
    failPropertyWrite(key, value) {
      return key.startsWith('product.report.') && JSON.parse(value).state === 'committed';
    }
  });
  const request = playerRequest(uuid(608));
  assert.deepEqual(post(state, request), { ok: false, error: 'storage_failed' });
  assert.equal(state.files.length, 1);
  assert.equal(JSON.parse(state.properties.get(`product.report.${request.reportId}`)).state, 'pending');
  assert.deepEqual(post(state, request), { ok: false, error: 'pending_reconciliation' });
  assert.equal(state.files.length, 1);
});

test('configured public or explicitly shared folders fail closed before saving', () => {
  for (const options of [
    { folderAccess: 'ANYONE' },
    { folderEditors: ['<email>'] },
    { folderViewers: ['<email>'] }
  ]) {
    const state = makeHarness(options);
    assert.deepEqual(post(state, requestFor(ZIP)), {
      ok: false,
      error: 'configuration_invalid'
    });
    assert.equal(state.createCalls, 0);
  }
});

test('shared production destinations fail closed before storage', () => {
  for (const options of [
    { folderAccess: 'ANYONE' },
    { folderEditors: ['<email>'] },
    { folderViewers: ['<email>'] }
  ]) {
    const state = makeProductHarness(options);
    assert.deepEqual(post(state, playerRequest(uuid(612))), {
      ok: false,
      error: 'configuration_invalid'
    });
    assert.equal(state.createCalls, 0);
    assert.equal([...state.properties.keys()].some(key => key.startsWith('product.report.')), false);
  }
});

test('a post-create public or shared file stops acceptance and retains pending charge', () => {
  for (const options of [
    { fileAccess: 'ANYONE' },
    { fileEditors: ['<email>'] },
    { fileViewers: ['<email>'] }
  ]) {
    const state = makeHarness(options);
    const request = requestFor(ZIP, uuid(83));
    assert.deepEqual(post(state, request), { ok: false, error: 'storage_privacy_failed' });
    assert.equal(state.files.length, 1);
    assert.equal(state.properties.get('PILOT_ACCEPTANCE_ENABLED'), 'false');
    assert.equal(JSON.parse(state.properties.get(`pilot.report.${request.reportId}`)).state, 'pending');

    const next = post(state, requestFor(ZIP, uuid(84)));
    assert.deepEqual(next, { ok: false, error: 'disabled' });
    assert.equal(state.createCalls, 1);
  }

  const stopFailure = makeHarness({
    fileAccess: 'ANYONE',
    failPropertyWrite(key, value) {
      return key === 'PILOT_ACCEPTANCE_ENABLED' && value === 'false';
    }
  });
  const request = requestFor(ZIP, uuid(85));
  assert.deepEqual(post(stopFailure, request), { ok: false, error: 'acceptance_stop_failed' });
  assert.equal(stopFailure.properties.get('PILOT_ACCEPTANCE_ENABLED'), 'true');
  assert.equal(JSON.parse(stopFailure.properties.get(`pilot.report.${request.reportId}`)).state, 'pending');
});

test('a player-report file privacy failure disables only product intake and retains its charge', () => {
  for (const options of [
    { fileAccess: 'ANYONE' },
    { fileEditors: ['<email>'] },
    { fileViewers: ['<email>'] }
  ]) {
    const state = makeProductHarness(options);
    state.properties.set('PILOT_ACCEPTANCE_ENABLED', 'true');
    const request = playerRequest(uuid(609));
    assert.deepEqual(post(state, request), { ok: false, error: 'storage_privacy_failed' });
    assert.equal(state.files.length, 1);
    assert.equal(state.properties.get('PRODUCT_ACCEPTANCE_ENABLED'), 'false');
    assert.equal(state.properties.get('PILOT_ACCEPTANCE_ENABLED'), 'true');
    assert.equal(JSON.parse(state.properties.get(`product.report.${request.reportId}`)).state, 'pending');

    assert.deepEqual(post(state, playerRequest(uuid(610))), { ok: false, error: 'disabled' });
    assert.equal(state.createCalls, 1);
  }

  const stopFailure = makeProductHarness({
    fileAccess: 'ANYONE',
    failPropertyWrite(key, value) {
      return key === 'PRODUCT_ACCEPTANCE_ENABLED' && value === 'false';
    }
  });
  stopFailure.properties.set('PILOT_ACCEPTANCE_ENABLED', 'true');
  const request = playerRequest(uuid(611));
  assert.deepEqual(post(stopFailure, request), { ok: false, error: 'acceptance_stop_failed' });
  assert.equal(stopFailure.properties.get('PRODUCT_ACCEPTANCE_ENABLED'), 'true');
  assert.equal(stopFailure.properties.get('PILOT_ACCEPTANCE_ENABLED'), 'true');
  assert.equal(JSON.parse(stopFailure.properties.get(`product.report.${request.reportId}`)).state, 'pending');
});

test('strict request schema, purpose, content type, and declared body size are enforced', () => {
  const unknownField = { ...requestFor(), extra: 'reject' };
  assert.equal(post(makeHarness(), unknownField).error, 'invalid_request');
  assert.equal(post(makeHarness(), requestFor(ZIP, uuid(6), 'player-report')).error, 'invalid_request');

  const state = makeHarness();
  assert.equal(post(state, requestFor(), { type: 'text/plain' }).error, 'invalid_request');
  assert.equal(post(state, requestFor(), { type: 'application/jsonp' }).error, 'invalid_request');
  assert.equal(post(makeHarness(), requestFor(), { type: 'application/json; charset=utf-8' }).ok, true);
  assert.equal(post(state, requestFor(), { contentLength: 12 * 1024 * 1024 + 1 }).error, 'request_too_large');
  assert.equal(state.files.length, 0);
});

test('base64 must be canonical, bounded, and contain a ZIP local-file signature', () => {
  const state = makeHarness();
  const invalidBase64 = requestFor();
  invalidBase64.bundleBase64 = 'PK\u0003\u0004!!!!';
  assert.equal(post(state, invalidBase64).error, 'invalid_bundle');

  const notZip = Buffer.from('not a zip');
  assert.equal(post(state, requestFor(notZip, uuid(7))).error, 'invalid_bundle');

  const tooLarge = requestFor();
  tooLarge.bundleBase64 = 'A'.repeat(Math.ceil((8 * 1024 * 1024) / 3) * 4 + 4);
  assert.equal(post(state, tooLarge).error, 'bundle_too_large');
  assert.equal(state.files.length, 0);
});

test('SHA-256 is recomputed from the decoded ZIP before admission', () => {
  const request = requestFor();
  request.sha256 = '0'.repeat(64);
  const state = makeHarness();
  assert.deepEqual(post(state, request), { ok: false, error: 'hash_mismatch' });
  assert.equal(state.files.length, 0);
  assert.equal(state.properties.size, 4);
});

test('busy locks fail closed without reserving or creating a Drive file', () => {
  const state = makeHarness({ lockUnavailable: true });
  assert.deepEqual(post(state, requestFor()), { ok: false, error: 'busy' });
  assert.equal(state.files.length, 0);
  assert.equal(state.properties.size, 4);
});

test('an acceptance disable during pre-lock validation is rechecked before reservation', () => {
  const state = makeHarness({
    beforeLockAcquire(current) {
      current.properties.set('PILOT_ACCEPTANCE_ENABLED', 'false');
    }
  });
  assert.deepEqual(post(state, requestFor(ZIP, uuid(53))), { ok: false, error: 'disabled' });
  assert.equal(state.files.length, 0);
  assert.equal([...state.properties.keys()].filter(key => key.startsWith('pilot.report.')).length, 0);
});

test('reentrant competing submission cannot pass the script lock during a Drive write', () => {
  const state = makeHarness({ reenterDuringSave: true });
  const response = post(state, requestFor(ZIP, uuid(8)));
  assert.equal(response.ok, true);
  assert.equal(JSON.parse(state.nestedResult.text).error, 'busy');
  assert.equal(state.files.length, 1);
  assert.equal([...state.properties.keys()].filter(key => key.startsWith('pilot.report.')).length, 1);
});

test('daily report and byte caps are charged against pending and committed reservations', () => {
  const reportCap = makeHarness();
  for (let i = 1; i <= 40; i++) {
    assert.equal(post(reportCap, requestFor(ZIP, uuid(i))).ok, true);
  }
  assert.deepEqual(post(reportCap, requestFor(ZIP, uuid(41))), {
    ok: false,
    error: 'daily_limit'
  });
  assert.equal(reportCap.files.length, 40);

  const byteCap = makeHarness();
  for (let i = 1; i <= 20; i++) addLedgerRecord(byteCap, i, 8 * 1024 * 1024, '2026-10-04');
  assert.equal(post(byteCap, requestFor(ZIP, uuid(500))).error, 'daily_limit');
  assert.equal(byteCap.files.length, 0);
});

test('player-report daily count and byte caps refuse without mutating isolated history', () => {
  const reportCap = makeProductHarness();
  for (let i = 1; i <= 40; i++) addProductLedgerRecord(reportCap, i, ZIP.length, '2026-10-04');
  const reportHistory = [...reportCap.properties.entries()].filter(([key]) => key.startsWith('product.report.'));
  assert.deepEqual(post(reportCap, playerRequest(uuid(701))), {
    ok: false,
    error: 'daily_limit'
  });
  assert.deepEqual(
    [...reportCap.properties.entries()].filter(([key]) => key.startsWith('product.report.')),
    reportHistory
  );
  assert.equal(reportCap.files.length, 0);

  const byteCap = makeProductHarness();
  for (let i = 1; i <= 20; i++) addProductLedgerRecord(byteCap, i, 8 * 1024 * 1024, '2026-10-04');
  const byteHistory = [...byteCap.properties.entries()].filter(([key]) => key.startsWith('product.report.'));
  assert.equal(post(byteCap, playerRequest(uuid(702))).error, 'daily_limit');
  assert.deepEqual(
    [...byteCap.properties.entries()].filter(([key]) => key.startsWith('product.report.')),
    byteHistory
  );
  assert.equal(byteCap.files.length, 0);
});

test('pilot history past its budget rotates oldest-first instead of a lifetime stop', () => {
  const reportCap = makeHarness();
  for (let i = 1; i <= 24; i++) {
    assert.equal(post(reportCap, requestFor(ZIP, uuid(i))).ok, true);
  }
  reportCap.now = '2026-10-05T12:00:00.000Z';
  for (let i = 25; i <= 48; i++) {
    assert.equal(post(reportCap, requestFor(ZIP, uuid(i))).ok, true);
  }
  const rotated = post(reportCap, requestFor(ZIP, uuid(49)));
  assert.equal(rotated.ok, true);
  assert.equal(reportCap.properties.has(`pilot.report.${uuid(1)}`), false);
  assert.equal(reportCap.filesById.get(driveFileId(1)).trashed, true);
  assert.equal(reportCap.filesById.get(driveFileId(2)).trashed, false);
  assert.equal([...reportCap.properties.keys()].filter(key => key.startsWith('pilot.report.')).length, 48);
  assert.equal(reportCap.mail.length, 1);
  assert.match(reportCap.mail[0].subject, /budget_rotation/);
  assert.equal(reportCap.mail[0].recipient, FOLDER_OWNER);

  const byteCap = makeHarness();
  for (let i = 1; i <= 32; i++) addLedgerRecord(byteCap, i, 8 * 1024 * 1024, '2026-10-03');
  byteCap.sandbox.setupPilot();
  byteCap.properties.set('PILOT_ACCEPTANCE_ENABLED', 'true');
  assert.equal(post(byteCap, requestFor(ZIP, uuid(501))).ok, true);
  assert.equal(byteCap.properties.has(`pilot.report.${uuid(1)}`), false);
  assert.equal(byteCap.properties.has(`pilot.report.${uuid(2)}`), true);
});

test('player-report reports past retention are trashed and their ledger records dropped', () => {
  const state = makeProductHarness();
  for (let i = 101; i <= 107; i++) {
    addProductLedgerRecord(state, i, ZIP.length, i <= 106 ? '2026-06-01' : '2026-09-30');
    state.storeFile(driveFileId(i), PRODUCT_FOLDER_ID);
  }
  const response = post(state, playerRequest(uuid(8100)));
  assert.equal(response.ok, true);
  // Bounded inline: at most five removals per request.
  const remaining = [...state.properties.keys()].filter(key => key.startsWith('product.report.'));
  assert.equal(remaining.length, 3);
  assert.equal(state.filesById.get(driveFileId(101)).trashed, true);
  assert.equal(state.filesById.get(driveFileId(105)).trashed, true);
  assert.equal(state.filesById.get(driveFileId(106)).trashed, false);
  assert.equal(state.filesById.get(driveFileId(107)).trashed, false);
  assert.equal(state.mail.length, 0, 'age-based retention is routine and does not alert');

  const run = state.sandbox.pruneReports();
  assert.equal(run.ok, true);
  assert.equal(state.filesById.get(driveFileId(106)).trashed, true);
  assert.equal(state.filesById.get(driveFileId(107)).trashed, false);
  assert.equal(state.properties.has(`product.report.${uuid(8100)}`), true);
});

test('player-report rotation trashes only intake-folder files, alerts, and refuses with storage_budget when no room can be made', () => {
  const state = makeProductHarness();
  for (let i = 101; i <= 228; i++) addProductLedgerRecord(state, i, 8 * 1024 * 1024, '2026-10-03');
  state.storeFile(driveFileId(101), 'some-other-folder-123');
  for (let i = 102; i <= 103; i++) state.storeFile(driveFileId(i), PRODUCT_FOLDER_ID);
  const accepted = post(state, playerRequest(uuid(8002)));
  assert.equal(accepted.ok, true);
  assert.equal(state.filesById.get(driveFileId(101)).trashed, false, 'files outside the intake folder are never trashed');
  assert.equal(state.properties.has(`product.report.${uuid(101)}`), false);
  assert.equal(state.filesById.get(driveFileId(102)).trashed, false);
  assert.equal(state.properties.has(`product.report.${uuid(102)}`), true, 'one removal was enough');
  assert.deepEqual(state.mail.map(mail => mail.subject.split(':')[1].trim().split(' ')[0]).sort(),
    ['budget_rotation', 'prune_mismatch']);

  const full = makeProductHarness();
  for (let i = 1; i <= 128; i++) addProductLedgerRecord(full, i, 8 * 1024 * 1024, '2026-10-04');
  // Today's records also trip the daily byte cap first; lift that to reach the retained budget.
  full.properties.set('PRODUCT_ALERT_LAST_daily_limit', String(Date.parse(NOW)));
  assert.equal(post(full, playerRequest(uuid(8003))).error, 'daily_limit');
  assert.equal(full.mail.length, 0, 'a recent alert of the same kind is not repeated');

  const budget = makeProductHarness();
  for (let i = 1; i <= 1000; i++) addProductLedgerRecord(budget, i, ZIP.length, '2026-10-04');
  budget.now = '2026-10-04T23:00:00.000Z';
  // 1000 today-records exceed the daily count cap; the budget check is reached only with a raised cap,
  // so exercise pilotPrune_ directly for the storage_budget branch.
  const alerts = [];
  const records = JSON.parse(JSON.stringify([...budget.properties.entries()]
    .filter(([key]) => key.startsWith('product.report.')).map(([, value]) => JSON.parse(value))));
  const result = budget.sandbox.pilotPrune_(
    budget.sandbox.PropertiesService.getScriptProperties(), budget.sandbox.PRODUCT_RELAY_,
    PRODUCT_FOLDER_ID, records, '2026-10-04', ZIP.length, 5, alerts);
  assert.equal(result.ok, false);
  assert.equal(result.error, 'storage_budget');
  assert.equal(alerts.length, 1);
  assert.equal(alerts[0].kind, 'storage_budget');
});

test('daily-limit alerts are emailed to the effective user at most once per interval and never carry report text', () => {
  const state = makeProductHarness();
  for (let i = 1; i <= 40; i++) addProductLedgerRecord(state, i, ZIP.length, '2026-10-04');
  assert.equal(post(state, playerRequest(uuid(8200))).error, 'daily_limit');
  assert.equal(post(state, playerRequest(uuid(8201))).error, 'daily_limit');
  assert.equal(state.mail.length, 1);
  assert.equal(state.mail[0].recipient, FOLDER_OWNER);
  assert.match(state.mail[0].subject, /daily_limit \(player-report\)/);
  assert.equal(state.mail[0].body.includes('SYNTHETIC'), false);

  state.now = '2026-10-04T18:00:00.001Z';
  assert.equal(post(state, playerRequest(uuid(8202))).error, 'daily_limit');
  assert.equal(state.mail.length, 2);

  const mailDown = makeProductHarness({ failMail: true });
  for (let i = 1; i <= 40; i++) addProductLedgerRecord(mailDown, i, ZIP.length, '2026-10-04');
  assert.equal(post(mailDown, playerRequest(uuid(8203))).error, 'daily_limit');
});

test('a trash failure stops pruning, alerts, and leaves the ledger record in place', () => {
  const state = makeProductHarness({ failTrash: true });
  addProductLedgerRecord(state, 1, ZIP.length, '2026-06-01');
  state.storeFile(driveFileId(1), PRODUCT_FOLDER_ID);
  assert.equal(post(state, playerRequest(uuid(8300))).ok, true);
  assert.equal(state.properties.has(`product.report.${uuid(1)}`), true);
  assert.equal(state.mail.length, 1);
  assert.match(state.mail[0].subject, /prune_failed/);
});

test('per-file ledger records remain bounded and malformed bookkeeping blocks writes', () => {
  const state = makeHarness();
  addLedgerRecord(state, 50, ZIP.length, '2026-10-03');
  const storedRecord = state.properties.get(`pilot.report.${uuid(50)}`);
  assert.ok(Buffer.byteLength(storedRecord, 'utf8') < 9 * 1024);

  state.properties.set(`pilot.report.${uuid(51)}`, '{broken');
  assert.equal(post(state, requestFor(ZIP, uuid(52))).error, 'ledger_corrupt');
  assert.equal(state.files.length, 0);

  const malformedId = makeHarness();
  addLedgerRecord(malformedId, 53, ZIP.length, '2026-10-03');
  const record = JSON.parse(malformedId.properties.get(`pilot.report.${uuid(53)}`));
  record.fileId = 'not/a/drive/id';
  malformedId.properties.set(`pilot.report.${uuid(53)}`, JSON.stringify(record));
  assert.equal(post(malformedId, requestFor(ZIP, uuid(53))).error, 'ledger_corrupt');
  assert.equal(malformedId.files.length, 0);
});

test('Code.gs embeds exactly the shared bundle contract used by the client tests', () => {
  const embedded = JSON.parse(JSON.stringify(makeHarness().sandbox.BUNDLE_CONTRACT_));
  assert.deepEqual(embedded, CONTRACT);
});

test('player bundles accept deflate entries, an optional native log, and an included PNG screenshot', () => {
  const state = makeProductHarness();
  const bytes = playerBundle(uuid(9001), { deflate: true, nativeLog: Buffer.from('native\n'), screenshot: true });
  assert.equal(post(state, playerRequest(uuid(9001), bytes)).ok, true);
  assert.equal(state.files.length, 1);
});

test('player bundles with unexpected, duplicate, missing, or encrypted entries are refused before storage', () => {
  const cases = [
    ['unknown entry', playerBundle(uuid(9010), { extraEntries: [['payload.exe', Buffer.from('MZ')]] }), 'invalid_bundle_entries'],
    ['jpg entry', playerBundle(uuid(9011), { extraEntries: [['screenshot.jpg', Buffer.from('x')]] }), 'invalid_bundle_entries'],
    ['path entry', playerBundle(uuid(9012), { extraEntries: [['../report.json', Buffer.from('x')]] }), 'invalid_bundle_entries'],
    ['duplicate entry', playerBundle(uuid(9013), { extraEntries: [['bepinex_log_tail.txt', Buffer.from('again')]] }), 'invalid_bundle_entries'],
    ['too many entries', playerBundle(uuid(9014), { nativeLog: Buffer.from('n'), screenshot: true,
      extraEntries: [['native_log.txt', Buffer.from('dup')]] }), 'invalid_bundle_entries'],
    ['encrypted entry', syntheticZip([
      ['report.json', Buffer.from(JSON.stringify(reportJson(uuid(9015))))],
      ['bepinex_log_tail.txt', Buffer.from('x'), { flags: 1 }],
      ['payload_manifest.json', Buffer.from('{}')]
    ]), 'invalid_bundle_entries'],
    ['missing manifest', syntheticZip([
      ['report.json', Buffer.from(JSON.stringify(reportJson(uuid(9016))))],
      ['bepinex_log_tail.txt', Buffer.from('x')]
    ]), 'invalid_bundle_entries'],
    ['trailing bytes', playerBundle(uuid(9017), { trailer: Buffer.from('junk') }), 'invalid_bundle']
  ];
  for (const [label, bytes, error] of cases) {
    const state = makeProductHarness();
    const id = label === 'encrypted entry' ? uuid(9015) : label === 'missing manifest' ? uuid(9016) : uuid(9010 + cases.findIndex(c => c[0] === label));
    assert.deepEqual(post(state, playerRequest(id, bytes)), { ok: false, error }, label);
    assert.equal(state.createCalls, 0, label);
    assert.equal([...state.properties.keys()].some(key => key.startsWith('product.report.')), false, label);
  }
});

test('declared or inflated entry sizes over the contract caps are refused without storing', () => {
  const declared = syntheticZip([
    ['report.json', Buffer.from(JSON.stringify(reportJson(uuid(9020))))],
    ['bepinex_log_tail.txt', Buffer.from('x'), { declaredSize: 64 * 1024 * 1024 }],
    ['payload_manifest.json', Buffer.from('{}')]
  ]);
  const state = makeProductHarness();
  assert.deepEqual(post(state, playerRequest(uuid(9020), declared)), { ok: false, error: 'bundle_entry_too_large' });
  assert.equal(state.unzipCalls, 0, 'declared sizes are checked before inflating');

  // A lying central directory that understates the inflated size is caught after unzip.
  const lying = syntheticZip([
    ['report.json', Buffer.from(JSON.stringify(reportJson(uuid(9021))))],
    ['bepinex_log_tail.txt', Buffer.alloc(CONTRACT.entries['bepinex_log_tail.txt'].maxBytes * 2, 0x61), { deflate: true, declaredSize: 10 }],
    ['payload_manifest.json', Buffer.from('{}')]
  ]);
  const second = makeProductHarness();
  assert.deepEqual(post(second, playerRequest(uuid(9021), lying)), { ok: false, error: 'bundle_entry_too_large' });
  assert.equal(second.createCalls, 0);

  const bigLog = playerBundle(uuid(9022), { log: Buffer.alloc(CONTRACT.entries['bepinex_log_tail.txt'].maxBytes + 1, 0x61), deflate: true });
  assert.deepEqual(post(makeProductHarness(), playerRequest(uuid(9022), bigLog)), { ok: false, error: 'bundle_entry_too_large' });
});

test('report.json must match the schema, the request report ID, and the screenshot entry', () => {
  const id = uuid(9030);
  const cases = [
    ['not json', { reportText: '{broken' }],
    ['array', { reportText: '[]' }],
    ['missing key', { dropReportKey: 'os' }],
    ['extra key', { reportText: JSON.stringify({ ...reportJson(id), extra: 'x' }) }],
    ['non-string', { reportText: JSON.stringify({ ...reportJson(id), title: 5 }) }],
    ['wrong schema', { report: { schema: 'oe_mod_bug_report.v2' } }],
    ['other report id', { report: { reportId: uuid(9031) } }],
    ['bad hash', { report: { reportHash: 'XYZ' } }],
    ['bad contact flag', { report: { contactProvided: 'maybe' } }],
    ['bad timestamp', { report: { createdUtc: 'yesterday' } }],
    ['unknown screenshot note', { report: { screenshot: 'attached' } }],
    ['claims screenshot without entry', { report: { screenshot: 'included' } }],
    ['entry without claim', { screenshot: true, report: { screenshot: 'none' } }],
    ['overlong title', { report: { title: 'x'.repeat(CONTRACT.reportFields.title + 1) } }],
    ['manifest not object', { manifestText: '[]' }],
    ['manifest non-string value', { manifestText: '{"a":1}' }]
  ];
  for (const [label, options] of cases) {
    const state = makeProductHarness();
    assert.deepEqual(post(state, playerRequest(id, playerBundle(id, options))), { ok: false, error: 'invalid_report_json' }, label);
    assert.equal(state.createCalls, 0, label);
  }
  const fakePng = makeProductHarness();
  assert.deepEqual(post(fakePng, playerRequest(id, playerBundle(id, { screenshot: Buffer.from('GIF89a-not-png') }))),
    { ok: false, error: 'invalid_bundle_entries' });
});

test('client token: v1 and v2 accepted until PRODUCT_CLIENT_TOKEN is set, then only the exact v2 token', () => {
  const open = makeProductHarness();
  const v1 = requestFor(playerBundle(uuid(9040)), uuid(9040), 'player-report');
  assert.equal(post(open, v1).ok, true);
  assert.equal(post(open, playerRequest(uuid(9041))).ok, true);
  assert.equal(post(open, playerRequest(uuid(9042), playerBundle(uuid(9042)), 'short')).error, 'invalid_request');

  const locked = makeProductHarness();
  locked.properties.set('PRODUCT_CLIENT_TOKEN', CLIENT_TOKEN);
  assert.equal(post(locked, requestFor(playerBundle(uuid(9043)), uuid(9043), 'player-report')).error, 'client_token_mismatch');
  assert.equal(post(locked, playerRequest(uuid(9044), playerBundle(uuid(9044)), 'golden-era-other-token')).error, 'client_token_mismatch');
  assert.equal(locked.unzipCalls, 0);
  assert.equal(post(locked, playerRequest(uuid(9045))).ok, true);

  const badConfig = makeProductHarness();
  badConfig.properties.set('PRODUCT_CLIENT_TOKEN', 'bad token with spaces');
  assert.equal(post(badConfig, playerRequest(uuid(9046))).error, 'configuration_invalid');

  // The pilot route never takes a token envelope.
  const pilot = makeHarness();
  const pilotV2 = { ...requestFor(ZIP, uuid(9047)), version: 2, clientToken: CLIENT_TOKEN };
  assert.equal(post(pilot, pilotV2).error, 'invalid_request');
});
