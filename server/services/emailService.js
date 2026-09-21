const sgMail = require('../config/email');
require('dotenv').config();

class EmailService {
  constructor() {
    this.fromEmail = process.env.SENDGRID_FROM_EMAIL || 'counselor@telugucounseling.com';
    this.fromName = process.env.SENDGRID_FROM_NAME || 'Find My Peace';
  }

  /**
   * Send an email
   */
  async sendEmail({ to, subject, html, text }) {
    try {
      await sgMail.send({
        to,
        from: { email: this.fromEmail, name: this.fromName },
        subject,
        html,
        text,
      });
      console.log(`Email sent to ${to}`);
    } catch (error) {
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
}

module.exports = new EmailService();
