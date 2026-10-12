import express from 'express';
import cors from 'cors';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';
import { execSync } from 'child_process';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = 3000;
const HOST = '0.0.0.0';

app.use(cors());
app.use(express.json({ limit: '50mb' }));
app.use(express.urlencoded({ extended: true, limit: '50mb' }));

// Ensure frontend build exists
const frontendBuildDir = path.join(__dirname, 'frontend', 'build');
const indexHtml = path.join(frontendBuildDir, 'index.html');

if (!fs.existsSync(indexHtml)) {
  console.log('[LUMINA] Building frontend assets...');
  try {
    execSync('npm run build', { cwd: __dirname, stdio: 'inherit' });
  } catch (err) {
    console.error('[LUMINA] Frontend build failed:', err);
  }
}

// In-memory data store
const db = {
  media: [],
  jobs: [],
  projects: [],
  identityPacks: [],
  documents: [],
  developerTasks: [],
};

// API Routes
const api = express.Router();

// Auth
api.post('/auth/login', (req, res) => {
  const email = req.body?.email || 'owner@lumina.local';
  res.json({
    email,
    access_token: 'lumina_token_' + Buffer.from(email).toString('base64'),
  });
});

api.get('/auth/me', (req, res) => {
  res.json({
    email: 'owner@lumina.local',
    role: 'owner',
    name: 'LUMINA Owner',
  });
});

// System & Health
api.get('/health', (req, res) => {
  res.json({ status: 'ok', healthy: true });
});

api.get('/system/status', (req, res) => {
  res.json({
    status: 'healthy',
    version: '0.1.1',
    uptime: process.uptime(),
    node: process.version,
  });
});

api.get('/system/runtime-settings', (req, res) => {
  res.json({
    env: process.env.NODE_ENV || 'development',
    storage: 'memory',
    model: 'gemini-3.8-flash',
  });
});

// Workspace & Dashboard
api.get('/workspace/overview', (req, res) => {
  res.json({
    media: db.media,
    jobs: db.jobs,
    projects: db.projects,
    readiness: {
      providers: [
        { id: 'gemini', name: 'Google Gemini', available: true, ready: true, description: 'Multimodal generative AI' },
      ],
      status: 'ok',
    },
    panel_errors: {},
  });
});

api.get('/providers', (req, res) => {
  res.json([
    { id: 'gemini', name: 'Google Gemini', available: true, ready: true, description: 'Multimodal generative AI' },
  ]);
});

api.get('/identity-packs', (req, res) => {
  res.json(db.identityPacks);
});

api.post('/identity-packs', (req, res) => {
  const pack = { id: 'pack_' + Date.now(), name: req.body?.name || 'New Pack', photos: [], created_at: new Date().toISOString() };
  db.identityPacks.push(pack);
  res.status(201).json(pack);
});

api.get('/identity-packs/:id', (req, res) => {
  const pack = db.identityPacks.find((p) => p.id === req.params.id) || { id: req.params.id, name: 'Default Pack', photos: [] };
  res.json(pack);
});

api.get('/gallery', (req, res) => {
  res.json(db.media);
});

api.get('/media-library', (req, res) => {
  res.json(db.media);
});

api.get('/jobs', (req, res) => {
  res.json(db.jobs);
});

api.get('/jobs/:id', (req, res) => {
  const job = db.jobs.find((j) => j.id === req.params.id) || { id: req.params.id, status: 'completed', progress: 100 };
  res.json(job);
});

api.post('/generate', (req, res) => {
  const job = {
    id: 'job_' + Date.now(),
    status: 'completed',
    type: req.body?.type || 'image',
    prompt: req.body?.prompt || '',
    result_url: '/lumina-icon.svg',
    created_at: new Date().toISOString(),
  };
  db.jobs.push(job);
  res.status(202).json(job);
});

// Code Builder & Creator
api.get('/code-builder/model-status', (req, res) => {
  res.json({
    ready: true,
    status: 'ready',
    default_model: 'gemini-3.8-flash',
    models: ['gemini-3.8-flash', 'gemini-2.5-pro'],
  });
});

api.get('/code-builder/engines', (req, res) => {
  res.json([
    { id: 'autonomous', name: 'Autonomous Builder v2', status: 'ready', default: true },
  ]);
});

api.get('/code-builder/tasks', (req, res) => {
  res.json(db.developerTasks);
});

api.post('/code-builder/tasks', (req, res) => {
  const task = { id: 'task_' + Date.now(), title: req.body?.title || 'Build task', status: 'completed' };
  db.developerTasks.push(task);
  res.status(201).json(task);
});

api.get('/code-creator/status', (req, res) => {
  res.json({ status: 'ready', ollama_running: false });
});

api.get('/code-creator/projects', (req, res) => {
  res.json(db.projects);
});

// Developer Center
api.get('/developer/overview', (req, res) => {
  res.json({
    tasks: db.developerTasks,
    metrics: { cpu: 14, memory: 32, uptime: Math.floor(process.uptime()) },
  });
});

api.get('/developer/metrics', (req, res) => {
  res.json({ cpu: 14, memory: 32, disk: 18 });
});

// Document Studio
api.get('/documents', (req, res) => {
  res.json(db.documents);
});

api.get('/documents/ai/providers/status', (req, res) => {
  res.json({
    ready: true,
    providers: [{ name: 'Document AI Engine', available: true, model: 'gemini-3.8-flash' }],
  });
});

api.get('/documents/library/index', (req, res) => {
  res.json({ documents: db.documents, categories: [] });
});

api.get('/documents/company-profile', (req, res) => {
  res.json({ name: 'LUMINA Studio', organization: 'AI Workspace' });
});

// Settings & Preferences
api.get('/settings/preferences', (req, res) => {
  res.json({ theme: 'dark', language: 'en', notifications: true });
});

api.get('/settings/readiness', (req, res) => {
  res.json({ status: 'ok', providers: ['gemini'] });
});

// Driver assistance
api.get('/driver/preferences', (req, res) => {
  res.json({ voiceAlerts: true, speedAlerts: true, cameraAlerts: true, weatherAlerts: true });
});

api.get('/driver/weather', (req, res) => {
  res.json({ condition: 'Clear', temp: 22, wind: 9 });
});

api.get('/driver/traffic', (req, res) => {
  res.json({ routes: [], alerts: [] });
});

// Generic catch-all for any additional /api routes
api.use((req, res) => {
  if (req.method === 'GET') {
    const isPlural = req.path.endsWith('s') || req.path.endsWith('s/');
    return res.json(isPlural ? [] : {});
  }
  return res.json({ success: true, id: 'res_' + Date.now() });
});

app.use('/api', api);

// Drive Assistant static apps
const driveDir = path.join(__dirname, 'drive-assistant');
if (fs.existsSync(driveDir)) {
  app.use('/driver-assistant', express.static(driveDir));
  app.use('/drive-assistant', express.static(driveDir));
}

// Serve Frontend SPA
if (fs.existsSync(frontendBuildDir)) {
  app.use(express.static(frontendBuildDir));

  // SPA fallback
  app.use((req, res) => {
    res.sendFile(indexHtml);
  });
} else {
  app.use((req, res) => {
    res.status(503).send('LUMINA AI Studio is compiling. Please refresh in a moment.');
  });
}

app.listen(PORT, HOST, () => {
  console.log(`[LUMINA AI Studio] Server listening on http://${HOST}:${PORT}`);
});
