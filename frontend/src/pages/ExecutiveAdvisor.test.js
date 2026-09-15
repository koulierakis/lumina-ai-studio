import fs from 'fs';
import path from 'path';

describe('Executive Advisor workspace', () => {
  test('exposes persistent advisory controls, providers and document grounding', () => {
    const page = fs.readFileSync(path.join(__dirname, 'ExecutiveAdvisor.jsx'), 'utf8');
    const app = fs.readFileSync(path.join(__dirname, '..', 'App.js'), 'utf8');
    const registry = fs.readFileSync(path.join(__dirname, '..', 'platform', 'moduleRegistry.js'), 'utf8');

    expect(app).toContain('path="mind" element={<ExecutiveAdvisor />}');
    expect(app).toContain('path="advisor" element={<ExecutiveAdvisor />}');
    expect(registry).toContain("name: 'LUMINA Mind'");
    expect(registry).toContain("route: '/studio/mind'");
    expect(page).toContain("['board', 'Board'");
    expect(page).toContain('Βαθιά ανάλυση');
    expect(page).toContain('Να το θυμάσαι');
    expect(page).toContain('Cloud ανάλυση');
    expect(page).toContain('Έρευνα διαδικτύου');
    expect(page).toContain('SpeechRecognition');
    expect(page).toContain('SpeechSynthesisUtterance');
    expect(page).toContain('exportConversation');
    expect(page).toContain('openai_configured');
    expect(page).toContain("import { documentApi } from '../documents/model'");
    expect(page).toContain('documentApi.importFile');
    expect(page).toContain('Επιλογή από τα Documents');
    expect(page).toContain('MAX_ATTACHED_DOCUMENTS = 3');
    expect(page).toContain('context: documentContext.length ? { documents: documentContext } : {}');
    expect(page).toContain('/runtime/advisor/ask');
    expect(page).toContain('/runtime/advisor/memory');
    expect(page).toContain('/runtime/advisor/profile');
  });
});
