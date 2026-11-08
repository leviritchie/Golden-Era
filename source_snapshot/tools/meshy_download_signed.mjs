import fs from 'node:fs';

const [url, outputPath] = process.argv.slice(2);
if (!url || !outputPath) throw new Error('Usage: meshy_download_signed.mjs <signed-url> <output-path>');

const response = await fetch(url);
if (!response.ok) throw new Error(`Download failed: ${response.status}`);
fs.writeFileSync(outputPath, Buffer.from(await response.arrayBuffer()));
