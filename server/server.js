const express = require('express');
const http = require('http');
const crypto = require('crypto');
const { Server } = require('socket.io');
const helmet = require('helmet');
const cors = require('cors');
const morgan = require('morgan');
const cookieParser = require('cookie-parser');
const compression = require('compression');
require('dotenv').config();

// Enforce Asia/Kolkata Timezone
process.env.TZ = 'Asia/Kolkata';

const { apiLimiter } = require('./middleware/rateLimiter');
const { authenticate } = require('./middleware/auth');
const errorHandler = require('./middleware/errorHandler');

// Route imports
const authRoutes = require('./routes/auth');
const bookingRoutes = require('./routes/booking');
const paymentRoutes = require('./routes/payment');
const adminRoutes = require('./routes/admin');
const slotRoutes = require('./routes/slots');
const exportRoutes = require('./routes/export');

const { setupTranslationSockets } = require('./sockets/translation');

const app = express();
const server = http.createServer(app);

// FRONTEND_URL may be a comma-separated list (e.g. local + production)
const allowedOrigins = (process.env.FRONTEND_URL || 'http://localhost:5173')
  .split(',')
  .map(o => o.trim())
  .filter(Boolean);

const corsOptions = {
  origin: (origin, callback) => {
    // Allow same-origin / server-to-server requests (no Origin header) and whitelisted origins
    if (!origin || allowedOrigins.includes(origin)) return callback(null, true);
    return callback(new Error(`Origin ${origin} not allowed by CORS`));
  },
  credentials: true,
  methods: ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'],
  allowedHeaders: ['Content-Type', 'Authorization'],
};

// Setup Socket.io
const io = new Server(server, {
  cors: {
    origin: allowedOrigins,
    methods: ['GET', 'POST'],
    credentials: true
  }
});
setupTranslationSockets(io);

// Expose io to all routes
app.use((req, res, next) => {
  req.io = io;
  next();
});

const PORT = process.env.PORT || 5000;

// ===== Security Middleware =====
app.use(helmet({
  contentSecurityPolicy: {
    directives: {
      defaultSrc: ["'self'"],
      scriptSrc: ["'self'", "'unsafe-inline'"],
      frameSrc: ["'self'", "https://api.razorpay.com", "https://checkout.razorpay.com"],
      connectSrc: ["'self'", "https://api.razorpay.com", "https://checkout.razorpay.com"],
      styleSrc: ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"],
      fontSrc: ["'self'", "https://fonts.gstatic.com"],
      imgSrc: ["'self'", "data:", "https:"],
    },
  },
  crossOriginEmbedderPolicy: false,
}));

// CORS
app.use(cors(corsOptions));

// Gzip compression for all responses
app.use(compression());

// Body parsing. `verify` keeps the raw bytes so the Razorpay webhook can check its HMAC.
app.use(express.json({
  limit: '10mb',
  verify: (req, res, buf) => { req.rawBody = buf; },
}));
app.use(express.urlencoded({ extended: true, limit: '10mb' }));
app.use(cookieParser());

// Logging
if (process.env.NODE_ENV !== 'production') {
  app.use(morgan('dev'));
} else {
  app.use(morgan('combined'));
}

// Rate limiting
app.use('/api/', apiLimiter);

// ===== Google OAuth (one-time counselor consent) =====
// Only a logged-in admin may start the flow, and the callback must carry the
// `state` we issued — otherwise anyone could connect their own Google account
// and hijack the counselor's calendar.
const { getAuthUrl, storeTokenFromCode } = require('./config/google');
const pendingOAuthStates = new Map(); // state -> expiry timestamp
const OAUTH_STATE_TTL_MS = 10 * 60 * 1000;

app.get('/api/auth/google', authenticate, (req, res) => {
  const state = crypto.randomBytes(24).toString('hex');
  pendingOAuthStates.set(state, Date.now() + OAUTH_STATE_TTL_MS);
  res.redirect(getAuthUrl(state));
});

app.get('/api/auth/google/callback', async (req, res) => {
  try {
    const { code, state } = req.query;

    // Purge expired states
    for (const [s, exp] of pendingOAuthStates) if (exp < Date.now()) pendingOAuthStates.delete(s);

    if (!state || !pendingOAuthStates.has(state)) {
      return res.status(403).send('Invalid or expired OAuth state. Please start again from the admin dashboard.');
    }
    pendingOAuthStates.delete(state);

    if (!code) {
      return res.status(400).send('No code provided');
    }
    await storeTokenFromCode(code);
    res.send('✅ Google Calendar connected successfully. You can close this window.');
  } catch (error) {
    console.error('Google OAuth error:', error);
    res.status(500).send('Google OAuth failed');
  }
});

// ===== API Routes =====
app.use('/api/auth', authRoutes);
app.use('/api/bookings', bookingRoutes);
app.use('/api/payments', paymentRoutes);
app.use('/api/admin', adminRoutes);
app.use('/api/slots', slotRoutes);
app.use('/api/export', exportRoutes);

// Health check
app.get('/api/health', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

// 404 handler
app.use('/api/*', (req, res) => {
  res.status(404).json({ error: 'API endpoint not found' });
});

// Global error handler
app.use(errorHandler);

// ===== Start Server =====
server.listen(PORT, () => {
  console.log(`\n🚀 Find My Peace – Counseling API Server running on port ${PORT}`);
  console.log(`📍 Environment: ${process.env.NODE_ENV || 'development'}`);
  console.log(`🌐 Allowed origins: ${allowedOrigins.join(', ')}\n`);
});

module.exports = server;
