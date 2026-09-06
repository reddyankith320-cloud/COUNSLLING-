const express = require('express');
const router = express.Router();
const { query } = require('../config/database');
const { authenticate, authorizeAdmin } = require('../middleware/auth');
const { noteValidation } = require('../middleware/validator');
const paymentService = require('../services/paymentService');
const { decrypt } = require('../utils/encryption');
const meetService = require('../services/meetService');
const emailService = require('../services/emailService');
const smsService = require('../services/smsService');
const whatsappService = require('../services/whatsappService');

// All admin routes require authentication
router.use(authenticate);

// GET /api/admin/dashboard — Dashboard stats
router.get('/dashboard', async (req, res, next) => {
  try {
    const today = new Date().toISOString().split('T')[0];

    const [todayAppts, upcomingAppts, completedAppts, cancelledAppts, totalEarnings, totalClients] =
      await Promise.all([
        query(
          `SELECT COUNT(*) as count FROM appointments a WHERE appointment_date = $1 AND a.status = 'Booked'`,
          [today]
        ),
        query(
          `SELECT COUNT(*) as count FROM appointments a WHERE appointment_date > $1 AND a.status = 'Booked'`,
          [today]
        ),
        query(`SELECT COUNT(*) as count FROM appointments a WHERE a.status = 'Completed'`),
        query(`SELECT COUNT(*) as count FROM appointments a WHERE a.status = 'Cancelled'`),
        query(`SELECT 
                 COALESCE(SUM(CASE WHEN is_followup = FALSE THEN amount ELSE 0 END), 0) as initial_total,
                 COALESCE(SUM(CASE WHEN is_followup = TRUE THEN amount ELSE 0 END), 0) as followup_total,
                 COALESCE(SUM(amount), 0) as total 
               FROM payments WHERE status = 'completed'`),
        query(`SELECT COUNT(*) as count FROM clients WHERE is_archived = FALSE`),
      ]);

    res.json({
      stats: {
        todayAppointments: parseInt(todayAppts.rows[0].count),
        upcomingAppointments: parseInt(upcomingAppts.rows[0].count),
        completedAppointments: parseInt(completedAppts.rows[0].count),
        cancelledAppointments: parseInt(cancelledAppts.rows[0].count),
        totalEarnings: parseFloat(totalEarnings.rows[0].total),
        initialEarnings: parseFloat(totalEarnings.rows[0].initial_total),
        followupEarnings: parseFloat(totalEarnings.rows[0].followup_total),
        totalClients: parseInt(totalClients.rows[0].count),
      },
    });
  } catch (error) {
    next(error);
  }
});

// GET /api/admin/appointments — List appointments with filters
router.get('/appointments', async (req, res, next) => {
  try {
    const { status, date, page = 1, limit = 20 } = req.query;
    const offset = (page - 1) * limit;
    const today = new Date().toISOString().split('T')[0];

    let whereClause = '';
    const params = [];
    let paramCount = 0;

    if (status === 'today') {
      paramCount++;
      whereClause = `WHERE a.appointment_date = $${paramCount} AND a.status = 'Booked'`;
      params.push(today);
    } else if (status === 'upcoming') {
      paramCount++;
      whereClause = `WHERE a.appointment_date > $${paramCount} AND a.status = 'Booked'`;
      params.push(today);
    } else if (status) {
      paramCount++;
      whereClause = `WHERE a.status = $${paramCount}`;
      params.push(status);
    }

    if (date) {
      paramCount++;
      whereClause += whereClause ? ` AND a.appointment_date = $${paramCount}` : `WHERE a.appointment_date = $${paramCount}`;
      params.push(date);
    }

    paramCount++;
    const limitParam = paramCount;
    params.push(parseInt(limit));

    paramCount++;
    const offsetParam = paramCount;
    params.push(parseInt(offset));

    const result = await query(
      `SELECT a.*, c.full_name, c.age, c.gender, c.mobile, c.email, c.follow_up_count,
              p.status as payment_status, p.amount as payment_amount
       FROM appointments a
       JOIN clients c ON a.client_id = c.id
       LEFT JOIN payments p ON a.id = p.appointment_id AND p.is_followup = FALSE
       ${whereClause}
       ORDER BY a.appointment_date DESC
       LIMIT $${limitParam} OFFSET $${offsetParam}`,
      params
    );

    const countResult = await query(
      `SELECT COUNT(*) as total FROM appointments a ${whereClause}`,
      params.slice(0, -2)
    );

    res.json({
      appointments: result.rows,
      total: parseInt(countResult.rows[0].total),
      page: parseInt(page),
      totalPages: Math.ceil(parseInt(countResult.rows[0].total) / limit),
    });
  } catch (error) {
    next(error);
  }
});

