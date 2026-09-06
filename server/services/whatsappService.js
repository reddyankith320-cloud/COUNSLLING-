const twilioClient = require('../config/twilio');
require('dotenv').config();

class WhatsAppService {
  /**
   * Send a WhatsApp message via Twilio
   * @param {string} to - Phone number (Indian, 10 digits)
   * @param {string} message - Message body
   */
  async sendMessage(to, message) {
    try {
      const formattedNumber = to.startsWith('+91') ? to : `+91${to}`;

      const result = await twilioClient.messages.create({
        body: message,
        from: process.env.TWILIO_WHATSAPP_NUMBER,
        to: `whatsapp:${formattedNumber}`,
      });

      console.log(`WhatsApp sent to ${formattedNumber}: ${result.sid}`);
      return result;
    } catch (error) {
      console.error('WhatsApp sending failed:', error.message);
      if (process.env.NODE_ENV === 'development') {
        console.log(`[DEV] WhatsApp would be sent to ${to}: ${message}`);
        return { sid: 'dev_mock_sid' };
      }
      throw error;
    }
  }

  /**
   * Send booking confirmation via WhatsApp
   */
  async sendBookingConfirmation({ clientName, mobile, date, time, meetLink }) {
    const message = `🙏 *Booking Confirmed!*\n\nDear *${clientName}*,\n\nYour counseling session with *Find My Peace* has been successfully booked.\n\n📅 *Date:* ${date}\n⏰ *Time:* ${time}\n🔗 *Google Meet:* ${meetLink}\n\nPlease join 5 minutes before the session.\n\n_Find My Peace_`;
    return this.sendMessage(mobile, message);
  }

  /**
   * Send follow-up payment request via WhatsApp
   */
  async sendFollowupPaymentRequest({ clientName, mobile, paymentLink }) {
    const message = `Dear *${clientName}*,\n\nBased on today's counseling session, a follow-up consultation has been recommended.\n\nPlease complete the follow-up consultation fee of *₹499* using the secure payment link below.\n\n💳 ${paymentLink}\n\nOnce payment is completed, you can choose your preferred date and time for the next session.\n\nThank you.\n_Find My Peace_`;
    return this.sendMessage(mobile, message);
  }

  /**
   * Send updated Meet link via WhatsApp
   */
  async sendUpdatedMeetLink({ clientName, mobile, date, time, meetLink }) {
    const message = `🙏 *Follow-up Session Scheduled!*\n\nDear *${clientName}*,\n\nYour follow-up counseling session with *Find My Peace* has been booked.\n\n📅 *Date:* ${date}\n⏰ *Time:* ${time}\n🔗 *Google Meet:* ${meetLink}\n\n_Find My Peace_`;
    return this.sendMessage(mobile, message);
  }
}

module.exports = new WhatsAppService();
