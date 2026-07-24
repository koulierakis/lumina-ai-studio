import { useAuth } from '../context/AuthContext';
import { Navigate, useLocation } from 'react-router-dom';

export default function RequireAuth({ children }) {
  const { user, ready } = useAuth();
  const location = useLocation();
  if (!ready) return <div className="min-h-screen bg-ink-950" />;
  if (!user) return <Navigate to="/login" state={{ from: location }} replace />;
  return children;
}
