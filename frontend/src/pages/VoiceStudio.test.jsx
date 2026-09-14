import { LUMINA_STYLES, LUMINA_VOICES } from './VoiceStudio';

test('Voice Studio exposes built-in Greek voices and Personal Voice', () => {
  expect(LUMINA_VOICES).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ id: 'lumina-male', language: 'el-GR' }),
      expect.objectContaining({ id: 'lumina-female', language: 'el-GR' }),
      expect.objectContaining({ id: 'personal-user', language: 'el-GR', personal: true }),
    ])
  );
});

test('Voice Studio exposes the six Style Engine v2 personalities', () => {
  expect(LUMINA_STYLES).toEqual(['Natural', 'Calm', 'Warm', 'Professional', 'Energetic', 'Storytelling']);
});
