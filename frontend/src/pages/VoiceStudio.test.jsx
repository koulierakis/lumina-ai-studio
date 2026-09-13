import { LUMINA_STYLES, LUMINA_VOICES } from './VoiceStudio';

test('Voice Studio exposes the two built-in Greek LUMINA voices', () => {
  expect(LUMINA_VOICES).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ id: 'lumina-male', language: 'el-GR' }),
      expect.objectContaining({ id: 'lumina-female', language: 'el-GR' }),
    ])
  );
});

test('Voice Studio exposes the five required styles', () => {
  expect(LUMINA_STYLES).toEqual(['Natural', 'Calm', 'Warm', 'Confident', 'Energetic']);
});
