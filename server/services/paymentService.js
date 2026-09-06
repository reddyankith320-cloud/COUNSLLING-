// Razorpay Payment Service
const Razorpay = require("razorpay");
const crypto = require("crypto");
require("dotenv").config();

// Only initialise the Razorpay SDK if credentials are present (production)
let razorpayInstance = null;
if (process.env.RAZORPAY_KEY_ID && process.env.RAZORPAY_KEY_SECRET) {
  razorpayInstance = new Razorpay({
    key_id:     process.env.RAZORPAY_KEY_ID,
    key_secret: process.env.RAZORPAY_KEY_SECRET,
  });
} else {
  console.warn("RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET not set. Payment gateway is in MOCK/DEV mode.");
}

class PaymentService {
  /**
   * Create a Razorpay order.
   * @param {Object} options
   * @param {number} options.amount  - Amount in PAISE (500 Rs = 50000 paise)
   * @param {string} options.receipt - Unique receipt string (max 40 chars)
   * @param {Object} options.notes   - Key-value metadata attached to the order
   * @returns {Object}  { id, amount, currency, receipt }
   */
  async createOrder({ amount, receipt, notes = {} }) {
    if (!razorpayInstance) {
      // DEV MOCK: return a fake order so the rest of the flow works without real keys
      const mockId = "order_dev_" + Date.now();
      console.log("[DEV] Mock Razorpay order:", mockId, " | amount paise:", amount);
      return {
        id:       mockId,
        amount,
        currency: "INR",
        receipt,
        status:   "created",
        notes,
      };
    }

    try {
      const order = await razorpayInstance.orders.create({
        amount,
        currency:        "INR",
        receipt:         receipt.substring(0, 40), // Razorpay limit
        notes,
        payment_capture: 1,
      });
      return order;
    } catch (error) {
      console.error("Razorpay order creation failed:", error.error || error.message || error);
      throw new Error("Failed to create Razorpay order: " + (error.error?.description || error.message));
    }
  }

  /**
   * Verify Razorpay payment signature.
   * Uses RAZORPAY_KEY_SECRET to generate an HMAC-SHA256 signature and compare.
   * @param {{ razorpay_order_id, razorpay_payment_id, razorpay_signature }} payload
   * @returns {{ verified, paymentId, orderId, method, status }}
   */
  verifyPayment({ razorpay_order_id, razorpay_payment_id, razorpay_signature }) {
    // DEV mock: auto-approve when key secret is missing
    if (!process.env.RAZORPAY_KEY_SECRET) {
      console.log("[DEV] Mock payment verification passed for order:", razorpay_order_id);
      return {
        verified:  true,
        paymentId: razorpay_payment_id,
        orderId:   razorpay_order_id,
        method:    "Razorpay",
        status:    "SUCCESS",
      };
    }

    const generatedSignature = crypto
      .createHmac("sha256", process.env.RAZORPAY_KEY_SECRET)
      .update(razorpay_order_id + "|" + razorpay_payment_id)
      .digest("hex");

    let verified = false;
    try {
      verified = crypto.timingSafeEqual(
        Buffer.from(generatedSignature, "hex"),
        Buffer.from(razorpay_signature,  "hex")
      );
    } catch {
      verified = false;
    }

    return {
      verified,
      paymentId: razorpay_payment_id,
      orderId:   razorpay_order_id,
      method:    "Razorpay",
      status:    verified ? "SUCCESS" : "FAILED",
    };
  }
}

module.exports = new PaymentService();
