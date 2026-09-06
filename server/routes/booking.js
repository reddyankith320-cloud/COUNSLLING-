const express = require("express");
const router = express.Router();
const { query, getClient } = require("../config/database");
const { bookingValidation } = require("../middleware/validator");
const slotService = require("../services/slotService");
const paymentService = require("../services/paymentService");

// Consultation fee rules
const INITIAL_FEE   = 7;   // New patient (Registration Fee)
const FOLLOWUP_FEE  = 499;   // Follow-up sessions 1, 2, 3
const MAX_FOLLOWUPS = 3;     // Maximum follow-up sessions allowed

// POST /api/bookings — Create a new booking and Razorpay order
router.post("/", bookingValidation, async (req, res, next) => {
  const client = await getClient();

  try {
    await client.query("BEGIN");

    const { fullName, age, gender, mobile, email, problemDescription, appointmentDate, startTime, endTime } = req.body;

    if (!fullName || !age || !gender || !mobile || !email || !problemDescription || !appointmentDate || !startTime || !endTime) {
      return res.status(400).json({ error: "All fields are required" });
    }

    // Check slot availability
    const isAvailable = await slotService.isSlotAvailable(appointmentDate, startTime);
    if (!isAvailable) {
      return res.status(409).json({ error: "This time slot is no longer available. Please choose another." });
    }

    // Create or find client record
    let clientResult = await client.query(
      "SELECT id FROM clients WHERE mobile = $1 AND email = $2",
      [mobile, email]
    );

    let clientId;
    if (clientResult.rows.length > 0) {
      clientId = clientResult.rows[0].id;
      await client.query(
        "UPDATE clients SET full_name = $1, age = $2, gender = $3, is_archived = FALSE WHERE id = $4",
        [fullName, age, gender, clientId]
      );
    } else {
      clientResult = await client.query(
        "INSERT INTO clients (full_name, age, gender, mobile, email) VALUES ($1, $2, $3, $4, $5) RETURNING id",
        [fullName, age, gender, mobile, email]
      );
      clientId = clientResult.rows[0].id;
    }

    // Count past successful appointments to determine fee and consultation type
    const pastApptResult = await client.query(
      "SELECT COUNT(*) as count FROM appointments WHERE client_id = $1 AND status IN ('Booked', 'Completed')",
      [clientId]
    );
    const pastCount = parseInt(pastApptResult.rows[0].count) || 0;

    // Apply business rules
    let consultationFee;
    let consultationType;
    let isFollowup;

    if (pastCount === 0) {
      consultationFee  = INITIAL_FEE;
      consultationType = "Registration Fee";
      isFollowup       = false;
    } else if (pastCount >= 1 && pastCount <= MAX_FOLLOWUPS) {
      consultationFee  = FOLLOWUP_FEE;
      consultationType = "Follow-up " + pastCount;
      isFollowup       = true;
    } else {
      // pastCount > 3 — max follow-ups reached; treat as new patient re-registration
      consultationFee  = INITIAL_FEE;
      consultationType = "Registration Fee";
      isFollowup       = false;
    }

    // Create appointment (pending payment)
    const appointmentResult = await client.query(
      `INSERT INTO appointments (client_id, appointment_date, start_time, end_time, problem_description, status, is_followup, consultation_type)
         VALUES ($1, $2, $3, $4, $5, 'pending_payment', $6, $7)
         RETURNING id`,
      [clientId, appointmentDate, startTime, endTime, problemDescription, isFollowup, consultationType]
    );

    const appointment = appointmentResult.rows[0];

    // Create Razorpay order (amount in paise)
    const order = await paymentService.createOrder({
      amount:  consultationFee * 100,
      receipt: "booking_" + appointment.id,
      notes: {
        appointmentId:    appointment.id,
        clientId,
        clientName:       fullName,
        consultationType,
      },
    });

    // Store payment record (with Razorpay order ID)
    await client.query(
      `INSERT INTO payments (appointment_id, client_id, razorpay_order_id, amount, status, is_followup)
         VALUES ($1, $2, $3, $4, 'pending', $5)`,
      [appointment.id, clientId, order.id, consultationFee, isFollowup]
    );

    await client.query("COMMIT");

    res.status(201).json({
      message: "Booking created. Please complete payment.",
      booking: {
        appointmentId:    appointment.id,
        clientId,
        date:             appointmentDate,
        consultationType,
        amount:           consultationFee,
      },
      payment: {
        orderId:  order.id,
        amount:   consultationFee,
        currency: "INR",
        key:      process.env.RAZORPAY_KEY_ID,
      },
    });
  } catch (error) {
    await client.query("ROLLBACK");
    next(error);
  } finally {
    client.release();
  }
});

// GET /api/bookings/:id — Get booking details
router.get("/:id", async (req, res, next) => {
  try {
    const result = await query(
      `SELECT a.*, c.full_name, c.age, c.gender, c.mobile, c.email,
              p.status as payment_status, p.razorpay_payment_id, p.amount as payment_amount,
              a.consultation_type
         FROM appointments a
         JOIN clients c ON a.client_id = c.id
         LEFT JOIN payments p ON a.id = p.appointment_id
        WHERE a.id = $1`,
      [req.params.id]
    );

    if (result.rows.length === 0) {
      return res.status(404).json({ error: "Booking not found" });
    }

    res.json({ booking: result.rows[0] });
  } catch (error) {
    next(error);
  }
});

module.exports = router;
