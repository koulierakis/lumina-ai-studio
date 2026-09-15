import { buildAuthoritativeTranscript } from './speechTranscript';

function speechResult(text, isFinal) {
  const result = [{ transcript: text }];
  result.isFinal = isFinal;
  return result;
}

describe('buildAuthoritativeTranscript', () => {
  test('ignores Chrome interim hypotheses', () => {
    const events = [
      [speechResult('θα', false)],
      [speechResult('θα θέλω', false)],
      [speechResult('θα θέλω να', false)],
      [speechResult('θα θέλω να μου πεις', true)],
    ];

    expect(events.map(buildAuthoritativeTranscript)).toEqual([
      '', '', '', 'θα θέλω να μου πεις',
    ]);
  });

  test('rebuilds multiple authoritative Chrome final segments', () => {
    const results = [
      speechResult('θέλω να μου πεις', true),
      speechResult('τι δυνατότητες έχεις', true),
    ];

    expect(buildAuthoritativeTranscript(results))
      .toBe('θέλω να μου πεις τι δυνατότητες έχεις');
  });

  test('ignores Android WebView interim replacement events', () => {
    const events = [
      [speechResult('θέλω να', false)],
      [speechResult('θέλω να μου πεις', false)],
      [speechResult('θέλω να μου πεις', true), speechResult('τι μπορείς', false)],
      [speechResult('θέλω να μου πεις', true), speechResult('τι μπορείς να κάνεις', false)],
      [speechResult('θέλω να μου πεις', true), speechResult('τι μπορείς να κάνεις', true)],
    ];

    expect(events.map(buildAuthoritativeTranscript)).toEqual([
      '',
      '',
      'θέλω να μου πεις',
      'θέλω να μου πεις',
      'θέλω να μου πεις τι μπορείς να κάνεις',
    ]);
  });

  test('is idempotent when the same final event is repeated', () => {
    const event = [
      speechResult('θέλω να μου πεις', true),
      speechResult('τι δυνατότητες έχεις', true),
    ];

    const first = buildAuthoritativeTranscript(event);
    const second = buildAuthoritativeTranscript(event);

    expect(first).toBe('θέλω να μου πεις τι δυνατότητες έχεις');
    expect(second).toBe(first);
  });

  test('never commits interim text into the final prompt', () => {
    const results = [
      speechResult('αυτή είναι η τελική πρόταση', true),
      speechResult('αυτό το προσωρινό κείμενο δεν πρέπει να σταλεί', false),
    ];

    expect(buildAuthoritativeTranscript(results))
      .toBe('αυτή είναι η τελική πρόταση');
  });
});
