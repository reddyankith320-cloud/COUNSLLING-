const express = require('express');
const router = express.Router();
const bcrypt = require('bcryptjs');
const { query } = require('../config/database');
const { authenticate, generateToken } = require('../middleware/auth');
const { loginValidation } = require('../middleware/validator');
const { authLimiter } = require('../middleware/rateLimiter');

const isProd = process.env.NODE_ENV === 'production';
const COOKIE_OPTIONS = {
  httpOnly: true,
  secure: isProd,
  // Cross-site cookies need SameSite=None (+Secure) when the SPA lives on another domain
  sameSite: isProd ? 'none' : 'lax',
  maxAge: 24 * 60 * 60 * 1000, // 24 hours
};

// POST /api/auth/login
router.post('/login', authLimiter, loginValidation, async (req, res, next) => {
  try {
    const { email, password } = req.body;

    const result = await query('SELECT * FROM admins WHERE email = $1', [email]);

    if (result.rows.length === 0) {
      return res.status(401).json({ error: 'Invalid email or password' });
    }

    const admin = result.rows[0];
    const isValidPassword = await bcrypt.compare(password, admin.password_hash);

    if (!isValidPassword) {
      return res.status(401).json({ error: 'Invalid email or password' });
    }

    const token = generateToken({ id: admin.id, email: admin.email, name: admin.name });

    // Set httpOnly cookie (works when the API and frontend share a site).
    // The token is also returned in the body so the SPA can send it as a
    // Bearer header when the frontend is hosted on a different domain.
    res.cookie('token', token, COOKIE_OPTIONS);

    res.json({
      message: 'Login successful',
      token,
      admin: { id: admin.id, email: admin.email, name: admin.name },
    });
  } catch (error) {
    next(error);
  }
});

// POST /api/auth/logout
router.post('/logout', (req, res) => {
  // Must match the options the cookie was set with, or some browsers keep it
  res.clearCookie('token', { ...COOKIE_OPTIONS, maxAge: undefined });
  res.json({ message: 'Logout successful' });
});

// GET /api/auth/me
router.get('/me', authenticate, async (req, res, next) => {
  try {
    const result = await query(
      'SELECT id, email, name, created_at FROM admins WHERE id = $1',
      [req.admin.id]
    );

    if (result.rows.length === 0) {
      return res.status(404).json({ error: 'Admin not found' });
    }

    res.json({ admin: result.rows[0] });
  } catch (error) {
    next(error);
  }
});

module.exports = router;
