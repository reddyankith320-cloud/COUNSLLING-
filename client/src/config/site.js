// Single source of truth for copy that appears in several places.
// NOTE: the fees charged are defined on the server in routes/booking.js —
// keep these two in sync when you change pricing.

export const PRICING = {
  registrationFee: 999,
  followUpFee: 499,
  maxFollowUps: 3,
  sessionMinutes: 60,
};

export const COUNSELOR = {
  name: 'Adulla Sridevi Reddy',
  initials: 'SR',
  qualification: 'Master of Social Work (MSW)',
  qualificationLong: 'Master of Social Work (MSW) – Postgraduate Degree',
  experience: '20+ Years',
  experienceLong: '20+ Years of Professional Counseling Experience',
};

export const CONTACT = {
  phone: '+91 98765 43210',
  email: 'hello@findmypeace.in',
  location: 'Hyderabad, Telangana',
};

export const SESSION_TIMES = '6:00 PM – 9:00 PM IST';
