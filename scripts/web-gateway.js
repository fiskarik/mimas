/* One public HTTP port for Next.js and the interview voice WebSocket. */
'use strict';

const http = require('node:http');
const net = require('node:net');

const VOICE_PATH = /^\/api\/ai\/sessions\/[0-9a-f]{32}\/voice(?:\?.*)?$/;

function createGateway({ nextPort = 3001, apiPort = 8000 } = {}) {
  const server = http.createServer((request, response) => {
    const api = request.url.startsWith('/api/');
    const upstream = http.request({
      hostname: '127.0.0.1',
      port: api ? apiPort : nextPort,
      path: request.url,
      method: request.method,
      headers: request.headers,
    }, upstreamResponse => {
      response.writeHead(upstreamResponse.statusCode || 502, upstreamResponse.headers);
      upstreamResponse.pipe(response);
    });
    upstream.on('error', () => {
      if (!response.headersSent) response.writeHead(502, { 'Content-Type': 'text/plain; charset=utf-8' });
      response.end('MIMAS is starting. Please try again shortly.');
    });
    request.on('aborted', () => upstream.destroy());
    request.pipe(upstream);
  });

  server.on('upgrade', (request, socket, head) => {
    if ((request.url || '').startsWith('/api/') && !VOICE_PATH.test(request.url || '')) {
      socket.end('HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n');
      return;
    }
    const port = VOICE_PATH.test(request.url || '') ? apiPort : nextPort;
    const upstream = net.connect({ host: '127.0.0.1', port });
    let connected = false;
    upstream.once('connect', () => {
      connected = true;
      const headers = [];
      for (let i = 0; i < request.rawHeaders.length; i += 2) {
        headers.push(`${request.rawHeaders[i]}: ${request.rawHeaders[i + 1]}`);
      }
      upstream.write(`GET ${request.url} HTTP/1.1\r\n${headers.join('\r\n')}\r\n\r\n`);
      if (head.length) upstream.write(head);
      socket.pipe(upstream).pipe(socket);
    });
    upstream.on('error', () => {
      if (!connected && !socket.destroyed) {
        socket.end('HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n');
      } else {
        socket.destroy();
      }
    });
    socket.on('error', () => upstream.destroy());
    socket.on('close', () => upstream.destroy());
  });
  return server;
}

if (require.main === module) {
  const port = Number(process.env.PORT || 3000);
  createGateway().listen(port, '0.0.0.0', () => {
    process.stdout.write(`MIMAS web gateway listening on ${port}\n`);
  });
}

module.exports = { createGateway };
