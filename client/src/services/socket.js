import { io } from 'socket.io-client';
import { API_ORIGIN } from './api';

// Socket.io server origin. Falls back to the API origin, then to the current
// page origin (works in dev thanks to the Vite /socket.io proxy).
export const SOCKET_URL =
  import.meta.env.VITE_SOCKET_URL || API_ORIGIN || window.location.origin;

let socket = null;

/**
 * Shared connection to the default namespace (availability updates).
 * Created lazily on first use, so pages that never need it don't open a socket.
 */
export const getSocket = () => {
  if (!socket) {
    socket = io(SOCKET_URL, {
      withCredentials: true,
      transports: ['websocket', 'polling'],
    });
  }
  return socket;
};

/**
 * Subscribe to an event on the shared socket; returns an unsubscribe function
 * so it slots straight into a useEffect cleanup.
 */
export const onSocketEvent = (event, handler) => {
  const s = getSocket();
  s.on(event, handler);
  return () => s.off(event, handler);
};
