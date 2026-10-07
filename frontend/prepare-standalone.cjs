/* Package the MIMAS HTTP/WebSocket gateway with the standalone Next server.
 * Render's existing start command launches standalone/server.js directly.
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');

const standalone = path.join(__dirname, '.next', 'standalone');
const entry = path.join(standalone, 'server.js');
const nextEntry = path.join(standalone, 'server.next.js');
const gateway = path.join(__dirname, '..', 'scripts', 'web-gateway.js');

if (!fs.existsSync(entry) || !fs.existsSync(gateway)) {
  throw new Error('Next standalone server or MIMAS gateway is missing');
}

if (!fs.readFileSync(entry, 'utf8').startsWith('/* MIMAS standalone entry:')) {
  fs.rmSync(nextEntry, { force: true });
  fs.renameSync(entry, nextEntry);
}
fs.copyFileSync(gateway, path.join(standalone, 'mimas-gateway.js'));
fs.writeFileSync(entry, `/* MIMAS standalone entry: Next on localhost, gateway on the public port. */\n'use strict';\nconst { spawn } = require('node:child_process');\nconst path = require('node:path');\nconst { createGateway } = require('./mimas-gateway');\nconst next = spawn(process.execPath, [path.join(__dirname, 'server.next.js')], {\n  cwd: __dirname,\n  env: { ...process.env, HOSTNAME: '127.0.0.1', PORT: '3001' },\n  stdio: 'inherit',\n});\nconst gateway = createGateway();\nconst sockets = new Set();\ngateway.on('connection', socket => {\n  sockets.add(socket);\n  socket.on('close', () => sockets.delete(socket));\n});\ngateway.listen(Number(process.env.PORT || 10000), '0.0.0.0', () => {\n  process.stdout.write('MIMAS gateway ready\\n');\n});\nlet stopping = false;\nfunction stop(code) {\n  if (stopping) return;\n  stopping = true;\n  gateway.close();\n  for (const socket of sockets) socket.destroy();\n  if (next.exitCode === null) next.kill('SIGTERM');\n  process.exitCode = code;\n  setTimeout(() => process.exit(code), 5000).unref();\n}\nnext.on('exit', code => stop(code || 1));\nfor (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => stop(0));\n`);
