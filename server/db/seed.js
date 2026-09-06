const bcrypt = require('bcryptjs');
const { pool } = require('../config/database');
const fs = require('fs');
const path = require('path');
require('dotenv').config({ path: path.join(__dirname, '..', '..', '.env') });

async function seed() {
  try {
    console.log('🌱 Starting database seed...\n');

    // Run schema
    const schema = fs.readFileSync(path.join(__dirname, 'schema.sql'), 'utf8');
    await pool.query(schema);
    console.log('✅ Schema created successfully');

    // Create default admin
    const email = process.env.ADMIN_EMAIL || 'admin@telugucounseling.com';
    const password = process.env.ADMIN_PASSWORD || 'Admin@123456';
    const hashedPassword = await bcrypt.hash(password, 12);

    await pool.query(
      `INSERT INTO admins (email, password_hash, name) 
       VALUES ($1, $2, $3) 
       ON CONFLICT (email) DO NOTHING`,
      [email, hashedPassword, 'Adulla Sridevi Reddy']
    );
    console.log(`✅ Admin user created: ${email}`);

    console.log('\n🎉 Database seeded successfully!');
    process.exit(0);
  } catch (error) {
    console.error('❌ Seed failed:', error);
    process.exit(1);
  }
}

seed();
