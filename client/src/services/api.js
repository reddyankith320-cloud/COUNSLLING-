import axios from 'axios';
import toast from 'react-hot-toast';

const api = axios.create({
  baseURL: '/api',
  withCredentials: true, // Important for sending cookies (JWT)
  headers: {
    'Content-Type': 'application/json',
  },
});

// Response interceptor for global error handling
api.interceptors.response.use(
  (response) => response,
  (error) => {
    // Handle authentication errors globally
    if (error.response?.status === 401) {
      // Avoid showing toast if we're just checking auth status on load
      const isAuthCheck = error.config.url === '/auth/me';
      if (!isAuthCheck) {
        toast.error('Session expired. Please log in again.');
        // Redirect to login could be handled here or in the context
        if (window.location.pathname.startsWith('/admin') && window.location.pathname !== '/admin/login') {
          window.location.href = '/admin/login';
        }
      }
    } else if (error.response?.status >= 500) {
      toast.error('Server error. Please try again later.');
    }
    
    return Promise.reject(error);
  }
);

export default api;
