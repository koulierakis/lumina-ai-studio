import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowLeft, CheckCircle2, CircleAlert, Code2, Loader2, Mic, MicOff, MonitorPlay,
  Play, RefreshCw, RotateCcw, Volume2, VolumeX, XCircle,
} from 'lucide-react';
import { useVoiceGuidance } from '../lib/useVoiceGuidance';

const API = '/api/code-builder-v2';

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
  return data;
}

function StatusBadge({ status }) {
  const label = (status || 'idle').replaceAll('_', ' ');
  return <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-0.5 text-xs uppercase tracking-wider text-cyan-300">{label}</span>;
}

export default function CodeBuilderV2() {
  const [prompt, setPrompt] = useState('');
  const [model, setModel] = useState('qwen2.5-coder:7b');
  const [task, setTask] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [centerTab, setCenterTab] = useState('preview');
  const [previewPath, setPreviewPath] = useState('/studio/dashboard');
  const [iframeKey, setIframeKey] = useState(0);

  const voiceGuide = useVoiceGuidance({
    onTranscript: (transcript) => {
      setPrompt((prev) => (prev ? `${prev} ${transcript}` : transcript));
    },
  });

  const refresh = useCallback(async () => {
    if (!task?.id) return;
    try {
      const next = await api(`/tasks/${task.id}`);
      setTask(next);
    } catch (err) {
      setError(err.message);
    }
  }, [task?.id]);

  useEffect(() => {
    if (!task?.id || !['queued', 'planning', 'executing', 'validating'].includes(task.status)) return undefined;
    const timer = window.setInterval(refresh, 1000);
    return () => window.clearInterval(timer);
  }, [task?.id, task?.status, refresh]);

  const canExecute = task?.status === 'awaiting_approval';
  const canCancel = task && !['completed', 'failed', 'cancelled', 'rolled_back'].includes(task.status);
  const canRollback = task?.status === 'completed' && task?.execution?.backup_id;
  const elapsed = useMemo(() => {
    if (!task?.created_at) return null;
    return Math.max(0, Math.floor((Date.now() - new Date(task.created_at).getTime()) / 1000));
  }, [task?.created_at]);

  async function createTask(event) {
    event.preventDefault();
    if (prompt.trim().length < 3) return;
    setBusy(true);
    setError('');
    try {
      const created = await api('/tasks', {
        method: 'POST',
        body: JSON.stringify({ prompt: prompt.trim(), model: model.trim() || null, auto_apply: false, autonomous: true, max_attempts: 3, timeout_seconds: 300 }),
      });
      setTask(created);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function action(name) {
    if (!task?.id) return;
    setBusy(true);
    setError('');
    try {
      setTask(await api(`/tasks/${task.id}/${name}`, { method: 'POST' }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="h-screen w-full flex flex-col lg:flex-row overflow-hidden bg-ink-950 text-foreground" data-testid="code-builder-v2-page">
      {/* ─── ΑΡΙΣΤΕΡΗ ΣΤΗΛΗ ΕΛΕΓΧΟΥ (LEFT CONTROL PANEL) ─── */}
      <aside className="w-full lg:w-[420px] lg:min-w-[380px] lg:max-w-[450px] h-full flex flex-col border-r border-white/10 bg-ink-950/95 overflow-y-auto shrink-0 z-20 p-4 sm:p-5 space-y-4">
        {/* Row 1: Back to Home + Tool Badge */}
        <div className="flex items-center justify-between gap-2 border-b border-white/[0.08] pb-3">
          <Link
            to="/studio/dashboard"
            data-testid="code-builder-v2-back-home"
            className="inline-flex items-center gap-1.5 rounded-lg border border-gold/40 bg-gold/15 px-3 py-1.5 text-xs font-bold text-gold hover:bg-gold hover:text-black transition shadow-sm"
            title="Επιστροφή στην Αρχική Οθόνη"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            <span>← Επιστροφή στην Αρχική</span>
          </Link>
          <span className="flex items-center gap-1.5 text-xs font-semibold text-white/90">
            <Code2 className="h-4 w-4 text-cyan-400" />
            <span>Code Builder V2</span>
          </span>
        </div>

        {/* Row 2: Status & Time */}
        <div className="flex items-center justify-between gap-2 bg-white/[0.025] border border-white/[0.07] rounded-xl p-2.5">
          <StatusBadge status={task?.status} />
          {elapsed !== null && <span className="text-xs text-zinc-400 font-mono">{elapsed}s</span>}
          <button
            type="button"
            onClick={refresh}
            disabled={!task?.id || busy}
            className="rounded border border-white/10 p-1 text-xs text-white/60 hover:text-white"
            title="Ανανέωση κατάστασης"
          >
            <RefreshCw className="h-3 w-3" />
          </button>
        </div>

        {/* Row 3: Φωνητική Καθοδήγηση & Φωνητική Υπαγόρευση */}
        <div className="rounded-xl border border-white/10 bg-black/40 p-3 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-cyan-300 flex items-center gap-1.5">
              <Volume2 className="h-3.5 w-3.5" />
              <span>Φωνητική Καθοδήγηση</span>
            </span>
            <span className="text-[10px] text-white/40">Voice Assistant</span>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => {
                if (voiceGuide.isSpeaking) {
                  voiceGuide.stopSpeaking();
                } else {
                  voiceGuide.speak('Καλώς ήρθατε στο Code Builder V2. Στην αριστερή στήλη μπορείτε να γράψετε αναλυτικά τις προδιαγραφές του κώδικα ή να πατήσετε το μικρόφωνο για υπαγόρευση. Στη συνέχεια πατήστε Δημιουργία Αυτόνομου Πλάνου. Στο κεντρικό παράθυρο βλέπετε το πλάνο, τα αρχεία και τη ζωντανή προεπισκόπηση.');
                }
              }}
              className={`inline-flex items-center justify-center gap-1.5 rounded-lg border px-2.5 py-2 text-xs font-medium transition ${
                voiceGuide.isSpeaking
                  ? 'border-cyan-400 bg-cyan-400/20 text-cyan-200 animate-pulse'
                  : 'border-white/10 bg-white/[0.04] text-white/80 hover:bg-white/10 hover:text-white'
              }`}
              title="Ακούστε οδηγίες χρήσης στα Ελληνικά"
            >
              {voiceGuide.isSpeaking ? <VolumeX className="h-3.5 w-3.5" /> : <Volume2 className="h-3.5 w-3.5 text-cyan-400" />}
              <span>{voiceGuide.isSpeaking ? 'Διακοπή' : 'Ακρόαση Οδηγιών'}</span>
            </button>
            <button
              type="button"
              onClick={voiceGuide.toggleListening}
              className={`inline-flex items-center justify-center gap-1.5 rounded-lg border px-2.5 py-2 text-xs font-medium transition ${
                voiceGuide.isListening
                  ? 'border-red-400 bg-red-400/20 text-red-200 animate-pulse'
                  : 'border-white/10 bg-white/[0.04] text-white/80 hover:bg-white/10 hover:text-white'
              }`}
              title="Φωνητική υπαγόρευση εντολής με μικρόφωνο"
            >
              {voiceGuide.isListening ? <MicOff className="h-3.5 w-3.5" /> : <Mic className="h-3.5 w-3.5 text-red-400" />}
              <span>{voiceGuide.isListening ? 'Ακρόαση…' : 'Υπαγόρευση'}</span>
            </button>
          </div>
          {voiceGuide.voiceMessage && (
            <p className="text-[11px] text-cyan-300 font-mono bg-cyan-400/10 rounded-md p-1.5">
              {voiceGuide.voiceMessage}
            </p>
          )}
        </div>

        {/* Row 4: Άνετο Μεγάλο Κουτί Prompt */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label htmlFor="cbv2-prompt" className="text-xs font-semibold text-white/90">
              Περιγραφή Εργασίας / Prompt:
            </label>
            <span className="text-[10px] text-white/40">{prompt.length} χαρακτήρες</span>
          </div>
          <div className="relative rounded-xl border border-white/15 bg-black/60 focus-within:border-cyan-400/60 shadow-inner">
            <textarea
              id="cbv2-prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={7}
              placeholder="Γράψτε εδώ με άνεση τι θέλετε να φτιάξει ή να διορθώσει αυτόνομα το σύστημα (π.χ. Δημιούργησε endpoint /health-details και πρόσθεσε unit tests)..."
              className="w-full bg-transparent p-3.5 text-sm text-white placeholder:text-white/30 outline-none resize-y leading-relaxed"
            />
          </div>
          {/* Quick template chips */}
          <div className="flex flex-wrap gap-1.5 pt-1">
            {[
              'Autonomous plan & validation',
              'Προσθήκη νέου API endpoint',
              'Διόρθωση σφαλμάτων build',
            ].map((tmpl) => (
              <button
                key={tmpl}
                type="button"
                onClick={() => setPrompt((prev) => (prev ? `${prev}\n${tmpl}` : tmpl))}
                className="text-[10px] rounded-md border border-white/10 bg-white/[0.03] px-2 py-0.5 text-white/60 hover:text-cyan-300 hover:border-cyan-400/30 transition"
              >
                + {tmpl}
              </button>
            ))}
          </div>
        </div>

        {/* Row 5: Model Selection */}
        <div className="rounded-xl border border-white/10 bg-black/30 p-3 space-y-2">
          <label className="text-xs text-white/60 block">AI Coding Model:</label>
          <input
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="w-full rounded-lg border border-white/10 bg-black/60 px-3 py-1.5 text-xs text-white outline-none focus:border-cyan-400/50"
          />
        </div>

        {/* Row 6: Actions */}
        <div className="space-y-2 pt-1">
          <button
            type="button"
            onClick={createTask}
            disabled={busy || prompt.trim().length < 3}
            className="w-full inline-flex items-center justify-center gap-2 rounded-xl bg-cyan-500 px-4 py-3 text-sm font-bold text-black transition hover:bg-cyan-400 hover:shadow-lg disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4 fill-current" />}
            <span>{busy ? 'Επεξεργασία…' : '⚡ Δημιουργία Αυτόνομου Πλάνου'}</span>
          </button>

          {canExecute && (
            <button
              onClick={() => action('execute')}
              disabled={busy}
              className="w-full inline-flex items-center justify-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-2 text-xs font-bold text-black hover:bg-emerald-400"
            >
              <CheckCircle2 className="h-3.5 w-3.5" />
              <span>Εκτέλεση Πλάνου (Execute)</span>
            </button>
          )}

          {canCancel && (
            <button
              onClick={() => action('cancel')}
              disabled={busy}
              className="w-full inline-flex items-center justify-center gap-1.5 rounded-lg border border-amber-400/30 px-3 py-2 text-xs text-amber-200 hover:bg-amber-400/10"
            >
              <XCircle className="h-3.5 w-3.5" />
              <span>Ακύρωση (Cancel)</span>
            </button>
          )}

          {canRollback && (
            <button
              onClick={() => action('rollback')}
              disabled={busy}
              className="w-full inline-flex items-center justify-center gap-1.5 rounded-lg border border-violet-400/30 px-3 py-2 text-xs text-violet-200 hover:bg-violet-400/10"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              <span>Επαναφορά (Rollback)</span>
            </button>
          )}

          {error && (
            <div className="flex items-center gap-1.5 rounded-lg border border-red-400/30 bg-red-500/10 p-2 text-xs text-red-300">
              <CircleAlert className="h-3.5 w-3.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}
        </div>

        {/* Row 7: Center View Selector */}
        <div className="border-t border-white/10 pt-3 space-y-1.5">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-white/50 block">
            Προβολή στο Κέντρο:
          </span>
          <div className="grid grid-cols-3 gap-1.5 text-xs">
            <button
              type="button"
              onClick={() => setCenterTab('preview')}
              className={`p-2 rounded-lg text-center transition font-semibold ${
                centerTab === 'preview' ? 'bg-cyan-500 text-black shadow' : 'bg-white/[0.03] text-white/70 hover:bg-white/[0.08] hover:text-white'
              }`}
            >
              🖥️ Preview
            </button>
            <button
              type="button"
              onClick={() => setCenterTab('plan')}
              className={`p-2 rounded-lg text-center transition font-semibold ${
                centerTab === 'plan' ? 'bg-cyan-500 text-black shadow' : 'bg-white/[0.03] text-white/70 hover:bg-white/[0.08] hover:text-white'
              }`}
            >
              📄 Plan
            </button>
            <button
              type="button"
              onClick={() => setCenterTab('activity')}
              className={`p-2 rounded-lg text-center transition font-semibold ${
                centerTab === 'activity' ? 'bg-cyan-500 text-black shadow' : 'bg-white/[0.03] text-white/70 hover:bg-white/[0.08] hover:text-white'
              }`}
            >
              📜 Events
            </button>
          </div>
        </div>
      </aside>

      {/* ─── ΚΕΝΤΡΟ: ΠΑΡΑΘΥΡΟ ΖΩΝΤΑΝΗΣ ΠΡΟΕΠΙΣΚΟΠΗΣΗΣ & ΧΩΡΟΣ ΕΡΓΑΣΙΑΣ ─── */}
      <section className="flex-1 h-full flex flex-col bg-black/70 overflow-hidden">
        {centerTab === 'preview' ? (
          <div className="flex flex-col h-full w-full overflow-hidden">
            {/* Live Preview Top Bar */}
            <div className="flex flex-wrap items-center justify-between border-b border-white/10 bg-white/[0.03] px-4 py-2.5 text-xs gap-2 shrink-0">
              <div className="flex items-center gap-2 flex-1">
                <span className="flex items-center gap-1.5 rounded-full border border-emerald-400/30 bg-emerald-500/10 px-2.5 py-1 text-[11px] font-semibold text-emerald-300">
                  <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
                  <span>ΖΩΝΤΑΝΗ ΠΡΟΕΠΙΣΚΟΠΗΣΗ (LIVE PREVIEW)</span>
                </span>
                <button
                  type="button"
                  onClick={() => setIframeKey((k) => k + 1)}
                  className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-black/40 px-2.5 py-1 text-white/70 hover:bg-white/10 hover:text-white transition"
                  title="Reload"
                >
                  <RefreshCw className="h-3 w-3" />
                  <span>Reload</span>
                </button>
                <div className="flex items-center gap-1 rounded-md border border-white/10 bg-black/60 px-2.5 py-1 flex-1 max-w-sm">
                  <span className="text-[10px] text-white/40">URL:</span>
                  <input
                    type="text"
                    value={previewPath}
                    onChange={(e) => setPreviewPath(e.target.value)}
                    className="w-full bg-transparent text-[11px] text-cyan-300 font-mono outline-none"
                  />
                </div>
              </div>
              <a
                href={previewPath}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/5 px-2.5 py-1 text-white/70 hover:bg-white/10 hover:text-white text-[11px]"
              >
                <span>Νέα Καρτέλα ↗</span>
              </a>
            </div>
            {/* Live Preview Iframe */}
            <div className="flex-1 w-full bg-ink-950 p-2 sm:p-4 flex items-center justify-center overflow-hidden">
              <iframe
                key={iframeKey}
                src={previewPath}
                title="Code Builder V2 Live Preview"
                className="w-full h-full rounded-xl border border-white/15 bg-ink-950 shadow-2xl"
              />
            </div>
          </div>
        ) : centerTab === 'plan' ? (
          <div className="flex-1 h-full overflow-y-auto p-5 sm:p-8 space-y-6">
            <h2 className="text-xl font-bold text-white flex items-center gap-2">
              <Code2 className="h-5 w-5 text-cyan-400" />
              <span>Αυτόνομο Πλάνο Εκτέλεσης (Execution Plan)</span>
            </h2>
            {!task?.plan ? (
              <div className="rounded-2xl border border-white/10 bg-zinc-950/60 p-8 text-center text-white/40">
                Δεν έχει δημιουργηθεί ακόμη πλάνο. Συμπληρώστε το prompt στα αριστερά και πατήστε «Δημιουργία Αυτόνομου Πλάνου».
              </div>
            ) : (
              <div className="space-y-4">
                <div className="rounded-xl border border-white/10 bg-black/40 p-4">
                  <h3 className="text-xs uppercase tracking-wider text-cyan-400 font-semibold mb-1">Περίληψη:</h3>
                  <p className="text-sm text-zinc-300 leading-relaxed">{task.plan.summary}</p>
                </div>
                <div className="space-y-2">
                  <h3 className="text-xs uppercase tracking-wider text-white/60 font-semibold">Προτεινόμενες Αλλαγές:</h3>
                  {task.plan.changes?.map((change, index) => (
                    <div key={`${change.path}-${index}`} className="rounded-xl border border-white/10 bg-black/30 p-3.5">
                      <div className="flex items-center justify-between gap-3">
                        <code className="break-all text-xs text-cyan-300 font-mono">{change.path}</code>
                        <span className="text-[10px] uppercase tracking-wider rounded bg-white/10 px-2 py-0.5 text-zinc-300">{change.operation}</span>
                      </div>
                      <p className="mt-2 text-xs text-zinc-400">{change.reason}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="flex-1 h-full overflow-y-auto p-5 sm:p-8 space-y-4">
            <h2 className="text-xl font-bold text-white">Καταγραφή Συμβάντων & Ενεργειών (Live Activity)</h2>
            <div className="space-y-3">
              {(task?.events || []).slice().reverse().map((event, index) => (
                <div key={`${event.at}-${index}`} className="rounded-xl border border-white/10 bg-black/30 p-3 border-l-4 border-l-cyan-400">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-semibold text-cyan-300">{event.phase?.replaceAll('_', ' ')}</span>
                    <span className="text-zinc-500 font-mono">{new Date(event.at).toLocaleTimeString()}</span>
                  </div>
                  <p className="mt-1 text-xs text-zinc-300">{event.message}</p>
                </div>
              ))}
              {!task?.events?.length && <p className="text-sm text-zinc-500">Δεν υπάρχουν συμβάντα προς το παρόν.</p>}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
