const express = require('express');
const router = express.Router();
const { query } = require('../config/database');
const { authenticate } = require('../middleware/auth');

// All export routes require authentication
router.use(authenticate);

// GET /api/export/excel — Export appointments data as JSON (frontend handles Excel conversion)
router.get('/excel', async (req, res, next) => {
  try {
    const { startDate, endDate, status } = req.query;

    let whereClause = '';
    const params = [];
    let paramCount = 0;

    if (startDate) {
      paramCount++;
      whereClause = `WHERE a.appointment_date >= $${paramCount}`;
      params.push(startDate);
    }

    if (endDate) {
      paramCount++;
      whereClause += whereClause ? ` AND a.appointment_date <= $${paramCount}` : `WHERE a.appointment_date <= $${paramCount}`;
      params.push(endDate);
    }

    if (status) {
      paramCount++;
      whereClause += whereClause ? ` AND a.status = $${paramCount}` : `WHERE a.status = $${paramCount}`;
      params.push(status);
    }

    const result = await query(
      `SELECT a.id, c.full_name, c.age, c.gender, c.mobile, c.email,
              a.appointment_date, a.status,
              a.problem_description, a.meet_join_url,
              p.amount, p.status as payment_status, p.created_at as payment_date
       FROM appointments a
       JOIN clients c ON a.client_id = c.id
       LEFT JOIN payments p ON a.id = p.appointment_id AND p.is_followup = FALSE
       ${whereClause}
       ORDER BY a.appointment_date DESC`,
      params
    );

    res.json({ data: result.rows });
  } catch (error) {
    next(error);
  }
});

// GET /api/export/pdf — Same data for PDF generation
router.get('/pdf', async (req, res, next) => {
  try {
    const { startDate, endDate } = req.query;

    let whereClause = '';
    const params = [];
    let paramCount = 0;

    if (startDate) {
      paramCount++;
      whereClause = `WHERE a.appointment_date >= $${paramCount}`;
      params.push(startDate);
    }

    if (endDate) {
      paramCount++;
      whereClause += whereClause ? ` AND a.appointment_date <= $${paramCount}` : `WHERE a.appointment_date <= $${paramCount}`;
      params.push(endDate);
    }

    const result = await query(
      `SELECT a.id, c.full_name, c.age, c.mobile, c.email,
              a.appointment_date, a.status,
              p.amount, p.status as payment_status
       FROM appointments a
       JOIN clients c ON a.client_id = c.id
       LEFT JOIN payments p ON a.id = p.appointment_id AND p.is_followup = FALSE
       ${whereClause}
       ORDER BY a.appointment_date DESC`,
      params
    );

    res.json({ data: result.rows });
  } catch (error) {
    next(error);
  }
});

module.exports = router;
