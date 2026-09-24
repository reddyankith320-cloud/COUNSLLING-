const { sendEmail: sendViaResend } = require('../config/resend');
require('dotenv').config();

class EmailService {
  /**
   * Send an email through the Resend transport.
   * Signature kept identical to the previous implementation so callers
   * (payment.js, admin.js) need no changes.
   */
  async sendEmail({ to, subject, html, text, replyTo }) {
    try {
      await sendViaResend({ to, subject, html, text, replyTo });
      console.log(`Email sent to ${to}`);
    } catch (error) {
      // error.message is sanitized in config/resend and never contains the key
      console.error('Email sending failed:', error.message);
      if (process.env.NODE_ENV === 'development') {
        console.log(`[DEV] Email would be sent to ${to}: ${subject}`);
        return;
      }
      throw error;
    }
  }

  /**
   * Send booking confirmation email
   */
  async sendBookingConfirmation({ clientName, email, date, time, meetLink, meetingId }) {
    const subject = '✅ Your Counseling Session is Confirmed! - Find My Peace';
    const displayTime = time || '6:00 PM – 7:00 PM (IST)';
    const html = `
      <!DOCTYPE html>
      <html>
      <head>
        <meta charset="UTF-8">
        <style>
          body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f0f7ff; margin: 0; padding: 0; }
          .container { max-width: 600px; margin: 0 auto; background: white; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.08); }
          .header { background: linear-gradient(135deg, #0ea5e9, #22c55e); padding: 40px 30px; text-align: center; }
          .header h1 { color: white; margin: 0; font-size: 24px; }
          .header p { color: rgba(255,255,255,0.9); margin: 8px 0 0; }
          .content { padding: 30px; }
          .greeting { font-size: 18px; color: #1e293b; margin-bottom: 20px; }
          .detail-box { background: #f0f7ff; border-radius: 12px; padding: 20px; margin: 20px 0; }
          .detail-row { display: flex; padding: 8px 0; border-bottom: 1px solid #e2e8f0; }
          .detail-row:last-child { border: none; }
          .detail-label { font-weight: 600; color: #475569; width: 120px; }
          .detail-value { color: #1e293b; }
          .meet-link { display: inline-block; background: linear-gradient(135deg, #0ea5e9, #0284c7); color: white; padding: 14px 28px; border-radius: 8px; text-decoration: none; font-weight: 600; margin: 20px 0; }
          .footer { background: #f8fafc; padding: 20px 30px; text-align: center; color: #64748b; font-size: 14px; }
        </style>
      </head>
      <body>
        <div class="container">
          <div class="header">
            <h1>🙏 Booking Confirmed!</h1>
            <p>Find My Peace – Counseling Services</p>
          </div>
          <div class="content">
            <p class="greeting">Dear <strong>${clientName}</strong>,</p>
            <p>Your counseling session has been successfully booked. Here are your session details:</p>
            <div class="detail-box">
              <div class="detail-row">
                <span class="detail-label">📅 Date</span>
                <span class="detail-value">${date}</span>
              </div>
              <div class="detail-row">
                <span class="detail-label">⏰ Time</span>
                <span class="detail-value">${displayTime}</span>
              </div>
              <div class="detail-row">
                <span class="detail-label">🆔 Meeting ID</span>
                <span class="detail-value">${meetingId}</span>
              </div>
            </div>
            <div style="text-align: center; margin: 30px 0;">
              <a href="${meetLink}" class="meet-link">🔗 Join Google Meet</a>
            </div>
            <p style="color: #64748b; font-size: 14px;">Please join the meeting 5 minutes before your scheduled time.</p>
          </div>
          <div class="footer">
            <p>Thank you for choosing Find My Peace – Counseling Services</p>
            <p>If you need to reschedule, please contact us.</p>
          </div>
        </div>
      </body>
      </html>
    `;

    const text = `Dear ${clientName},\n\nYour counseling session is confirmed!\n\nDate: ${date}\nTime: ${displayTime}\nMeeting ID: ${meetingId}\nGoogle Meet Link: ${meetLink}\nPlease join 5 minutes early.\n\n- Find My Peace`;

    return this.sendEmail({ to: email, subject, html, text });
  }

