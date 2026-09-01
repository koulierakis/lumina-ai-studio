// craco.config.js
const path = require("path");
require("dotenv").config();

const isDevServer = process.env.NODE_ENV !== "production";
const config = { enableHealthCheck: process.env.ENABLE_HEALTH_CHECK === "true" };

function makeDevServerV5Compatible(devServerConfig) {
  const { https, onAfterSetupMiddleware, onBeforeSetupMiddleware, onListening, setupMiddlewares, ...compatibleConfig } = devServerConfig;
  compatibleConfig.server = typeof https === "object" ? { type: "https", options: https } : https ? "https" : "http";
  compatibleConfig.headers = { ...compatibleConfig.headers, "Cross-Origin-Resource-Policy": "same-origin" };
  // The phone only talks to the LUMINA web address. The dev server forwards
  // /api internally to the backend, so 127.0.0.1 never points at the phone.
  compatibleConfig.proxy = compatibleConfig.proxy || [{
    context: ["/api"],
    target: process.env.LUMINA_BACKEND_PROXY || "http://127.0.0.1:8000",
    changeOrigin: false,
    secure: false,
  }];
  if (onBeforeSetupMiddleware || setupMiddlewares) {
    compatibleConfig.setupMiddlewares = (middlewares, devServer) => {
      if (onBeforeSetupMiddleware) onBeforeSetupMiddleware(devServer);
      return setupMiddlewares ? setupMiddlewares(middlewares, devServer) : middlewares;
    };
  }
  compatibleConfig.onListening = (devServer) => {
    devServer.close ??= (callback) => devServer.stopCallback(callback);
    if (onListening) onListening(devServer);
    if (onAfterSetupMiddleware) onAfterSetupMiddleware(devServer);
  };
  return compatibleConfig;
}

let WebpackHealthPlugin;
let setupHealthEndpoints;
let healthPluginInstance;
if (config.enableHealthCheck) {
  WebpackHealthPlugin = require("./plugins/health-check/webpack-health-plugin");
  setupHealthEndpoints = require("./plugins/health-check/health-endpoints");
  healthPluginInstance = new WebpackHealthPlugin();
}

let webpackConfig = {
  eslint: { configure: { extends: ["plugin:react-hooks/recommended"], rules: { "react-hooks/rules-of-hooks": "error", "react-hooks/exhaustive-deps": "warn" } } },
  jest: {
    configure: (jestConfig) => ({
      ...jestConfig,
      resolver: path.resolve(__dirname, 'jest.lexical-resolver.js'),
    }),
  },
  webpack: {
    alias: { '@': path.resolve(__dirname, 'src') },
    configure: (webpackConfig) => {
      webpackConfig.watchOptions = { ...webpackConfig.watchOptions, ignored: ['**/node_modules/**','**/.git/**','**/build/**','**/dist/**','**/coverage/**','**/public/**'] };
      if (config.enableHealthCheck && healthPluginInstance) webpackConfig.plugins.push(healthPluginInstance);
      return webpackConfig;
    },
  },
};

webpackConfig.devServer = (devServerConfig) => {
  if (config.enableHealthCheck && setupHealthEndpoints && healthPluginInstance) {
    const originalSetupMiddlewares = devServerConfig.setupMiddlewares;
    devServerConfig.setupMiddlewares = (middlewares, devServer) => {
      if (originalSetupMiddlewares) middlewares = originalSetupMiddlewares(middlewares, devServer);
      setupHealthEndpoints(devServer, healthPluginInstance);
      return middlewares;
    };
  }
  return devServerConfig;
};

if (isDevServer) {
  try {
    const { withVisualEdits } = require("@emergentbase/visual-edits/craco");
    webpackConfig = withVisualEdits(webpackConfig);
  } catch (err) {
    if (!(err.code === 'MODULE_NOT_FOUND' && err.message.includes('@emergentbase/visual-edits/craco'))) throw err;
  }
}

const configureDevServer = webpackConfig.devServer;
webpackConfig.devServer = (devServerConfig) => makeDevServerV5Compatible(configureDevServer(devServerConfig));
module.exports = webpackConfig;
