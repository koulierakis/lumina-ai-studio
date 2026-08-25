import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import { Toaster } from 'sonner';
import StudioLayout from './components/StudioLayout';
import RequireAuth from './components/RequireAuth';
import Login from './pages/Login';
import IdentityPacks from './pages/IdentityPacks';
import Generate from './pages/Generate';
import Gallery from './pages/Gallery';
import ProductivityCenter from './pages/ProductivityCenter';
import Editor from './pages/Editor';
import EditorLanding from './pages/EditorLanding';
import VideoStudio from './pages/VideoStudio';
import Dashboard from './pages/Dashboard';
import DeveloperCenter from './pages/DeveloperCenter';
import VoiceStudio from './pages/VoiceStudio';
import WorkspaceCenter from './pages/WorkspaceCenter';
import ProjectDetail from './pages/ProjectDetail';
import PlatformHub from './pages/PlatformHub';
import CodeCreator from './pages/CodeCreator';
import CodeBuilder from './pages/CodeBuilder';
import DocumentStudio from './pages/DocumentStudio';
import ExecutiveAdvisor from './pages/ExecutiveAdvisor';
import Mentor from './pages/Mentor';
import LuminaDrive from './pages/LuminaDrive';

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
            <Route path="/" element={<Navigate to="/studio/dashboard" replace />} />
            <Route path="/login" element={<Navigate to="/studio/dashboard" replace />} />
            <Route
              path="/studio"
              element={
                <RequireAuth>
                  <StudioLayout />
                </RequireAuth>
              }
            >
              <Route index element={<Navigate to="dashboard" replace />} />
              <Route path="dashboard" element={<Dashboard />} />
              <Route path="advisor" element={<ExecutiveAdvisor />} />
              <Route path="mentor" element={<Mentor />} />
              <Route path="drive" element={<LuminaDrive />} />
              <Route path="developer" element={<DeveloperCenter />} />
              <Route path="code-creator" element={<CodeCreator />} />
              <Route path="code-builder" element={<CodeBuilder />} />
              <Route path="generate" element={<Generate />} />
              <Route path="identity" element={<IdentityPacks />} />
              <Route path="gallery" element={<Gallery />} />
              <Route path="media-library" element={<PlatformHub mode="media" />} />
              <Route path="jobs" element={<PlatformHub mode="jobs" />} />
              <Route path="notifications" element={<PlatformHub mode="notifications" />} />
              <Route path="editor" element={<EditorLanding />} />
              <Route path="editor/:mediaId" element={<Editor />} />
              <Route path="video-studio" element={<VideoStudio />} />
              <Route path="voice-studio" element={<VoiceStudio />} />
              <Route path="projects" element={<WorkspaceCenter mode="projects" />} />
              <Route path="projects/:projectId" element={<ProjectDetail />} />
              <Route path="documents" element={<DocumentStudio />} />
              <Route path="finance" element={<ProductivityCenter mode="finance" />} />
              <Route path="research" element={<ProductivityCenter mode="research" />} />
              <Route path="automations" element={<ProductivityCenter mode="automations" />} />
              <Route path="settings" element={<WorkspaceCenter mode="settings" />} />
              <Route path="search" element={<WorkspaceCenter mode="search" />} />
            </Route>
            <Route path="*" element={<Navigate to="/studio/dashboard" replace />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </div>
  );
}
