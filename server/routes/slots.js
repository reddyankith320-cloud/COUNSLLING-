const express = require('express');
const router = express.Router();
const { authenticate } = require('../middleware/auth');
const dateService = require('../services/slotService'); // Keep the same filename to avoid changing requires everywhere

// Public: Get unavailable dates for a month
router.get('/unavailable', async (req, res, next) => {
  try {
    const { year, month } = req.query;
    if (!year || !month) {
      return res.status(400).json({ error: 'Year and month parameters are required' });
    }
    const data = await dateService.getUnavailableDates(parseInt(year), parseInt(month));
    res.json(data);
  } catch (error) {
    next(error);
  }
});

// GET /api/slots/time-slots — Get the predefined time slots (public)
router.get('/time-slots', (req, res) => {
  res.json({ timeSlots: dateService.getTimeSlots() });
});

// GET /api/slots/available-slots — Get available slots for a date (public)
router.get('/available-slots', async (req, res, next) => {
  try {
    const { date } = req.query;
    if (!date) return res.status(400).json({ error: 'Date parameter is required' });
    const slots = await dateService.getAvailableSlots(date);
    res.json({ date, slots });
  } catch (error) {
    next(error);
  }
});

// Admin routes below require auth
router.use(authenticate);

// GET /api/slots/blocked
router.get('/blocked', async (req, res, next) => {
  try {
    const blocked = await dateService.getBlockedDates();
    res.json({ blockedDates: blocked });
  } catch (error) {
    next(error);
  }
});

// POST /api/slots/block
router.post('/block', async (req, res, next) => {
  try {
    const { date, reason } = req.body;
    const result = await dateService.blockDate(date, reason);
    req.io?.emit('availability_changed');
    res.json({ message: 'Date blocked', blockedDate: result.rows[0] });
  } catch (error) {
    next(error);
  }
});

// POST /api/slots/unblock
router.post('/unblock', async (req, res, next) => {
  try {
    const { date } = req.body;
    const result = await dateService.unblockDate(date);
    req.io?.emit('availability_changed');
    res.json({ message: 'Date unblocked', blockedDate: result.rows[0] });
  } catch (error) {
    next(error);
  }
});

// GET /api/slots/holidays
router.get('/holidays', async (req, res, next) => {
  try {
    const holidays = await dateService.getHolidays();
    res.json({ holidays });
  } catch (error) {
    next(error);
  }
});

// POST /api/slots/holidays
router.post('/holidays', async (req, res, next) => {
  try {
    const { date, reason } = req.body;
    const result = await dateService.addHoliday(date, reason);
    req.io?.emit('availability_changed');
    res.json({ message: 'Holiday added', holiday: result.rows[0] });
  } catch (error) {
    next(error);
  }
});

// DELETE /api/slots/holidays/:id
router.delete('/holidays/:id', async (req, res, next) => {
  try {
    const result = await dateService.removeHoliday(req.params.id);
    req.io?.emit('availability_changed');
    res.json({ message: 'Holiday removed', holiday: result.rows[0] });
  } catch (error) {
    next(error);
  }
});

// GET /api/slots/blocked-slots?date=YYYY-MM-DD  (omit date for all upcoming)
router.get('/blocked-slots', async (req, res, next) => {
  try {
    const { date } = req.query;
    const blockedSlots = date
      ? await dateService.getBlockedSlotsForDate(date)
      : await dateService.getAllBlockedSlots();
    res.json({ blockedSlots });
  } catch (error) {
    next(error);
  }
});

// POST /api/slots/block-slot
router.post('/block-slot', async (req, res, next) => {
  try {
    const { date, startTime, reason } = req.body;
    if (!date || !startTime) return res.status(400).json({ error: 'Date and startTime are required' });
    const slot = dateService.getTimeSlots().find(s => s.startTime === startTime);
    if (!slot) return res.status(400).json({ error: 'Unknown time slot' });
    const result = await dateService.blockSlot(date, slot.startTime, slot.endTime, reason);
    req.io?.emit('availability_changed');
    res.json({ message: 'Slot blocked', blockedSlot: result.rows[0] });
  } catch (error) {
    next(error);
  }
});

// DELETE /api/slots/unblock-slot/:id
router.delete('/unblock-slot/:id', async (req, res, next) => {
  try {
    const result = await dateService.unblockSlot(req.params.id);
    req.io?.emit('availability_changed');
    res.json({ message: 'Slot unblocked', blockedSlot: result.rows[0] });
  } catch (error) {
    next(error);
  }
});

module.exports = router;
