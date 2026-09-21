// Adds the `consultation_type` column used by routes/booking.js to databases
// that were seeded before it was part of schema.sql. Safe to run repeatedly.
const { pool } = require('./config/database');

async function migrate() {
  try {
    await pool.query(`ALTER TABLE appointments ADD COLUMN IF NOT EXISTS consultation_type VARCHAR(50)`);
    console.log('✅ appointments.consultation_type is present');
    process.exit(0);
  } catch (err) {
    console.error('❌ Migration failed:', err);
    process.exit(1);
  }
}

migrate();
