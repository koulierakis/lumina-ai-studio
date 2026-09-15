const { TextDecoder, TextEncoder } = require('util');

// React Router 7 uses the browser Encoding API during module initialization.
// Jest 27's jsdom environment does not expose it even though supported browsers do.
if (!global.TextEncoder) global.TextEncoder = TextEncoder;
if (!global.TextDecoder) global.TextDecoder = TextDecoder;

global.IS_REACT_ACT_ENVIRONMENT = true;
