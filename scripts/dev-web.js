/* Local development: keep the public URL on :3000 and Next.js on :3001. */
'use strict';

const { spawn } = require('node:child_process');
const path = require('node:path');
const { createGateway } = require('./web-gateway');
const mode = process.argv[2] === 'start' ? 'start' : 'dev';

const next = spawn(process.execPath, [
  path.join(__dirname, '..', 'frontend', 'node_modules', 'next', 'dist', 'bin', 'next'),
  mode, '--hostname', '127.0.0.1', '--port', '3001',
], { cwd: path.join(__dirname, '..', 'frontend'), stdio: 'inherit', env: process.env });
const gateway = createGateway();
gateway.listen(3000, '127.0.0.1', () => process.stdout.write('MIMAS ready at http://localhost:3000\n'));
next.on('exit', code => {
  gateway.close();
  process.exitCode = code || 0;
});
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    next.kill(signal);
    gateway.close();
  });
}