// PATCH /api/admin/appointments/:id/status — Update appointment status
router.patch('/appointments/:id/status', async (req, res, next) => {
  try {
    const { id } = req.params;
    const { status } = req.body;

    if (!['pending_payment', 'Booked', 'Completed', 'Cancelled', 'no_show', 'Blocked'].includes(status)) {
      return res.status(400).json({ error: 'Invalid status' });
    }

    const result = await query(
      'UPDATE appointments SET status = $1, updated_at = NOW() WHERE id = $2 RETURNING *',
      [status, id]
    );

    if (result.rows.length === 0) {
      return res.status(404).json({ error: 'Appointment not found' });
    }

    const appointment = result.rows[0];

    // If cancelled, remove Google Calendar event
    if (status === 'Cancelled' && appointment.google_event_id) {
      try {
        await meetService.deleteMeeting(appointment.google_event_id);
      } catch (err) {
        console.error('Failed to delete Google Meet for cancelled appointment:', err.message);
      }
    }

    // Inform clients that availability changed
    req.io?.emit('availability_changed');

    res.json({ message: 'Status updated', appointment });
  } catch (error) {
    next(error);
  }
});

// POST /api/admin/appointments/:id/followup — Trigger follow-up workflow (YES)
router.post('/appointments/:id/followup', async (req, res, next) => {
  try {
    const { id } = req.params;

    // Get appointment and client details
    const appointmentResult = await query(
      `SELECT a.*, c.full_name, c.mobile, c.email, c.id as client_id, c.follow_up_count
       FROM appointments a
       JOIN clients c ON a.client_id = c.id
       WHERE a.id = $1`,
      [id]
    );

    if (appointmentResult.rows.length === 0) {
      return res.status(404).json({ error: 'Appointment not found' });
    }

    const appointment = appointmentResult.rows[0];
    const followUpCount = parseInt(appointment.follow_up_count) || 0;

    // Enforce max 3 follow-ups
    if (followUpCount >= 3) {
      return res.status(400).json({ error: 'This client has reached the maximum number of follow-up sessions.' });
    }

    // Mark appointment as requiring follow-up
    await query(
      'UPDATE appointments SET requires_followup = TRUE, status = $1, updated_at = NOW() WHERE id = $2',
      ['Completed', id]
    );

    // Increment follow_up_count on the client
    const newCount = followUpCount + 1;
    await query(
      'UPDATE clients SET follow_up_count = $1, updated_at = NOW() WHERE id = $2',
      [newCount, appointment.client_id]
    );

    // Create Razorpay order for follow-up session (₹499)
    const order = await paymentService.createOrder({
      amount: 499 * 100, // paise
      receipt: 'followup_' + id + '_' + Date.now(),
      notes: {
        clientId: appointment.client_id,
        clientName: appointment.full_name,
        consultationType: 'Follow-up ' + newCount,
      },
    });

    // Store payment record
    await query(
      `INSERT INTO payments (appointment_id, client_id, amount, status, is_followup)
       VALUES ($1, $2, 499, 'pending', TRUE)`,
      [id, appointment.client_id]
    );

    // Send notifications
    const notifPayload = {
      clientName: appointment.full_name,
      email: appointment.email,
      mobile: appointment.mobile,
      paymentLink: `${process.env.FRONTEND_URL || 'http://localhost:5173'}/payment?order_id=${order.id}`,
    };

    Promise.allSettled([
      emailService.sendFollowupPaymentRequest(notifPayload),
      smsService.sendFollowupPaymentRequest(notifPayload),
      whatsappService.sendFollowupPaymentRequest(notifPayload),
    ]).then(results => {
      results.forEach((r, i) => {
        if (r.status === 'rejected') {
          console.error(`Follow-up notification ${i} failed:`, r.reason);
        }
      });
    });

    res.json({
      message: 'Follow-up session initiated. Razorpay order created.',
      razorpayOrderId: order.id,
      followUpCount: newCount,
    });
  } catch (error) {
    next(error);
  }
});

