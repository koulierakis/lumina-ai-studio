const path = require('path');

/**
 * Jest 27 (react-scripts 5) predates reliable support for the conditional
 * package exports used by Lexical 0.45. Node itself resolves those exports
 * correctly, so delegate Lexical subpaths to Node and keep Jest's resolver
 * for every other dependency.
 */
module.exports = (request, options) => {
  if (request.startsWith('@lexical/')) {
    try {
      return require.resolve(request, {
        paths: [options.basedir, path.resolve(options.rootDir || __dirname, 'node_modules')],
      });
    } catch {
      // Fall through so Jest emits its normal, actionable resolution error.
    }
  }

  return options.defaultResolver(request, options);
};
