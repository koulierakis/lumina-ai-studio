export function buildAuthoritativeTranscript(results) {
  const finalSegments = [];

  if (!results || typeof results.length !== 'number') return '';

  for (let index = 0; index < results.length; index += 1) {
    const result = results[index];
    if (!result?.isFinal) continue;

    const transcript = result[0]?.transcript?.trim();
    if (transcript) finalSegments.push(transcript);
  }

  return finalSegments.join(' ').replace(/\s+/g, ' ').trim();
}
