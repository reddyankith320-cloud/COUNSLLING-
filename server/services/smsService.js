const twilioClient = require('../config/twilio');
require('dotenv').config();

class SmsService {
  /**
   * Send an SMS message
   * @param {string} to - Phone number (Indian, 10 digits)
   * @param {string} message - Message body
   */
  async sendSms(to, message) {
    try {
      const formattedNumber = to.startsWith('+91') ? to : `+91${to}`;

      const result = await twilioClient.messages.create({
        body: message,
        from: process.env.TWILIO_PHONE_NUMBER,
        to: formattedNumber,
      });

      console.log(`SMS sent to ${formattedNumber}: ${result.sid}`);
      return result;
    } catch (error) {
      console.error('SMS sending failed:', error.message);
      if (process.env.NODE_ENV === 'development') {
        console.log(`[DEV] SMS would be sent to ${to}: ${message}`);
        return { sid: 'dev_mock_sid' };
      }
      throw error;
    }
  }

  /**
   * Send booking confirmation SMS
   */
  async sendBookingConfirmation({ clientName, mobile, date, time, meetLink }) {
    const message = `Dear ${clientName},\n\nYour counseling session with Find My Peace is confirmed!\n\n\uD83D\uDCC5 Date: ${date}\n\u23F0 Time: ${time}\n\uD83D\uDD17 Google Meet: ${meetLink}\n\nPlease join 5 minutes early.\n\n- Find My Peace`;
    return this.sendSms(mobile, message);
  }

  /**
   * Send follow-up payment request SMS
   */
  async sendFollowupPaymentRequest({ clientName, mobile, paymentLink }) {
    const message = `Dear ${clientName},\n\nBased on today's counseling session, a follow-up consultation has been recommended.\n\nPlease complete the follow-up consultation fee of \u20B9499 using the secure payment link below.\n\n${paymentLink}\n\nOnce payment is completed, you can choose your preferred date and time for the next session.\n\nThank you.\n- Find My Peace`;
    return this.sendSms(mobile, message);
  }

  /**
   * Send updated Meet link SMS
   */
  async sendUpdatedMeetLink({ clientName, mobile, date, time, meetLink }) {
    const message = `Dear ${clientName},\n\nYour follow-up session with Find My Peace is scheduled!\n\n\uD83D\uDCC5 Date: ${date}\n\u23F0 Time: ${time}\n\uD83D\uDD17 Google Meet: ${meetLink}\n\n- Find My Peace`;
    return this.sendSms(mobile, message);
  }
}

module.exports = new SmsService();
