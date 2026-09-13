import { LUMINA_STYLES, LUMINA_VOICES } from './VoiceStudio';

test('Voice Studio exposes the two built-in Greek voices', () => {
  expect(LUMINA_VOICES).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ id: 'andreas', name: 'Ανδρέας', providerVoice: 'el-GR-NestorasNeural' }),
      expect.objectContaining({ id: 'ariadni', name: 'Αριάδνη', providerVoice: 'el-GR-AthinaNeural' }),
    ])
  );
});

test('Voice Studio exposes the five delivery styles', () => {
  expect(LUMINA_STYLES).toEqual(['Natural', 'Calm', 'Warm', 'Confident', 'Energetic']);
});