  /**
   * Send follow-up payment request email
   */
  async sendFollowupPaymentRequest({ clientName, email, bookingLink, followUpNumber }) {
    const subject = 'Follow-up Session Recommended - Find My Peace';
    const sessionLabel = followUpNumber ? `Follow-up session ${followUpNumber} of 3` : 'Follow-up session';
    const html = `
      <!DOCTYPE html>
      <html>
      <head>
        <meta charset="UTF-8">
        <style>
          body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f0f7ff; margin: 0; padding: 0; }
          .container { max-width: 600px; margin: 0 auto; background: white; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.08); }
          .header { background: linear-gradient(135deg, #0ea5e9, #22c55e); padding: 40px 30px; text-align: center; }
          .header h1 { color: white; margin: 0; font-size: 24px; }
          .content { padding: 30px; }
          .pay-btn { display: inline-block; background: linear-gradient(135deg, #22c55e, #16a34a); color: white; padding: 16px 32px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 16px; margin: 20px 0; }
          .amount { font-size: 28px; font-weight: 700; color: #22c55e; }
          .footer { background: #f8fafc; padding: 20px 30px; text-align: center; color: #64748b; font-size: 14px; }
        </style>
      </head>
      <body>
        <div class="container">
          <div class="header">
            <h1>Follow-up Session Recommended</h1>
          </div>
          <div class="content">
            <p>Dear <strong>${clientName}</strong>,</p>
            <p>Based on today's counseling session, a follow-up consultation has been recommended (${sessionLabel}).</p>
            <p>Choose a date and time that suits you and complete the follow-up fee of <span class="amount">₹499</span> securely via Razorpay. Please use the same mobile number and email so we can link it to your file.</p>
            <div style="text-align: center; margin: 30px 0;">
              <a href="${bookingLink}" class="pay-btn">📅 Book Follow-up Session</a>
            </div>
            <p>You will receive your Google Meet link immediately after payment.</p>
            <p>Thank you.</p>
          </div>
          <div class="footer">
            <p>Find My Peace – Counseling Services</p>
          </div>
        </div>
      </body>
      </html>
    `;

    const text = `Dear ${clientName},\n\nBased on today's counseling session, a follow-up consultation has been recommended (${sessionLabel}).\n\nChoose your preferred date and time and complete the follow-up fee of ₹499 here:\n${bookingLink}\n\nPlease use the same mobile number and email so we can link it to your file. You will receive your Google Meet link immediately after payment.\n\nThank you.\n- Find My Peace`;

    return this.sendEmail({ to: email, subject, html, text });
  }

  /**
   * Send updated appointment details email
   */
  async sendUpdatedAppointment({ clientName, email, date, time, meetLink, meetingId }) {
    const subject = '📅 Follow-up Session Scheduled - Find My Peace';
    const html = `
      <!DOCTYPE html>
      <html>
      <head>
        <meta charset="UTF-8">
        <style>
          body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f0f7ff; margin: 0; padding: 0; }
          .container { max-width: 600px; margin: 0 auto; background: white; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.08); }
          .header { background: linear-gradient(135deg, #0ea5e9, #22c55e); padding: 40px 30px; text-align: center; }
          .header h1 { color: white; margin: 0; font-size: 24px; }
          .content { padding: 30px; }
          .detail-box { background: #f0f7ff; border-radius: 12px; padding: 20px; margin: 20px 0; }
          .meet-link { display: inline-block; background: linear-gradient(135deg, #0ea5e9, #0284c7); color: white; padding: 14px 28px; border-radius: 8px; text-decoration: none; font-weight: 600; margin: 20px 0; }
          .footer { background: #f8fafc; padding: 20px 30px; text-align: center; color: #64748b; font-size: 14px; }
        </style>
      </head>
      <body>
        <div class="container">
          <div class="header">
            <h1>Follow-up Session Scheduled!</h1>
          </div>
          <div class="content">
            <p>Dear <strong>${clientName}</strong>,</p>
            <p>Your follow-up counseling session has been scheduled.</p>
            <div class="detail-box">
              <p>📅 <strong>Date:</strong> ${date}</p>
              <p>⏰ <strong>Time:</strong> ${time}</p>
              <p>🆔 <strong>Meeting ID:</strong> ${meetingId}</p>
            </div>
            <div style="text-align: center;">
              <a href="${meetLink}" class="meet-link">🔗 Join Google Meet</a>
            </div>
          </div>
          <div class="footer">
            <p>Find My Peace – Counseling Services</p>
          </div>
        </div>
      </body>
      </html>
    `;

    return this.sendEmail({ to: email, subject, html, text: `Follow-up session: ${date} at ${time}. Google Meet: ${meetLink}` });
  }

