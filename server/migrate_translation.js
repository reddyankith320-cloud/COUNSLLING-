const { pool } = require('./config/database');

async function migrate() {
  try {
    console.log('🔄 Creating transcripts and settings tables...');

    await pool.query(`
      CREATE TABLE IF NOT EXISTS transcripts (
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

    await pool.query(`
      CREATE TABLE IF NOT EXISTS settings (
          id SERIAL PRIMARY KEY,
          key VARCHAR(100) UNIQUE NOT NULL,
          value TEXT NOT NULL
      );
    `);
    
    // Insert default settings
    await pool.query(`
      INSERT INTO settings (key, value)
      VALUES ('store_transcripts', 'true')
      ON CONFLICT (key) DO NOTHING;
    `);

    console.log('✅ Migration successful — Translation tables created');
    process.exit(0);
  } catch (err) {
    console.error('❌ Migration failed:', err);
    process.exit(1);
  }
}

migrate();
