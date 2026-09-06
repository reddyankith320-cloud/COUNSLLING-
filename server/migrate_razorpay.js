require("dotenv").config();
const { Pool } = require("pg");

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  ssl: false,
});

async function migrate() {
  try {
    console.log("Migrating payments table from Airtel -> Razorpay...");

    // 1. Add new Razorpay columns if they do not already exist
    await pool.query(`
      ALTER TABLE payments
        ADD COLUMN IF NOT EXISTS razorpay_order_id   VARCHAR(255),
        ADD COLUMN IF NOT EXISTS razorpay_payment_id VARCHAR(255),
        ADD COLUMN IF NOT EXISTS razorpay_signature  VARCHAR(512)
    `);
    console.log("Added Razorpay columns");

    // 2. Add consultation_type to appointments if missing
    await pool.query(`
      ALTER TABLE appointments
        ADD COLUMN IF NOT EXISTS consultation_type VARCHAR(50) DEFAULT 'Initial'
    `);
    console.log("Added consultation_type column to appointments");

    // 3. Drop old Airtel columns
    await pool.query(`
      ALTER TABLE payments
        DROP COLUMN IF EXISTS airtel_transaction_id,
        DROP COLUMN IF EXISTS airtel_payment_id,
        DROP COLUMN IF EXISTS airtel_signature,
        DROP COLUMN IF EXISTS airtel_link_id,
        DROP COLUMN IF EXISTS payment_link
    `);
    console.log("Removed Airtel columns");

    // 4. Create index on razorpay_order_id for fast lookups
    await pool.query(`
      CREATE INDEX IF NOT EXISTS idx_payments_razorpay_order
        ON payments(razorpay_order_id)
    `);
    console.log("Created index on razorpay_order_id");

    console.log("\nMigration complete!");
  } catch (err) {
    console.error("Migration failed:", err.message);
    process.exit(1);
  } finally {
    await pool.end();
  }
}

migrate();