  /**
   * Company notification — sent to the counselor when a booking is confirmed.
   * Recipient defaults to ADMIN_EMAIL when COUNSELOR_NOTIFY_EMAIL isn't set.
   */
  async sendBookingNotificationToCounselor({ clientName, email, mobile, date, time, consultationType, problemDescription, meetLink }) {
    const to = process.env.COUNSELOR_NOTIFY_EMAIL || process.env.ADMIN_EMAIL;
    if (!to) {
      console.warn('[Email] No COUNSELOR_NOTIFY_EMAIL/ADMIN_EMAIL set — skipping counselor notification.');
      return;
    }

    const bookedAt = new Date().toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short' });
    const esc = (s) => String(s ?? '—')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const subject = `New booking: ${clientName} — ${date}`;

    const row = (label, value) => `
      <tr>
        <td style="padding:10px 14px;background:#f8fafc;color:#475569;font-weight:600;width:150px;border-bottom:1px solid #e2e8f0;vertical-align:top">${label}</td>
        <td style="padding:10px 14px;color:#0f172a;border-bottom:1px solid #e2e8f0">${value}</td>
      </tr>`;

    const html = `
      <!DOCTYPE html>
      <html>
      <head><meta charset="UTF-8"></head>
      <body style="font-family:'Segoe UI',Tahoma,sans-serif;background:#f0f7ff;margin:0;padding:24px">
        <div style="max-width:600px;margin:0 auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.08)">
          <div style="background:linear-gradient(135deg,#0d9488,#0f766e);padding:28px 30px">
            <h1 style="color:#fff;margin:0;font-size:20px">🔔 New Booking Confirmed</h1>
            <p style="color:rgba(255,255,255,0.9);margin:6px 0 0;font-size:13px">Find My Peace — Counseling Services</p>
          </div>
          <div style="padding:24px 30px">
            <p style="color:#334155;margin:0 0 16px">A payment was completed and a session is confirmed. Client details:</p>
            <table style="width:100%;border-collapse:collapse;border:1px solid #e2e8f0;border-radius:10px;overflow:hidden;font-size:14px">
              ${row('Client', esc(clientName))}
              ${row('Email', `<a href="mailto:${esc(email)}" style="color:#0d9488">${esc(email)}</a>`)}
              ${row('Phone', mobile ? `+91 ${esc(mobile)}` : 'Not provided')}
              ${row('Date', esc(date))}
              ${row('Time', esc(time))}
              ${row('Type', esc(consultationType))}
              ${row('Concern', esc(problemDescription))}
              ${meetLink ? row('Google Meet', `<a href="${esc(meetLink)}" style="color:#0d9488">${esc(meetLink)}</a>`) : ''}
              ${row('Booked at', esc(bookedAt) + ' IST')}
            </table>
          </div>
          <div style="background:#f8fafc;padding:16px 30px;text-align:center;color:#64748b;font-size:12px">
            Automated notification from your Find My Peace booking system.
          </div>
        </div>
      </body>
      </html>
    `;

    const text = [
      'New booking confirmed — Find My Peace',
      `Client: ${clientName}`,
      `Email: ${email}`,
      `Phone: ${mobile ? '+91 ' + mobile : 'Not provided'}`,
      `Date: ${date}`,
      `Time: ${time}`,
      `Type: ${consultationType || '—'}`,
      `Concern: ${problemDescription || '—'}`,
      meetLink ? `Google Meet: ${meetLink}` : '',
      `Booked at: ${bookedAt} IST`,
    ].filter(Boolean).join('\n');

    // reply-to the client so the counselor can respond directly
    return this.sendEmail({ to, subject, html, text, replyTo: email });
  }
}

module.exports = new EmailService();
