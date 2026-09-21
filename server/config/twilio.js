const twilio = require('twilio');
require('dotenv').config();

const sid = process.env.TWILIO_ACCOUNT_SID;
const token = process.env.TWILIO_AUTH_TOKEN;

let client;

// The Twilio constructor throws if the SID is missing or malformed, which used to
// crash the whole server on startup. Fall back to a mock so SMS/WhatsApp simply log.
if (sid && sid.startsWith('AC') && token && !token.startsWith('your_')) {
  client = twilio(sid, token);
} else {
  console.warn('[Twilio] Credentials not configured. SMS/WhatsApp sending is in MOCK mode.');
  client = {
    messages: {
      create: async ({ to, body }) => {
        console.log(`[MOCK Twilio] -> ${to}: ${body.substring(0, 80)}...`);
        return { sid: 'mock_' + Date.now() };
      },
    },
  };
}

module.exports = client;
