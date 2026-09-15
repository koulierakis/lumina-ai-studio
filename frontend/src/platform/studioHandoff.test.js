import { detectStudioIntent, handoffForTarget, STUDIO_TARGETS } from './studioHandoff';

describe('LUMINA Mind studio handoff', () => {
  test.each([
    ['Θέλω να μου φτιάξεις ένα επαγγελματικό έγγραφο', 'document'],
    ['Δημιούργησε μια φωτογραφία 9:16 για το Athletico', 'image'],
    ['Κάνε ένα βίντεο πέντε δευτερολέπτων', 'video'],
    ['Ετοίμασε ηχητικό με γυναικεία φωνή', 'voice'],
  ])('routes a creation request to the correct studio', (message, target) => {
    expect(detectStudioIntent(message)).toEqual(expect.objectContaining({
      target,
      route: STUDIO_TARGETS[target].route,
      prompt: message,
      autoRun: true,
      source: 'lumina-mind',
    }));
  });

  test('does not hijack normal advisory questions', () => {
    expect(detectStudioIntent('Τι γνώμη έχεις για αυτή τη φωτογραφία;')).toBeNull();
    expect(detectStudioIntent('Πώς πρέπει να οργανώσω την εταιρεία;')).toBeNull();
  });

  test('routes image-to-video wording to Video Studio instead of Image Studio', () => {
    expect(detectStudioIntent('Φτιάξε βίντεο από αυτή τη φωτογραφία')).toEqual(expect.objectContaining({ target: 'video' }));
  });

  test('carries explicit production settings to the target studio', () => {
    expect(detectStudioIntent('Δημιούργησε βίντεο 9:16 για 8 δευτερόλεπτα').options).toEqual(expect.objectContaining({ aspect: '9:16', duration: 8, language: 'el' }));
    expect(detectStudioIntent('Ετοίμασε ηχητικό με ανδρική φωνή').options).toEqual(expect.objectContaining({ voiceId: 'andreas' }));
  });

  test('a studio only accepts a valid handoff addressed to itself', () => {
    const studioHandoff = detectStudioIntent('Φτιάξε μια εικόνα προϊόντος');
    expect(handoffForTarget({ studioHandoff }, 'image')).toBe(studioHandoff);
    expect(handoffForTarget({ studioHandoff }, 'video')).toBeNull();
    expect(handoffForTarget({}, 'image')).toBeNull();
  });
});
