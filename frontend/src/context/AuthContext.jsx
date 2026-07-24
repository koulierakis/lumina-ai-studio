import { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { apiGet, apiPost } from '../lib/api';

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);

  const refresh = useCallback(async () => {
    const token = localStorage.getItem('lumina_token');
    if (!token) {
      setUser(null);
      setReady(true);
      return;
    }
    try {
      const data = await apiGet('/auth/me');
      setUser(data);
    } catch {
      setUser(null);
    } finally {
      setReady(true);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const login = async (email, password) => {
    const data = await apiPost('/auth/login', { email, password });
    localStorage.setItem('lumina_token', data.access_token);
    setUser({ email: data.email });
    return data;
  };

  const logout = () => {
    localStorage.removeItem('lumina_token');
    setUser(null);
    window.location.href = '/login';
  };

  return (
    <AuthCtx.Provider value={{ user, ready, login, logout, refresh }}>
      {children}
    </AuthCtx.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error('useAuth must be inside AuthProvider');
  return ctx;
}
