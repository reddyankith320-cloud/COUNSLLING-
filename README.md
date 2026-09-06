# Find My Peace Platform

A full-stack, production-ready web application built for a professional counseling practice, featuring integrated video calling (Zoom), secure payments (Razorpay), and automated SMS/WhatsApp notifications.

## Features

### Client-Facing Web Application
* **Modern UI**: Built with React and Tailwind CSS v4 featuring glassmorphism and smooth animations.
* **Responsive Design**: Mobile-first approach ensuring a seamless experience across all devices.
* **Smart Booking System**: 
  * Select from dynamic available time slots based on the counselor's schedule.
  * Captures essential personal information and pre-session questionnaire.
* **Integrated Payments**: Secure checkout flow via Razorpay with UPI (GPay, PhonePe, Paytm) support.
* **Automated Confirmation**: Instantly generates Zoom meetings and sends details via Email, SMS, and WhatsApp upon successful payment.

### Counselor / Admin Dashboard
* **Secure Authentication**: JWT-based secure login with bcrypt password hashing.
* **Dashboard Analytics**: Real-time overview of appointments, earnings, and client base.
* **Comprehensive Schedule Management**:
  * View Today's, Upcoming, Completed, and Cancelled appointments.
  * Direct "Start Meeting" integration for Zoom.
* **Follow-up Workflow System**:
  * Easily mark sessions as complete or request a follow-up.
  * Automated payment link generation for returning clients.
* **Client Management**: Searchable client directory with full session history and private counselor notes.
* **Slot Configuration**: Manage default working hours, block specific time slots, and schedule holidays.

## Technology Stack

* **Frontend**: React.js, Vite, Tailwind CSS v4, React Router, Axios, Framer Motion, Chart.js
* **Backend**: Node.js, Express.js
* **Database**: PostgreSQL
* **Third-Party APIs**: 
  * Razorpay (Payments)
  * Zoom API (Video Conferencing - Server-to-Server OAuth)
  * Twilio (SMS & WhatsApp Business API)
  * SendGrid (Email Notifications)

## Local Development Setup

### 1. Prerequisites
* Node.js (v18+)
* PostgreSQL installed and running

### 2. Database Configuration
Create a PostgreSQL database named \`telugu_counseling\` and run the seed script:
\`\`\`bash
cd server
npm run seed
\`\`\`

### 3. Environment Variables
Copy \`.env.example\` to \`.env\` in the root directory and fill in your API keys:
* Database credentials
* JWT Secret
* Razorpay Key ID and Secret
* Zoom Account ID, Client ID, and Client Secret
* Twilio SID and Auth Token
* SendGrid API Key

### 4. Running the Servers
Start the backend server (runs on port 5000):
\`\`\`bash
cd server
npm run dev
\`\`\`

Start the frontend Vite server (runs on port 5173):
\`\`\`bash
cd client
npm run dev
\`\`\`

## Default Admin Credentials
For testing purposes, the seed script creates a default admin account:
* **Email**: adullasridevireddy810@gmail.com
* **Password**: Admin@123456

*(Please change this password in production!)*

## Security Implementations
* **Helmet.js**: Sets secure HTTP headers (CSP, HSTS).
* **CORS**: Configured strictly for the frontend domain.
* **Rate Limiting**: Protects against brute-force (auth routes) and DDoS (API routes).
* **CSRF/XSS Protection**: Handled via secure cookie policies and React's built-in escaping.
* **Data Validation**: Strict input validation using \`express-validator\`.
* **Parameterized Queries**: Prevents SQL injection via \`node-postgres\`.

## License
Proprietary software. All rights reserved.
