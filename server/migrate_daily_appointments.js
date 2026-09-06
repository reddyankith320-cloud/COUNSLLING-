const { pool } = require('./config/database');

async function migrate() {
  try {
    console.log('🔄 Migrating database to Single Daily Appointment Model...');

    // 1. Drop existing tables that depend on time slots
    await pool.query('DROP TABLE IF EXISTS working_hours CASCADE');
    await pool.query('DROP TABLE IF EXISTS blocked_slots CASCADE');
    
    // We will drop appointments and recreate it because existing data 
    // violates the new strict "one per day" constraint and the time columns are obsolete.
    await pool.query('DROP TABLE IF EXISTS payments CASCADE'); // depends on appointments
    await pool.query('DROP TABLE IF EXISTS transcripts CASCADE'); // depends on appointments
    await pool.query('DROP TABLE IF EXISTS appointments CASCADE');

    console.log('✅ Obsolete tables dropped');

    // 2. Recreate Appointments Table
    await pool.query(`
      CREATE TABLE appointments (
          id SERIAL PRIMARY KEY,
          client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
          appointment_date DATE NOT NULL,
          status VARCHAR(50) DEFAULT 'pending_payment' CHECK (status IN ('pending_payment', 'Booked', 'Cancelled', 'Completed', 'no_show')),
          google_event_id VARCHAR(255),
          meet_join_url TEXT,
          google_calendar_link TEXT,
          problem_description TEXT,
          requires_followup BOOLEAN,
          is_followup BOOLEAN DEFAULT FALSE,
          parent_appointment_id INTEGER REFERENCES appointments(id),
          created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
          updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
      );
    `);

    await pool.query(`CREATE INDEX idx_appointments_date ON appointments(appointment_date);`);
    await pool.query(`CREATE UNIQUE INDEX idx_unique_booked_date ON appointments(appointment_date) WHERE status IN ('Booked', 'Completed');`);
    await pool.query(`CREATE INDEX idx_appointments_status ON appointments(status);`);
    await pool.query(`CREATE INDEX idx_appointments_client ON appointments(client_id);`);

    console.log('✅ Appointments table recreated');

    // 3. Recreate Payments Table
    await pool.query(`
      CREATE TABLE payments (
          id SERIAL PRIMARY KEY,
          appointment_id INTEGER REFERENCES appointments(id) ON DELETE CASCADE,
          client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
          razorpay_order_id VARCHAR(255),
          razorpay_payment_id VARCHAR(255),
          razorpay_signature VARCHAR(512),
          amount DECIMAL(10,2) NOT NULL DEFAULT 999.00,
          currency VARCHAR(10) DEFAULT 'INR',
          status VARCHAR(50) DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'failed', 'refunded')),
          payment_method VARCHAR(50) DEFAULT 'UPI',
          payment_link TEXT,
          is_followup BOOLEAN DEFAULT FALSE,
          created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
          updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
      );
    `);

    console.log('✅ Payments table recreated');

    // 4. Recreate Transcripts Table
    await pool.query(`
      CREATE TABLE transcripts (
          id SERIAL PRIMARY KEY,
          appointment_id INTEGER REFERENCES appointments(id) ON DELETE CASCADE,
          speaker VARCHAR(50) NOT NULL,
          original_text TEXT NOT NULL,
          detected_language VARCHAR(50),
          translated_text TEXT,
          target_language VARCHAR(50),
          timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
      );
    `);

    console.log('✅ Transcripts table recreated');

    // 5. Create new Blocked Dates table
    await pool.query(`
      CREATE TABLE blocked_dates (
          id SERIAL PRIMARY KEY,
          date DATE UNIQUE NOT NULL,
          reason VARCHAR(255),
          created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
      );
    `);
    
    await pool.query(`CREATE INDEX idx_blocked_dates ON blocked_dates(date);`);

    console.log('✅ Blocked Dates table created');

    console.log('🎉 Migration successful!');
    process.exit(0);
  } catch (err) {
    console.error('❌ Migration failed:', err);
    process.exit(1);
  }
}

migrate();
