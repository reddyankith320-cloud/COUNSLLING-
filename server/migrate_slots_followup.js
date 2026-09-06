const { pool } = require('./config/database');
const fs = require('fs');
const path = require('path');
require('dotenv').config({ path: path.join(__dirname, '.env') });

async function migrate() {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    console.log('Starting migration: slots + follow-up limit...\n');

    await client.query(`ALTER TABLE clients ADD COLUMN IF NOT EXISTS follow_up_count INTEGER DEFAULT 0`);
    console.log('✅ Added follow_up_count to clients');

    await client.query(`ALTER TABLE appointments ADD COLUMN IF NOT EXISTS start_time TIME DEFAULT '18:00'`);
    await client.query(`ALTER TABLE appointments ADD COLUMN IF NOT EXISTS end_time TIME DEFAULT '19:00'`);
    console.log('✅ Added start_time and end_time to appointments');

    await client.query(`DROP INDEX IF EXISTS idx_unique_booked_date`);
    console.log('✅ Dropped old unique index');

    await client.query(`CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_booked_slot ON appointments(appointment_date, start_time) WHERE status IN ('Booked', 'Completed')`);
    console.log('✅ Created new unique index on (date, start_time)');

    await client.query(`ALTER TABLE appointments DROP CONSTRAINT IF EXISTS appointments_status_check`);
    await client.query(`ALTER TABLE appointments ADD CONSTRAINT appointments_status_check CHECK (status IN ('pending_payment', 'Booked', 'Cancelled', 'Completed', 'no_show', 'Blocked'))`);
    console.log('✅ Updated status check constraint');

    await client.query(`CREATE TABLE IF NOT EXISTS blocked_slots (
      id SERIAL PRIMARY KEY,
      date DATE NOT NULL,
      start_time TIME NOT NULL,
      end_time TIME NOT NULL,
      reason VARCHAR(255),
      created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
      UNIQUE(date, start_time)
    )`);
    console.log('✅ Created blocked_slots table');

    await client.query('COMMIT');
    console.log('\nMigration completed successfully!');
    process.exit(0);
  } catch (error) {
    await client.query('ROLLBACK');
    console.error('Migration failed:', error);
    process.exit(1);
  } finally {
    client.release();
  }
}

migrate();
