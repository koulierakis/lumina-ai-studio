const path = require('path');

/**
 * Jest 27 (react-scripts 5) predates reliable support for the conditional
 * package exports used by Lexical 0.45 and React Router 7. Node itself
 * resolves those exports correctly, so delegate those packages to Node and
 * keep Jest's resolver for every other dependency.
 */
module.exports = (request, options) => {
  if (request === 'react-router-dom') {
    return path.resolve(
      options.rootDir || __dirname,
      'node_modules/react-router-dom/dist/index.js',
    );
  }

  if (request === 'react-router') {
    return path.resolve(
      options.rootDir || __dirname,
      'node_modules/react-router/dist/development/index.js',
    );
  }

  if (request === 'react-router/dom') {
    return path.resolve(
      options.rootDir || __dirname,
      'node_modules/react-router/dist/development/dom-export.js',
    );
  }

  if (
    request.startsWith('@lexical/')
  ) {
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
