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
const { toDateString, to12Hour } = require("../utils/dates");

// POST /api/payments/verify — Verify Razorpay payment and complete booking
router.post("/verify", paymentLimiter, async (req, res, next) => {
  try {
    const { razorpay_order_id, razorpay_payment_id, razorpay_signature, appointmentId } = req.body;

    if (!razorpay_order_id || !razorpay_payment_id || !razorpay_signature || !appointmentId) {
      return res.status(400).json({ error: "Razorpay payment details and appointment ID are required." });
    }

    // Verify Razorpay signature — never trust frontend payment success.
    // (paymentService auto-approves only when no RAZORPAY_KEY_SECRET is configured.)
    const verification = paymentService.verifyPayment({ razorpay_order_id, razorpay_payment_id, razorpay_signature });
    if (!verification.verified) {
      return res.status(400).json({ error: "Payment verification failed. Please contact support." });
    }

    // The order must belong to THIS appointment — otherwise one paid order could
    // be replayed to confirm any other pending appointment.
    const paymentRow = await query(
      "SELECT id, status, razorpay_payment_id FROM payments WHERE razorpay_order_id = $1 AND appointment_id = $2",
      [razorpay_order_id, appointmentId]
    );
    if (paymentRow.rows.length === 0) {
      return res.status(400).json({ error: "Payment does not match this appointment." });
    }

    // Idempotency: prevent duplicate processing
    if (paymentRow.rows[0].status === "completed") {
      return res.status(409).json({ error: "This payment has already been processed." });
    }

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

    if (appointment.status !== "pending_payment") {
      return res.status(409).json({ error: `This appointment is already ${appointment.status}.` });
    }

    // Mark payment completed in DB
    await query(
      `UPDATE payments
         SET razorpay_payment_id = $1,
             razorpay_signature  = $2,
             payment_method      = 'Razorpay',
             status              = 'completed',
             updated_at          = NOW()
       WHERE id = $3`,
      [razorpay_payment_id, razorpay_signature, paymentRow.rows[0].id]
    );

    const isoDate = toDateString(appointment.appointment_date);
    const dateStr = new Date(`${isoDate}T00:00:00+05:30`).toLocaleDateString("en-IN", {
      weekday: "long", year: "numeric", month: "long", day: "numeric", timeZone: "Asia/Kolkata",
    });

    // Parse time from DB (e.g. '18:00:00')
    const startTimeStr = appointment.start_time.substring(0, 5);
    const endTimeStr = appointment.end_time.substring(0, 5);
    const timeStr = `${to12Hour(startTimeStr)} - ${to12Hour(endTimeStr)} (IST)`;

    // Create Google Meet event
    let meetMeeting = { eventId: null, meetLink: null, calendarLink: null };
    try {
      meetMeeting = await meetService.createMeeting({
        summary: "Counseling Session - " + appointment.full_name,
        startTime: `${isoDate}T${startTimeStr}:00+05:30`,
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
        return res.status(409).json({ error: "This slot was just booked by someone else. Please contact support for a refund or reschedule." });
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
      consultationType: appointment.consultation_type,
      problemDescription: appointment.problem_description,
      meetLink: meetMeeting.meetLink,
      meetingId: meetMeeting.eventId,
      startTime: startTimeStr,
      endTime: endTimeStr,
    };

    Promise.allSettled([
      emailService.sendBookingConfirmation(notifications),          // flow 1: customer
      emailService.sendBookingNotificationToCounselor(notifications), // flow 2: company
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
        isoDate,
        time: timeStr,
        startTime: startTimeStr,
        endTime: endTimeStr,
        consultationType: appointment.consultation_type,
        meetLink: meetMeeting.meetLink,
        meetingId: meetMeeting.eventId,
        calendarLink: meetMeeting.calendarLink,
      },
    });
  } catch (error) {
    next(error);
  }
});

// POST /api/payments/webhook — Razorpay async webhook
// NOTE: req.rawBody is captured by the express.json() `verify` hook in server.js,
// because the body has already been parsed by the time we get here.
router.post("/webhook", async (req, res, next) => {
  try {
    const rawBody = req.rawBody;
    const razorpaySignature = req.headers["x-razorpay-signature"];

    if (!rawBody) {
      return res.status(400).json({ error: "Missing request body" });
    }

    if (process.env.RAZORPAY_WEBHOOK_SECRET) {
      if (!razorpaySignature) {
        return res.status(400).json({ error: "Missing webhook signature" });
      }
      const expectedSignature = crypto
        .createHmac("sha256", process.env.RAZORPAY_WEBHOOK_SECRET)
        .update(rawBody)
        .digest("hex");
      const expectedBuf = Buffer.from(expectedSignature);
      const receivedBuf = Buffer.from(String(razorpaySignature));
      if (expectedBuf.length !== receivedBuf.length || !crypto.timingSafeEqual(expectedBuf, receivedBuf)) {
        return res.status(400).json({ error: "Invalid webhook signature" });
      }
    }

    const event = typeof req.body === "object" && req.body !== null ? req.body : JSON.parse(rawBody.toString("utf8"));
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
        `UPDATE payments SET status = 'failed', updated_at = NOW() WHERE razorpay_order_id = $1 AND status = 'pending'`,
        [razorpayOrderId]
      );
      // Release slot (only if it was still waiting for payment)
      await query(
        `UPDATE appointments SET status = 'Cancelled', updated_at = NOW()
          WHERE status = 'pending_payment'
            AND id = (SELECT appointment_id FROM payments WHERE razorpay_order_id = $1 LIMIT 1)`,
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
