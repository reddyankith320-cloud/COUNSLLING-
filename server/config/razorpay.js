require('dotenv').config();

const RAZORPAY_CONFIG = {
  key_id: process.env.RAZORPAY_KEY_ID,
  key_secret: process.env.RAZORPAY_KEY_SECRET,
  webhook_secret: process.env.RAZORPAY_WEBHOOK_SECRET,
};

module.exports = { RAZORPAY_CONFIG };
