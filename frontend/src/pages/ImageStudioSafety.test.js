import fs from 'fs';
import path from 'path';

function source(name) {
  return fs.readFileSync(path.join(__dirname, name), 'utf8');
}

describe('Image Studio production safety invariants', () => {
  test('generation UI only offers healthy identity-capable providers for explicit selection', () => {
    const generate = source('Generate.jsx');
    expect(generate).toContain("item.capabilities?.identity_references === true");
    expect(generate).toContain('item.configured && item.healthy && identityReady');
    expect(generate).toContain('no identity references');
    expect(generate).toContain('navigate(`/studio/editor/${mid}`)');
  });

  test('gallery viewer stays synchronized after favorite changes', () => {
    const gallery = source('Gallery.jsx');
    expect(gallery).toContain("setViewer((current) => (current?.id === item.id ? data : current))");
  });

  test('AI editor hides cancellation once result persistence has started', () => {
    const panels = fs.readFileSync(path.join(__dirname, '../editor/Sprint3Panels.jsx'), 'utf8');
    expect(panels).toContain("activeAiJob.status !== 'finalizing'");
  });

  test('identity pack upload guidance matches the backend image limit', () => {
    const packs = source('IdentityPacks.jsx');
    expect(packs).toContain('max 25MB each');
  });
});
