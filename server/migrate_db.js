const { pool } = require('./config/database');

async function migrate() {
  try {
    // 1. Drop existing constraints
    await pool.query('ALTER TABLE appointments DROP CONSTRAINT IF EXISTS appointments_appointment_date_start_time_key');
    
    // 2. Drop existing status check constraint
    // We need to find the name of the check constraint. Usually it is something like `appointments_status_check`.
    await pool.query('ALTER TABLE appointments DROP CONSTRAINT IF EXISTS appointments_status_check');
    
    // Update existing status values to match new ones if necessary
    await pool.query("UPDATE appointments SET status = 'Booked' WHERE status = 'scheduled'");
    
    // 3. Add new check constraint
    await pool.query(`ALTER TABLE appointments ADD CONSTRAINT appointments_status_check 
                      CHECK (status IN ('pending_payment', 'Booked', 'Cancelled', 'Completed', 'no_show'))`);
    
    // 4. Alter column default
    await pool.query(`ALTER TABLE appointments ALTER COLUMN status SET DEFAULT 'pending_payment'`);
    
    // 5. Create partial unique index
    await pool.query(`CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_booked_slot 
                      ON appointments(appointment_date, start_time) 
                      WHERE status IN ('Booked', 'Completed')`);
                      
    console.log('Migration successful');
    process.exit(0);
  } catch (err) {
    console.error('Migration failed:', err);
    process.exit(1);
  }
}

migrate();
