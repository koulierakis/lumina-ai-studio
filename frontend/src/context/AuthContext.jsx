import { createContext, useContext } from 'react';

const AuthCtx = createContext(null);

const LOCAL_OWNER = {
  email: 'owner@lumina.local',
};

export function AuthProvider({ children }) {
  const refresh = async () => LOCAL_OWNER;

  const login = async () => ({
    access_token: 'local-owner-mode',
    email: LOCAL_OWNER.email,
  });

  const logout = () => {
    window.location.href = '/studio/dashboard';
  };

  return (
    <AuthCtx.Provider
      value={{
        user: LOCAL_OWNER,
        ready: true,
        login,
        logout,
        refresh,
      }}
    >
      {children}
    </AuthCtx.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error('useAuth must be inside AuthProvider');
  return ctx;
}