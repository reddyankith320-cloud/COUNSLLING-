const { Resend } = require('resend');
require('dotenv').config();

// Server-side only. The API key is read from the environment and is never
// logged, returned to callers, or exposed to the frontend.
const apiKey = process.env.RESEND_API_KEY;

// Sender must be an address on a domain verified in the Resend dashboard.
const FROM_EMAIL = process.env.RESEND_FROM_EMAIL || 'Find My Peace <noreply@findmypeace.in>';

let resendClient = null;
if (apiKey && apiKey.startsWith('re_')) {
  resendClient = new Resend(apiKey);
} else {
  console.warn('[Email] RESEND_API_KEY not configured. Email sending is in MOCK mode.');
}

/**
 * Send one email through Resend.
 * @param {Object} opts
 * @param {string|string[]} opts.to
 * @param {string} opts.subject
 * @param {string} [opts.html]
 * @param {string} [opts.text]
 * @param {string} [opts.replyTo]
 * @returns {Promise<Object>} Resend response data (or a mock marker in dev)
 * @throws {Error} A sanitized error that never contains the API key
 */
async function sendEmail({ to, subject, html, text, replyTo }) {
  if (!to) throw new Error('Email recipient (to) is required');
  if (!subject) throw new Error('Email subject is required');

  if (!resendClient) {
    // MOCK mode: no key configured. Log intent only — never the key.
    console.log(`[MOCK Email] -> ${Array.isArray(to) ? to.join(', ') : to} | ${subject}`);
    return { mock: true };
  }

  try {
    const { data, error } = await resendClient.emails.send({
      from: FROM_EMAIL,
      to: Array.isArray(to) ? to : [to],
      subject,
      html,
      text,
      ...(replyTo ? { replyTo } : {}),
    });

    // Resend returns { data, error } rather than throwing on API errors.
    if (error) {
      throw new Error(error.message || 'Resend rejected the message');
    }
    return data;
  } catch (err) {
    // Resend errors carry a message/name, never the API key — but re-wrap
    // defensively so nothing upstream can log the original object.
    throw new Error(`Email send failed: ${err.message || 'unknown error'}`);
  }
}

module.exports = {
  sendEmail,
  FROM_EMAIL,
  isConfigured: () => Boolean(resendClient),
};
