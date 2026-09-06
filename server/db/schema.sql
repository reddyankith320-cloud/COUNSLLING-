-- Telugu Counseling Services Database Schema
-- PostgreSQL

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Admin users (counselors)
CREATE TABLE admins (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Clients
CREATE TABLE clients (
    id SERIAL PRIMARY KEY,
    full_name VARCHAR(255) NOT NULL,
    age INTEGER NOT NULL CHECK (age > 0 AND age < 150),
    gender VARCHAR(50),
    mobile VARCHAR(15) NOT NULL,
    email VARCHAR(255) NOT NULL,
    is_archived BOOLEAN DEFAULT FALSE,
    follow_up_count INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Holidays
CREATE TABLE holidays (
    id SERIAL PRIMARY KEY,
    date DATE UNIQUE NOT NULL,
    reason VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Blocked Dates (full day block)
CREATE TABLE blocked_dates (
    id SERIAL PRIMARY KEY,
    date DATE UNIQUE NOT NULL,
    reason VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Blocked Slots (individual time slot block)
CREATE TABLE blocked_slots (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    reason VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(date, start_time)
);

-- Appointments
CREATE TABLE appointments (
    id SERIAL PRIMARY KEY,
    client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
    appointment_date DATE NOT NULL,
    start_time TIME NOT NULL DEFAULT '18:00',
    end_time TIME NOT NULL DEFAULT '19:00',
    status VARCHAR(50) DEFAULT 'pending_payment' CHECK (status IN ('pending_payment', 'Booked', 'Cancelled', 'Completed', 'no_show', 'Blocked')),
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

-- Payments
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

-- Counselor notes (private, visible only to the counselor)
CREATE TABLE notes (
    id SERIAL PRIMARY KEY,
    appointment_id INTEGER REFERENCES appointments(id) ON DELETE CASCADE,
    client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Transcripts (Real-time translation transcripts)
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

-- Settings (Admin controls)
CREATE TABLE settings (
    id SERIAL PRIMARY KEY,
    key VARCHAR(100) UNIQUE NOT NULL,
    value TEXT NOT NULL
);

-- Insert default settings
INSERT INTO settings (key, value) VALUES ('store_transcripts', 'true') ON CONFLICT (key) DO NOTHING;

-- Indexes for performance
CREATE INDEX idx_appointments_date ON appointments(appointment_date);
CREATE UNIQUE INDEX idx_unique_booked_slot ON appointments(appointment_date, start_time) WHERE status IN ('Booked', 'Completed');
CREATE INDEX idx_appointments_status ON appointments(status);
CREATE INDEX idx_appointments_client ON appointments(client_id);
CREATE INDEX idx_payments_status ON payments(status);
CREATE INDEX idx_payments_client ON payments(client_id);
CREATE INDEX idx_payments_razorpay_order ON payments(razorpay_order_id);
CREATE INDEX idx_clients_email ON clients(email);
CREATE INDEX idx_clients_mobile ON clients(mobile);
