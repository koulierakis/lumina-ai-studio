import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import { Toaster } from 'sonner';
import StudioLayout from './components/StudioLayout';
import RequireAuth from './components/RequireAuth';
import Login from './pages/Login';
import IdentityPacks from './pages/IdentityPacks';
import Generate from './pages/Generate';
import Gallery from './pages/Gallery';
import ComingSoon from './pages/ComingSoon';
import Editor from './pages/Editor';
import EditorLanding from './pages/EditorLanding';

export default function App() {
  return (
    <div className="App min-h-screen bg-ink-950 text-foreground">
      <BrowserRouter>
        <AuthProvider>
          <Toaster
            theme="dark"
            position="bottom-right"
            toastOptions={{
              style: {
                background: '#111',
                border: '1px solid rgba(255,255,255,0.08)',
                color: '#f5f5f5',
              },
            }}
          />
          <Routes>
            <Route path="/" element={<Navigate to="/studio/generate" replace />} />
            <Route path="/login" element={<Login />} />
            <Route
              path="/studio"
              element={
                <RequireAuth>
                  <StudioLayout />
                </RequireAuth>
              }
            >
              <Route index element={<Navigate to="generate" replace />} />
              <Route path="generate" element={<Generate />} />
              <Route path="identity" element={<IdentityPacks />} />
              <Route path="gallery" element={<Gallery />} />
              <Route path="editor" element={<EditorLanding />} />
              <Route path="editor/:mediaId" element={<Editor />} />
              <Route path="projects" element={<ComingSoon title="Projects" />} />
              <Route path="settings" element={<ComingSoon title="Settings" />} />
            </Route>
            <Route path="*" element={<Navigate to="/studio/generate" replace />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </div>
  );
}
