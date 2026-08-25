const { createProxyMiddleware } = require('http-proxy-middleware');

// Forward only /api requests to the backend service. Client-side routes
// (e.g. /studio/dashboard) are left to the dev server's history fallback so
// the SPA router keeps working. The backend runs on an internal compose
// network hostname "backend" so no CORS is needed from the browser.
module.exports = function (app) {
  app.use(
    '/api',
    createProxyMiddleware({
      target: 'http://backend:8000',
      changeOrigin: true,
    })
  );
};
