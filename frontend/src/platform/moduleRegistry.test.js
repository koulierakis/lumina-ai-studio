import { MODULE_REGISTRY, navigationModules } from './moduleRegistry';

describe('central module registry', () => {
  it('contains unique, navigable visible modules in display order', () => {
    expect(new Set(MODULE_REGISTRY.map((item) => item.id)).size).toBe(MODULE_REGISTRY.length);
    expect(navigationModules().every((item) => item.route.startsWith('/studio/'))).toBe(true);
    expect(navigationModules().map((item) => item.id)).toContain('projects');
  });
});
