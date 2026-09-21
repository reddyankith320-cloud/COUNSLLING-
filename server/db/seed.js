const bcrypt = require('bcryptjs');
const { pool } = require('../config/database');
const fs = require('fs');
const path = require('path');
// Load server/.env first (where DATABASE_URL lives), then fall back to the repo-root .env
require('dotenv').config({ path: path.join(__dirname, '..', '.env') });
require('dotenv').config({ path: path.join(__dirname, '..', '..', '.env') });

async function seed() {
  try {
    console.log('🌱 Starting database seed...\n');

    // Run schema
    const schema = fs.readFileSync(path.join(__dirname, 'schema.sql'), 'utf8');
    await pool.query(schema);
    console.log('✅ Schema created successfully');

    // Create default admin
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
    if (inserted.rowCount > 0) {
      console.log(`✅ Admin user created: ${email}`);
    } else {
      console.log(`ℹ️  Admin user already exists: ${email} (password unchanged)`);
    }

    const admins = await pool.query('SELECT email FROM admins ORDER BY id');
    console.log(`👤 Admin accounts in this database: ${admins.rows.map(r => r.email).join(', ')}`);

    console.log('\n🎉 Database seeded successfully!');
    process.exit(0);
  } catch (error) {
    console.error('❌ Seed failed:', error);
    process.exit(1);
  }
}

seed();
