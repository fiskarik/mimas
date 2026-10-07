'use strict';

const assert = require('node:assert/strict');
const http = require('node:http');
const net = require('node:net');
const { test } = require('node:test');
const { createGateway } = require('./web-gateway');

const listen = server => new Promise(resolve => server.listen(0, '127.0.0.1', () => resolve(server.address().port)));
const close = server => new Promise(resolve => server.close(resolve));

test('gateway forwards pages, API requests and voice upgrades to the right servers', async () => {
  const next = http.createServer((_request, response) => response.end('next'));
  const api = http.createServer((_request, response) => response.end('api'));
  let upgradedPath = '';
  api.on('upgrade', (request, socket) => {
    upgradedPath = request.url;
    socket.end('HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n');
  });
  const nextPort = await listen(next);
  const apiPort = await listen(api);
  const gateway = createGateway({ nextPort, apiPort });
  const gatewayPort = await listen(gateway);
  try {
    const page = await fetch(`http://127.0.0.1:${gatewayPort}/`);
    const health = await fetch(`http://127.0.0.1:${gatewayPort}/api/health`);
    assert.equal(await page.text(), 'next');
    assert.equal(await health.text(), 'api');

    const path = `/api/ai/sessions/${'a'.repeat(32)}/voice`;
    const reply = await new Promise((resolve, reject) => {
      const socket = net.connect(gatewayPort, '127.0.0.1');
      let received = '';
      socket.on('connect', () => socket.write(`GET ${path} HTTP/1.1\r\nHost: localhost\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Key: dGVzdA==\r\nSec-WebSocket-Version: 13\r\n\r\n`));
      socket.on('data', chunk => { received += chunk.toString(); });
      socket.on('end', () => resolve(received));
      socket.on('error', reject);
    });
    assert.match(reply, /^HTTP\/1\.1 101 Switching Protocols/);
    assert.equal(upgradedPath, path);
  } finally {
    await Promise.all([close(gateway), close(next), close(api)]);
  }
});
