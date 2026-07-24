import axios from 'axios';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
export const API_BASE = `${BACKEND_URL}/api`;
const DEFAULT_TIMEOUT = 25000;
const RETRYABLE_STATUSES = new Set([429, 500, 502, 503, 504]);
const SAFE_METHODS = new Set(['get', 'head', 'options']);

export const api = axios.create({
  baseURL: API_BASE,
  timeout: DEFAULT_TIMEOUT,
  headers: {
    Accept: 'application/json',
  },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('lumina_token');
  if (token) {
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

function safeMessageFromStatus(status, backendMessage) {
  switch (status) {
    case 400:
      return backendMessage || 'Bad request. Please check your input.';
    case 401:
      return 'Authentication required. Please sign in again.';
    case 403:
      return 'Access denied. You do not have permission.';
    case 404:
      return 'Resource not found.';
    case 409:
      return backendMessage || 'Conflict detected. Please try again.';
    case 422:
      return backendMessage || 'Validation failed. Please review your data.';
    case 429:
      return 'Too many requests. Please wait a moment and retry.';
    case 500:
      return 'Server error. Please try again later.';
    case 502:
      return 'Service unavailable. Please try again later.';
    case 503:
      return 'Service temporarily unavailable. Please retry shortly.';
    case 504:
      return 'The request timed out. Please try again.';
    default:
      return backendMessage || 'Request failed. Please try again.';
  }
}

function normalizeError(error) {
  const isCanceled = axios.isCancel(error) || error?.name === 'CanceledError';
  if (isCanceled) {
    return {
      isAborted: true,
      status: null,
      message: 'Request canceled.',
      code: 'aborted',
      retryable: false,
      responseData: null,
      original: error,
    };
  }

  const status = error?.response?.status;
  const responseData = error?.response?.data;
  const backendMessage =
    typeof responseData?.detail === 'string'
      ? responseData.detail
      : typeof responseData?.message === 'string'
      ? responseData.message
      : null;

  if (status === 401) {
    localStorage.removeItem('lumina_token');
    if (!window.location.pathname.startsWith('/login')) {
      window.location.href = '/login';
    }
  }

  return {
    isAxiosError: true,
    status,
    message: safeMessageFromStatus(status, backendMessage),
    code: status ? `http_${status}` : error?.code || 'network_error',
    retryable: !status || RETRYABLE_STATUSES.has(status),
    responseData,
    original: error,
  };
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function request(method, url, options = {}) {
  const {
    params,
    data,
    headers,
    signal,
    onUploadProgress,
    responseType,
    timeout = DEFAULT_TIMEOUT,
    retry = true,
  } = options;

  const config = {
    method,
    url,
    params,
    data,
    headers,
    signal,
    onUploadProgress,
    responseType,
    timeout,
  };

  let attempt = 0;
  const maxAttempts = retry && SAFE_METHODS.has(method.toLowerCase()) ? 2 : 0;

  while (true) {
    try {
      const response = await api.request(config);
      return response.data;
    } catch (rawError) {
      const error = normalizeError(rawError);
      if (attempt < maxAttempts && error.retryable) {
        attempt += 1;
        await delay(500 * attempt);
        continue;
      }
      throw error;
    }
  }
}

export async function apiRequest(method, url, options = {}) {
  return request(method, url, options);
}

export async function apiGet(url, options = {}) {
  return request('get', url, options);
}

export async function apiPost(url, data, options = {}) {
  return request('post', url, { ...options, data });
}

export async function apiPut(url, data, options = {}) {
  return request('put', url, { ...options, data });
}

export async function apiPatch(url, data, options = {}) {
  return request('patch', url, { ...options, data });
}

export async function apiDelete(url, options = {}) {
  return request('delete', url, options);
}

export async function uploadFormData(url, formData, options = {}) {
  return request('post', url, {
    ...options,
    data: formData,
    headers: {
      'Content-Type': 'multipart/form-data',
      ...(options.headers || {}),
    },
    retry: false,
  });
}

export async function fetchMediaBlobUrl(mediaId, options = {}) {
  const data = await request('get', `/media/${mediaId}`, {
    ...options,
    responseType: 'blob',
  });
  return URL.createObjectURL(data);
}

export function makeAbortController() {
  return new AbortController();
}
