import React from 'react';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { Recorder, VOICE_TABS } from './VoiceStudio';

jest.mock('../lib/api', () => ({
  apiDelete: jest.fn(),
  apiGet: jest.fn(),
  apiPatch: jest.fn(),
  apiPost: jest.fn(),
  uploadFormData: jest.fn(),
}));

test('Voice Studio exposes all user-facing workspaces', () => {
  expect(VOICE_TABS).toEqual(expect.arrayContaining(['Generate Speech', 'Voice Packs', 'Record Voice', 'My Voice', 'Transcribe', 'Talking Video', 'Jobs', 'Audio Library', 'Settings']));
});

describe('Voice recorder safety', () => {
  let host;
  let root;
  let track;
  let stream;
  let recorder;
  let originalMediaRecorder;
  let originalMediaDevices;
  let originalCreateObjectURL;
  let originalRevokeObjectURL;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
    track = { stop: jest.fn() };
    stream = { getTracks: jest.fn(() => [track]) };
    originalMediaRecorder = window.MediaRecorder;
    originalMediaDevices = navigator.mediaDevices;
    originalCreateObjectURL = URL.createObjectURL;
    originalRevokeObjectURL = URL.revokeObjectURL;

    class FakeMediaRecorder {
      constructor(input) {
        this.stream = input;
        this.state = 'inactive';
        this.mimeType = 'audio/webm';
        recorder = this;
      }
      start() { this.state = 'recording'; }
      pause() { this.state = 'paused'; }
      resume() { this.state = 'recording'; }
      stop() {
        this.state = 'inactive';
        this.onstop?.();
      }
    }

    window.MediaRecorder = FakeMediaRecorder;
    global.MediaRecorder = FakeMediaRecorder;
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: jest.fn(async () => stream) },
    });
    URL.createObjectURL = jest.fn(() => 'blob:voice-test');
    URL.revokeObjectURL = jest.fn();
  });

  afterEach(() => {
    act(() => root.unmount());
    host.remove();
    window.MediaRecorder = originalMediaRecorder;
    global.MediaRecorder = originalMediaRecorder;
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: originalMediaDevices });
    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
    jest.restoreAllMocks();
  });

  it('stops the active recorder and microphone when Discard is pressed', async () => {
    await act(async () => root.render(<Recorder packs={[]} reload={jest.fn()} />));
    const button = (label) => [...host.querySelectorAll('button')].find((item) => item.textContent === label);

    await act(async () => button('Start').click());
    expect(recorder.state).toBe('recording');
    expect(track.stop).not.toHaveBeenCalled();

    await act(async () => button('Discard').click());

    expect(recorder.state).toBe('inactive');
    expect(track.stop).toHaveBeenCalledTimes(1);
    expect(host.textContent).toContain('0s · idle');
  });
});