import { VOICE_TABS } from './VoiceStudio';

test('Voice Studio exposes all user-facing workspaces', () => {
  expect(VOICE_TABS).toEqual(expect.arrayContaining(['Generate Speech', 'Voice Packs', 'Record Voice', 'Transcribe', 'Talking Video', 'Jobs', 'Audio Library', 'Settings']));
});
