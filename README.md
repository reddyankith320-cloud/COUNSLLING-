# Find My Peace Platform

A full-stack web application for a professional counseling practice, featuring integrated video calling (Google Meet via Google Calendar), secure payments (Razorpay), live speech translation, and automated Email/SMS/WhatsApp notifications.

## Features

### Client-Facing Web Application
* **Modern UI**: Built with React and Tailwind CSS v4 featuring glassmorphism and smooth animations.
* **Responsive Design**: Mobile-first approach ensuring a seamless experience across all devices.
* **Smart Booking System**: 
  * Select from dynamic available time slots based on the counselor's schedule.
  * Captures essential personal information and pre-session questionnaire.
* **Integrated Payments**: Secure checkout flow via Razorpay with UPI (GPay, PhonePe, Paytm) support.
* **Automated Confirmation**: Instantly generates a Google Meet link and sends details via Email, SMS, and WhatsApp upon successful payment.
* **Slot Holds**: An unpaid booking reserves its slot for 15 minutes, then releases it automatically.

### Counselor / Admin Dashboard
* **Secure Authentication**: JWT-based secure login with bcrypt password hashing.
* **Dashboard Analytics**: Real-time overview of appointments, earnings, and client base.
* **Comprehensive Schedule Management**:
  * View Today's, Upcoming, Completed, and Cancelled appointments.
  * Direct "Join Google Meet" integration and a live translation room.
* **Follow-up Workflow System**:
  * Easily mark sessions as complete or request a follow-up.
  * Sends the client a booking link; the ₹499 follow-up fee is applied automatically when they book again with the same mobile/email.
* **Client Management**: Searchable client directory with full session history and private counselor notes.
* **Availability**: Block whole days or single time slots, and schedule holidays. Clients see changes live via Socket.io.
* **Export**: Download all appointments as an Excel workbook.

## Technology Stack

* **Frontend**: React.js, Vite, Tailwind CSS v4, React Router, Axios, Framer Motion, Chart.js
* **Backend**: Node.js, Express.js
* **Database**: PostgreSQL
* **Third-Party APIs**: 
  * Razorpay (Payments)
  * Google Calendar API (Google Meet links – one-time OAuth consent from the admin)
  * Google Cloud Speech / Translate / Text-to-Speech (live translation room)
  * Twilio (SMS & WhatsApp Business API)
  * SendGrid (Email Notifications)

## Local Development Setup

### 1. Prerequisites
* Node.js (v18+)
* PostgreSQL installed and running

### 2. Database Configuration
Create a PostgreSQL database named `telugu_counseling` and run the seed script (safe to re-run on an existing database):
```bash
cd server
npm run seed
```
If your database was created before `consultation_type` existed, also run `node migrate_consultation_type.js` once.

### 3. Environment Variables
Copy `.env.example` to `server/.env` and fill in your keys:
* Database credentials (`DATABASE_URL`)
* JWT Secret
* Razorpay Key ID, Secret and Webhook Secret
* Google OAuth Client ID / Secret (Calendar + Meet)
* Twilio SID and Auth Token (optional – mocked when absent)
* SendGrid API Key (optional – mocked when absent)
* `FRONTEND_URL` – comma-separated list of allowed origins

Copy `client/.env.example` to `client/.env`. Leave `VITE_API_BASE_URL` empty in development (Vite proxies `/api`); set it to your API host in production.

### Connecting Google Calendar (one-time)
Log in to the admin dashboard, then open `http://localhost:5000/api/auth/google` in the same browser and grant access. The refresh token is stored in `server/.google-token.json`. Until this is done, Meet links are mocked in development.

### 4. Running the Servers
Start the backend server (runs on port 5000):
```bash
cd server
npm run dev
```

Start the frontend Vite server (runs on port 5173):
```bash
cd client
npm run dev
```

## Default Admin Credentials
The seed script creates a default admin account from `ADMIN_EMAIL` / `ADMIN_PASSWORD` in `server/.env` (defaults below). Re-run `npm run seed` if the account is missing.
* **Email**: adullasridevireddy810@gmail.com
* **Password**: Admin@123456

*(Please change this password in production!)*

## Pricing
Fees are defined in `server/routes/booking.js` (`INITIAL_FEE`, `FOLLOWUP_FEE`, `MAX_FOLLOWUPS`) and mirrored for display in `client/src/config/site.js`. Change both when updating prices.

## Security Implementations
* **Helmet.js**: Sets secure HTTP headers (CSP, HSTS).
* **CORS**: Configured strictly for the frontend domain.
* **Rate Limiting**: Protects against brute-force (auth routes) and DDoS (API routes).
* **CSRF/XSS Protection**: Handled via secure cookie policies and React's built-in escaping.
* **Data Validation**: Strict input validation using `express-validator`.
* **Parameterized Queries**: Prevents SQL injection via `node-postgres`.

## License
Proprietary software. All rights reserved.