// POST /api/admin/appointments/:id/complete — Mark as complete, NO follow-up
router.post('/appointments/:id/complete', async (req, res, next) => {
  try {
    const { id } = req.params;

    // Update appointment
    await query(
      `UPDATE appointments SET status = 'Completed', requires_followup = FALSE, updated_at = NOW() WHERE id = $1`,
      [id]
    );

    // Archive client
    const appointment = await query('SELECT client_id FROM appointments WHERE id = $1', [id]);
    if (appointment.rows.length > 0) {
      // Check if client has any upcoming appointments
      const upcomingResult = await query(
        `SELECT COUNT(*) as count FROM appointments 
         WHERE client_id = $1 AND status = 'Booked' AND id != $2`,
        [appointment.rows[0].client_id, id]
      );

      if (parseInt(upcomingResult.rows[0].count) === 0) {
        await query(
          'UPDATE clients SET is_archived = TRUE, updated_at = NOW() WHERE id = $1',
          [appointment.rows[0].client_id]
        );
      }
    }

    res.json({ message: 'Treatment marked as completed. Client archived.' });
  } catch (error) {
    next(error);
  }
});

// GET /api/admin/clients — List clients with search
router.get('/clients', async (req, res, next) => {
  try {
    const { search, archived, page = 1, limit = 20 } = req.query;
    const offset = (page - 1) * limit;

    let whereClause = '';
    const params = [];
    let paramCount = 0;

    if (search) {
      paramCount++;
      whereClause = `WHERE (c.full_name ILIKE $${paramCount} OR c.email ILIKE $${paramCount} OR c.mobile ILIKE $${paramCount})`;
      params.push(`%${search}%`);
    }

    if (archived !== undefined) {
      paramCount++;
      whereClause += whereClause ? ` AND c.is_archived = $${paramCount}` : `WHERE c.is_archived = $${paramCount}`;
      params.push(archived === 'true');
    }

    paramCount++;
    params.push(parseInt(limit));
    paramCount++;
    params.push(parseInt(offset));

    const result = await query(
      `SELECT c.*,
              (SELECT COUNT(*) FROM appointments WHERE client_id = c.id) as total_sessions,
              (SELECT COUNT(*) FROM appointments WHERE client_id = c.id AND status = 'Completed') as completed_sessions
       FROM clients c
       ${whereClause}
       ORDER BY c.created_at DESC
       LIMIT $${paramCount - 1} OFFSET $${paramCount}`,
      params
    );

    res.json({ clients: result.rows });
  } catch (error) {
    next(error);
  }
});

// GET /api/admin/clients/:id — Client detail
router.get('/clients/:id', async (req, res, next) => {
  try {
    const { id } = req.params;

    const clientResult = await query('SELECT * FROM clients WHERE id = $1', [id]);
    if (clientResult.rows.length === 0) {
      return res.status(404).json({ error: 'Client not found' });
    }

    const appointmentsResult = await query(
      `SELECT a.*, p.status as payment_status, p.amount
       FROM appointments a
       LEFT JOIN payments p ON a.id = p.appointment_id AND p.is_followup = FALSE
       WHERE a.client_id = $1
       ORDER BY a.appointment_date DESC`,
      [id]
    );

    const notesResult = await query(
      'SELECT * FROM notes WHERE client_id = $1 ORDER BY created_at DESC',
      [id]
    );

    res.json({
      client: clientResult.rows[0],
      appointments: appointmentsResult.rows,
      notes: notesResult.rows,
    });
  } catch (error) {
    next(error);
  }
});

// POST /api/admin/notes — Add a counselor note
router.post('/notes', noteValidation, async (req, res, next) => {
  try {
    const { content, appointmentId, clientId } = req.body;

    const result = await query(
      'INSERT INTO notes (appointment_id, client_id, content) VALUES ($1, $2, $3) RETURNING *',
      [appointmentId, clientId, content]
    );

    res.status(201).json({ note: result.rows[0] });
  } catch (error) {
    next(error);
  }
});

