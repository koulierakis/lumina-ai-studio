import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { api } from '../lib/api';

const AuthCtx = createContext(null);

const LOCAL_OWNER = {
  email: 'owner@lumina.local',
};

// Local development keeps the desktop workflow frictionless. Production
// builds always use the backend login/token flow.
const LOCAL_DEV_AUTH = process.env.NODE_ENV !== 'production' && process.env.REACT_APP_LOCAL_DEV_AUTH !== 'false';

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    const cached = localStorage.getItem('lumina_user');
    if (cached) {
      try { return JSON.parse(cached); } catch { localStorage.removeItem('lumina_user'); }
    }
    return LOCAL_DEV_AUTH ? LOCAL_OWNER : null;
  });
  const [ready, setReady] = useState(false);

  const refresh = async () => {
    const token = localStorage.getItem('lumina_token');
    if (!token && LOCAL_DEV_AUTH) {
      setUser(LOCAL_OWNER);
      return LOCAL_OWNER;
    }
    if (!token) {
      setUser(null);
      return null;
    }
    try {
      const response = await api.get('/auth/me');
      const nextUser = { email: response.data.email };
      setUser(nextUser);
      localStorage.setItem('lumina_user', JSON.stringify(nextUser));
      return nextUser;
    } catch (error) {
      localStorage.removeItem('lumina_token');
      localStorage.removeItem('lumina_user');
      setUser(null);
      throw error;
    }
  };

  const login = async (email, password) => {
    const response = await api.post('/auth/login', { email, password }, { retry: false });
    const session = response.data;
    const nextUser = { email: session.email };
    localStorage.setItem('lumina_token', session.access_token);
    localStorage.setItem('lumina_user', JSON.stringify(nextUser));
    setUser(nextUser);
    return session;
  };

  const logout = () => {
    localStorage.removeItem('lumina_token');
    localStorage.removeItem('lumina_user');
    setUser(null);
    window.location.href = '/login';
  };

  useEffect(() => {
    refresh().catch(() => undefined).finally(() => setReady(true));
  }, []);

  const value = useMemo(() => ({ user, ready, login, logout, refresh }), [user, ready]);

  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error('useAuth must be inside AuthProvider');
  return ctx;
}
