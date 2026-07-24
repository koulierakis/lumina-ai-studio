import { useState } from 'react';
import { useNavigate, Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { toast } from 'sonner';
import { Sparkles } from 'lucide-react';

export default function Login() {
  const { login, user, ready } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState('owner@lumina.local');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);

  if (ready && user) return <Navigate to="/studio/generate" replace />;

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await login(email, password);
      toast.success('Welcome to Lumina');
      nav('/studio/generate', { replace: true });
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'Invalid credentials');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen w-full flex items-center justify-center bg-ink-950 lumina-noise px-6">
      <div className="w-full max-w-md">
        <div className="mb-10 text-left">
          <div className="flex items-baseline gap-2 mb-3">
            <h1 className="font-display text-5xl tracking-tight text-white">Lumina</h1>
            <span className="text-gold text-xs tracking-[0.35em] uppercase font-medium">AI</span>
          </div>
          <p className="text-white/50 text-sm tracking-wide">
            Private desktop studio for identity-preserving image generation.
          </p>
        </div>

        <form
          onSubmit={submit}
          className="lumina-glass rounded-lg p-8 shadow-[0_8px_32px_rgba(0,0,0,0.5)]"
          data-testid="login-form"
        >
          <div className="space-y-5">
            <div>
              <label className="block text-[11px] uppercase tracking-[0.2em] text-white/50 mb-2">Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                data-testid="login-email"
                className="w-full bg-black/50 border border-white/10 rounded px-4 py-3 text-white placeholder:text-white/30 focus:border-gold/50 focus:ring-1 focus:ring-gold/40 outline-none transition-colors"
                autoComplete="username"
                required
              />
            </div>
            <div>
              <label className="block text-[11px] uppercase tracking-[0.2em] text-white/50 mb-2">Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                data-testid="login-password"
                className="w-full bg-black/50 border border-white/10 rounded px-4 py-3 text-white placeholder:text-white/30 focus:border-gold/50 focus:ring-1 focus:ring-gold/40 outline-none transition-colors"
                autoComplete="current-password"
                required
              />
            </div>
            <button
              type="submit"
              disabled={busy}
              data-testid="login-submit"
              className="w-full mt-2 flex items-center justify-center gap-2 bg-gold text-black font-medium py-3 rounded hover:bg-gold-soft disabled:opacity-50 transition-colors"
            >
              <Sparkles strokeWidth={1.5} className="w-4 h-4" />
              {busy ? 'Signing in...' : 'Enter Studio'}
            </button>
          </div>
        </form>

        <p className="mt-6 text-[11px] uppercase tracking-[0.2em] text-white/30 text-center">
          Private single-owner access · no public signup
        </p>
      </div>
    </div>
  );
}
