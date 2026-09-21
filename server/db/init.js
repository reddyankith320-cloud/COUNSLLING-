// Runs the (idempotent) schema and makes sure the default admin exists.
// Called on server start so a freshly provisioned database — e.g. on Render,
// where the free tier has no shell to run `npm run seed` — just works.
const fs = require('fs');
const path = require('path');
const bcrypt = require('bcryptjs');
const { pool } = require('../config/database');

async function ensureSchema() {
  const schema = fs.readFileSync(path.join(__dirname, 'schema.sql'), 'utf8');
  await pool.query(schema);
  // Columns added after the original schema shipped
  await pool.query('ALTER TABLE appointments ADD COLUMN IF NOT EXISTS consultation_type VARCHAR(50)');
}

async function ensureAdmin() {
  const email = process.env.ADMIN_EMAIL || 'adullasridevireddy810@gmail.com';
  const password = process.env.ADMIN_PASSWORD || 'Admin@123456';
  const hashedPassword = await bcrypt.hash(password, 12);

  const inserted = await pool.query(
    `INSERT INTO admins (email, password_hash, name)
     VALUES ($1, $2, $3)
     ON CONFLICT (email) DO NOTHING
     RETURNING id`,
    [email, hashedPassword, 'Adulla Sridevi Reddy']
  );
  return { email, created: inserted.rowCount > 0 };
}

async function initDatabase() {
  await ensureSchema();
  const admin = await ensureAdmin();
  return admin;
}

module.exports = { initDatabase, ensureSchema, ensureAdmin };
