const express = require("express");
const router = express.Router();
const crypto = require("crypto");
const { query } = require("../config/database");
const paymentService = require("../services/paymentService");
const meetService = require("../services/meetService");
const emailService = require("../services/emailService");
const smsService = require("../services/smsService");
const whatsappService = require("../services/whatsappService");
const { paymentLimiter } = require("../middleware/rateLimiter");

// POST /api/payments/create-order — Create a Razorpay order (standalone / generic)
router.post("/create-order", async (req, res, next) => {
  try {
    const { amount, receipt, notes } = req.body;

    // Validate: amount must be at least 100 paise (₹1)
    const amountPaise = parseInt(amount, 10);
    if (!amountPaise || amountPaise < 100) {
      return res.status(400).json({ error: "Amount must be at least 100 paise (₹1)." });
    }

    const order = await paymentService.createOrder({
      amount:  amountPaise,
      receipt: (receipt || "order_" + Date.now()).substring(0, 40),
      notes:   notes || {},
    });

    return res.status(201).json({
      order_id: order.id,
      amount:   order.amount,
      currency: order.currency || "INR",
    });
  } catch (error) {
    next(error);
  }
});

// POST /api/payments/verify — Verify Razorpay payment and complete booking

router.post("/verify", paymentLimiter, async (req, res, next) => {
  try {
    const { razorpay_order_id, razorpay_payment_id, razorpay_signature, appointmentId } = req.body;

    if (!razorpay_order_id || !razorpay_payment_id || !razorpay_signature || !appointmentId) {
      return res.status(400).json({ error: "Razorpay payment details and appointment ID are required." });
    }

    // Verify Razorpay signature — never trust frontend payment success
    const verification = paymentService.verifyPayment({ razorpay_order_id, razorpay_payment_id, razorpay_signature });

    if (!verification.verified && process.env.NODE_ENV !== "development") {
      return res.status(400).json({ error: "Payment verification failed. Please contact support." });
    }

    // Idempotency: prevent duplicate processing
    const existingPayment = await query(
      "SELECT id, status FROM payments WHERE razorpay_payment_id = $1",
      [razorpay_payment_id]
    );
    if (existingPayment.rows.length > 0 && existingPayment.rows[0].status === "completed") {
      return res.status(409).json({ error: "This payment has already been processed." });
    }

    // Mark payment completed in DB
    await query(
      `UPDATE payments
         SET razorpay_payment_id = $1,
             razorpay_signature  = $2,
             payment_method      = 'Razorpay',
             status              = 'completed',
             updated_at          = NOW()
       WHERE razorpay_order_id = $3`,
      [razorpay_payment_id, razorpay_signature, razorpay_order_id]
    );

    // Fetch appointment + client
    const appointmentResult = await query(
      `SELECT a.*, c.full_name, c.mobile, c.email
         FROM appointments a
         JOIN clients c ON a.client_id = c.id
        WHERE a.id = $1`,
      [appointmentId]
    );

    if (appointmentResult.rows.length === 0) {
      return res.status(404).json({ error: "Appointment not found" });
    }

    const appointment = appointmentResult.rows[0];
    const dateStr = new Date(appointment.appointment_date).toLocaleDateString("en-IN", {
      weekday: "long", year: "numeric", month: "long", day: "numeric",
    });
    
    // Parse time from DB (e.g. '18:00:00')
    const startTimeStr = appointment.start_time.substring(0, 5);
    const endTimeStr = appointment.end_time.substring(0, 5);
    
    // Convert to 12-hour AM/PM format
    const formatTime = (time) => {
      let [h, m] = time.split(':');
      let hour = parseInt(h);
      const ampm = hour >= 12 ? 'PM' : 'AM';
      hour = hour % 12 || 12;
      return `${hour}:${m} ${ampm}`;
    };
    
    const timeStr = `${formatTime(startTimeStr)} - ${formatTime(endTimeStr)} (IST)`;

    // Create Google Meet event
    let meetMeeting = { eventId: null, meetLink: null, calendarLink: null };
    try {
      meetMeeting = await meetService.createMeeting({
        summary: "Counseling Session - " + appointment.full_name,
        startTime: new Date(appointment.appointment_date).toISOString().split("T")[0] + "T" + startTimeStr + "+05:30",
        duration: 60,
        attendeeEmail: appointment.email,
      });
    } catch (meetError) {
      console.error("Google Meet creation failed (non-fatal):", meetError.message);
    }

    // Book the appointment (guard against race conditions)
    try {
      await query(
        `UPDATE appointments
            SET status               = 'Booked',
                google_event_id      = $1,
                meet_join_url        = $2,
                google_calendar_link = $3,
                updated_at           = NOW()
          WHERE id = $4`,
        [meetMeeting.eventId, meetMeeting.meetLink, meetMeeting.calendarLink, appointmentId]
      );
    } catch (dbError) {
      if (dbError.code === "23505") {
        return res.status(409).json({ error: "This date was just booked by someone else. Please contact support." });
      }
      throw dbError;
    }

    req.io?.emit("availability_changed");

    const notifications = {
      clientName: appointment.full_name,
      email: appointment.email,
      mobile: appointment.mobile,
      date: dateStr,
      time: timeStr,
      meetLink: meetMeeting.meetLink,
      meetingId: meetMeeting.eventId,
      startTime: startTimeStr,
      endTime: endTimeStr,
    };

    Promise.allSettled([
      emailService.sendBookingConfirmation(notifications),
      smsService.sendBookingConfirmation(notifications),
      whatsappService.sendBookingConfirmation(notifications),
    ]).then(results => {
      results.forEach((r, i) => {
        if (r.status === "rejected") console.error("Notification " + i + " failed:", r.reason);
      });
    });

    res.json({
      message: "Payment verified and booking confirmed!",
      appointment: {
        id: appointmentId,
        date: dateStr,
        time: timeStr,
        meetLink: meetMeeting.meetLink,
        meetingId: meetMeeting.eventId,
      },
    });
  } catch (error) {
    next(error);
  }
});

