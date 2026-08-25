const { createProxyMiddleware } = require('http-proxy-middleware');

// Forward only /api requests to the backend. Base44/Docker can override the
// target via REACT_APP_PROXY_TARGET, while normal local development keeps the
// localhost backend default. Client-side routes remain handled by the CRA
// history fallback so the SPA router keeps working.
module.exports = function (app) {
  const target = process.env.REACT_APP_PROXY_TARGET || 'http://localhost:8000';

  app.use(
    '/api',
    createProxyMiddleware({
      target,
      changeOrigin: true,
    })
  );
};
