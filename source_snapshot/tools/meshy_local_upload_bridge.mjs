import http from 'node:http';
import fs from 'node:fs';

const sourcePath = 'V:/Games/Olden Era Playtest Tweak/artifacts/creature_aaa_3d_upscale/h3_amalek.png';

http.createServer((_request, response) => {
  response.setHeader('Access-Control-Allow-Origin', '*');
  response.end(fs.readFileSync(sourcePath));
}).listen(8765, '127.0.0.1');