// POST /api/payments/webhook — Razorpay async webhook
router.post("/webhook", express.raw({ type: "application/json" }), async (req, res, next) => {
  try {
    const rawBody = req.body;
    const razorpaySignature = req.headers["x-razorpay-signature"];

    if (process.env.RAZORPAY_WEBHOOK_SECRET && razorpaySignature) {
      const expectedSignature = crypto
        .createHmac("sha256", process.env.RAZORPAY_WEBHOOK_SECRET)
        .update(rawBody)
        .digest("hex");
      if (!crypto.timingSafeEqual(Buffer.from(expectedSignature), Buffer.from(razorpaySignature))) {
        return res.status(400).json({ error: "Invalid webhook signature" });
      }
    }

    const event = JSON.parse(rawBody);
    const eventType = event.event;
    const paymentEntity = event.payload && event.payload.payment && event.payload.payment.entity;

    if (!paymentEntity) return res.json({ status: "ok" });

    const razorpayOrderId   = paymentEntity.order_id;
    const razorpayPaymentId = paymentEntity.id;
    const paymentMethod     = paymentEntity.method || "Razorpay";

    if (eventType === "payment.captured") {
      await query(
        `UPDATE payments
            SET status              = 'completed',
                razorpay_payment_id = $1,
                payment_method      = $2,
                updated_at          = NOW()
          WHERE razorpay_order_id = $3 AND status != 'completed'`,
        [razorpayPaymentId, paymentMethod, razorpayOrderId]
      );
    }

    if (eventType === "payment.failed") {
      await query(
        `UPDATE payments SET status = 'failed', updated_at = NOW() WHERE razorpay_order_id = $1`,
        [razorpayOrderId]
      );
      // Release slot
      await query(
        `UPDATE appointments SET status = 'Cancelled', updated_at = NOW()
          WHERE id = (SELECT appointment_id FROM payments WHERE razorpay_order_id = $1 LIMIT 1)`,
        [razorpayOrderId]
      );
      req.io?.emit("availability_changed");
    }

    res.json({ status: "ok" });
  } catch (error) {
    next(error);
  }
});

module.exports = router;
