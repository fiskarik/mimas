/** @type {import('next').NextConfig} */
const config = (phase) => ({
  distDir: phase === 'phase-development-server' ? '.next-dev' : '.next',
  output: 'standalone',
  experimental: { proxyTimeout: 180000 },
  async rewrites() { return [{ source: '/api/:path*', destination: 'http://127.0.0.1:8000/api/:path*' }]; },
});
export default config;
