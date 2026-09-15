import { buildAuthoritativeTranscript } from './speechTranscript';

const result = (transcript, isFinal = true) => ({
  0: { transcript },
  isFinal,
});

describe('buildAuthoritativeTranscript', () => {
  test('keeps arbitrary final speech exactly once', () => {
    const results = [result('Φτιάξε μου έναν καφέ')];
    expect(buildAuthoritativeTranscript(results)).toBe('Φτιάξε μου έναν καφέ');
  });

  test('ignores interim hypotheses instead of accumulating them', () => {
    const results = [
      result('Φτιάξε', false),
      result('Φτιάξε μου', false),
      result('Φτιάξε μου έναν καφέ', true),
    ];
    expect(buildAuthoritativeTranscript(results)).toBe('Φτιάξε μου έναν καφέ');
  });

  test('preserves distinct final segments', () => {
    const results = [result('Άνοιξε το Image Studio'), result('και δημιούργησε μια φωτογραφία')];
    expect(buildAuthoritativeTranscript(results)).toBe(
      'Άνοιξε το Image Studio και δημιούργησε μια φωτογραφία'
    );
  });
});