// GET /api/admin/earnings — Earnings analytics
router.get('/earnings', async (req, res, next) => {
  try {
    const { period = 'monthly' } = req.query;

    let groupBy, dateFormat;
    if (period === 'daily') {
      groupBy = "DATE(p.created_at)";
      dateFormat = "TO_CHAR(DATE(p.created_at), 'YYYY-MM-DD')";
    } else if (period === 'weekly') {
      groupBy = "DATE_TRUNC('week', p.created_at)";
      dateFormat = "TO_CHAR(DATE_TRUNC('week', p.created_at), 'YYYY-MM-DD')";
    } else {
      groupBy = "DATE_TRUNC('month', p.created_at)";
      dateFormat = "TO_CHAR(DATE_TRUNC('month', p.created_at), 'YYYY-MM')";
    }

    const result = await query(
      `SELECT ${dateFormat} as period, 
              SUM(amount) as total, 
              SUM(CASE WHEN is_followup = FALSE THEN amount ELSE 0 END) as initial_total,
              SUM(CASE WHEN is_followup = TRUE THEN amount ELSE 0 END) as followup_total,
              COUNT(*) as count
       FROM payments p
       WHERE p.status = 'completed'
       GROUP BY ${groupBy}
       ORDER BY ${groupBy} DESC
       LIMIT 12`
    );

    const totalResult = await query(
      `SELECT COALESCE(SUM(amount), 0) as total, 
              COALESCE(SUM(CASE WHEN is_followup = FALSE THEN amount ELSE 0 END), 0) as initial_total,
              COALESCE(SUM(CASE WHEN is_followup = TRUE THEN amount ELSE 0 END), 0) as followup_total,
              COUNT(*) as count 
       FROM payments WHERE status = 'completed'`
    );

    res.json({
      earnings: result.rows,
      summary: totalResult.rows[0],
    });
  } catch (error) {
    next(error);
  }
});

// GET /api/admin/payments — Payment history
router.get('/payments', async (req, res, next) => {
  try {
    const { status, page = 1, limit = 20 } = req.query;
    const offset = (page - 1) * limit;

    let whereClause = '';
    const params = [];
    let paramCount = 0;

    if (status) {
      paramCount++;
      whereClause = `WHERE p.status = $${paramCount}`;
      params.push(status);
    }

    paramCount++;
    params.push(parseInt(limit));
    paramCount++;
    params.push(parseInt(offset));

    const result = await query(
      `SELECT p.*, c.full_name, c.email, c.mobile
       FROM payments p
       JOIN clients c ON p.client_id = c.id
       ${whereClause}
       ORDER BY p.created_at DESC
       LIMIT $${paramCount - 1} OFFSET $${paramCount}`,
      params
    );

    res.json({ payments: result.rows });
  } catch (error) {
    next(error);
  }
});

// ===== Transcripts & Settings =====

// GET /api/admin/transcripts/:appointmentId
router.get('/transcripts/:appointmentId', async (req, res, next) => {
  try {
    const result = await query(
      'SELECT * FROM transcripts WHERE appointment_id = $1 ORDER BY timestamp ASC',
      [req.params.appointmentId]
    );

    // Decrypt the transcripts
    const transcripts = result.rows.map(row => ({
      ...row,
      original_text: decrypt(row.original_text),
      translated_text: decrypt(row.translated_text)
    }));

    res.json({ transcripts });
  } catch (error) {
    next(error);
  }
});

// DELETE /api/admin/transcripts/:appointmentId
router.delete('/transcripts/:appointmentId', async (req, res, next) => {
  try {
    await query('DELETE FROM transcripts WHERE appointment_id = $1', [req.params.appointmentId]);
    res.json({ message: 'Transcripts deleted successfully' });
  } catch (error) {
    next(error);
  }
});

// GET /api/admin/settings
router.get('/settings', async (req, res, next) => {
  try {
    const result = await query('SELECT key, value FROM settings');
    const settings = {};
    result.rows.forEach(r => settings[r.key] = r.value);
    res.json({ settings });
  } catch (error) {
    next(error);
  }
});

// PUT /api/admin/settings/:key
router.put('/settings/:key', async (req, res, next) => {
  try {
    const { value } = req.body;
    await query(
      'INSERT INTO settings (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = $2',
      [req.params.key, value]
    );
    res.json({ message: 'Setting updated successfully' });
  } catch (error) {
    next(error);
  }
});

module.exports = router;
