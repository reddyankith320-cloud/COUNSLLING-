const { Pool } = require('pg');
require('dotenv').config();

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  ssl: process.env.NODE_ENV === 'production' ? { rejectUnauthorized: false } : false,
});

pool.on('connect', () => {
  console.log('✅ Connected to PostgreSQL database');
});

// An idle client dropping (network blip, DB restart) should not take the whole
// API down — the pool will open a fresh connection on the next query.
pool.on('error', (err) => {
  console.error('❌ PostgreSQL idle client error:', err.message);
});

// Helper function to run queries
const query = (text, params) => pool.query(text, params);

// Helper for transactions
const getClient = () => pool.connect();

module.exports = { pool, query, getClient };
