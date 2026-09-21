import axios from 'axios';
import toast from 'react-hot-toast';

// In dev the Vite proxy forwards /api to the backend, so the base URL can be
// empty. In production the frontend and API usually live on different hosts,
// so VITE_API_BASE_URL must point at the API (e.g. https://api.example.com).
export const API_ORIGIN = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '');

const TOKEN_KEY = 'fmp_admin_token';

export const getStoredToken = () => {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
};

export const setStoredToken = (token) => {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Storage unavailable (private mode etc.) — cookie auth still works same-site
  }
};

const api = axios.create({
  baseURL: `${API_ORIGIN}/api`,
  withCredentials: true, // send the httpOnly cookie when same-site
  headers: {
    'Content-Type': 'application/json',
  },
});

// Attach the admin token as a Bearer header so auth also works when the API is
// hosted on a different domain (where the cookie is not sent).
api.interceptors.request.use((config) => {
  const token = getStoredToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Response interceptor for global error handling
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status;

    if (status === 401) {
      // A 401 from the auth endpoints themselves is "not logged in" / "wrong
      // password", not an expired session — let the caller handle it.
      const isAuthEndpoint = /^\/auth\/(me|login)$/.test(error.config?.url || '');
      if (!isAuthEndpoint) {
        setStoredToken(null);
        toast.error('Session expired. Please log in again.');
        if (window.location.pathname.startsWith('/admin') && window.location.pathname !== '/admin/login') {
          window.location.href = '/admin/login';
        }
      }
    } else if (status >= 500) {
      toast.error('Server error. Please try again later.');
    } else if (!error.response && error.code !== 'ERR_CANCELED') {
      toast.error('Cannot reach the server. Please check your connection.');
    }

    return Promise.reject(error);
  }
);

export default api;
