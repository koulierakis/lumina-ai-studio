export function runtimeStudioJobPayload(studio, taskType, payload = {}, options = {}) {
  const normalizedStudio = String(studio || 'runtime').trim() || 'runtime';
  const normalizedTaskType = String(taskType || 'llm').trim() || 'llm';
  const safePayload = payload && typeof payload === 'object' && !Array.isArray(payload) ? payload : {};

  return {
    studio: normalizedStudio,
    task_type: normalizedTaskType,
    payload: safePayload,
    ...(options.provider ? { provider: String(options.provider) } : {}),
    ...(options.model ? { model: String(options.model) } : {}),
  };
}
