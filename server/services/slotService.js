const { query } = require("../config/database");

const TIME_SLOTS = [
  { startTime: "18:00", endTime: "19:00", display: "6:00 PM - 7:00 PM" },
  { startTime: "19:00", endTime: "20:00", display: "7:00 PM - 8:00 PM" },
  { startTime: "20:00", endTime: "21:00", display: "8:00 PM - 9:00 PM" }
];

class DateService {
  getTimeSlots() {
    return TIME_SLOTS;
  }

  async getAvailableSlots(dateStr) {
    const allSlots = this.getTimeSlots();

    // Check full day blocks
    const fullDayBlock = await query("SELECT id FROM blocked_dates WHERE date = $1", [dateStr]);
    if (fullDayBlock.rows.length > 0) return [];
    
    const holiday = await query("SELECT id FROM holidays WHERE date = $1", [dateStr]);
    if (holiday.rows.length > 0) return [];

    // Check booked slots
    const booked = await query(
      "SELECT start_time FROM appointments WHERE appointment_date = $1 AND status IN ('Booked', 'Completed', 'pending_payment')",
      [dateStr]
    );
    const bookedTimes = booked.rows.map(r => r.start_time.substring(0, 5));

    // Check blocked slots
    const blockedSlots = await query(
      "SELECT start_time FROM blocked_slots WHERE date = $1",
      [dateStr]
    );
    const blockedTimes = blockedSlots.rows.map(r => r.start_time.substring(0, 5));

    return allSlots.map(slot => {
      const isBooked = bookedTimes.includes(slot.startTime);
      const isBlocked = blockedTimes.includes(slot.startTime);
      return {
        ...slot,
        available: !isBooked && !isBlocked
      };
    });
  }

  async getUnavailableDates(year, month) {
    const startDate = `${year}-${month.toString().padStart(2, "0")}-01`;
    const lastDay = new Date(year, month, 0).getDate();
    const endDate = `${year}-${month.toString().padStart(2, "0")}-${lastDay.toString().padStart(2, "0")}`;

    const holidays = await query("SELECT date FROM holidays WHERE date >= $1 AND date <= $2", [startDate, endDate]);
    const blocked = await query("SELECT date FROM blocked_dates WHERE date >= $1 AND date <= $2", [startDate, endDate]);
    
    // Find dates where all slots are booked/blocked
    const slotCounts = await query(`
      SELECT date, COUNT(*) as count FROM (
        SELECT appointment_date as date, start_time FROM appointments 
        WHERE appointment_date >= $1 AND appointment_date <= $2 AND status IN ('Booked', 'Completed', 'pending_payment')
        UNION
        SELECT date, start_time FROM blocked_slots 
        WHERE date >= $1 AND date <= $2
      ) as combined
      GROUP BY date
      HAVING COUNT(*) >= 3
    `, [startDate, endDate]);

    const formatToYYYYMMDD = (d) => {
      const date = new Date(d);
      return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
    };

    const fullyBlocked = [
      ...holidays.rows.map(r => formatToYYYYMMDD(r.date)),
      ...blocked.rows.map(r => formatToYYYYMMDD(r.date))
    ];
    
    const fullyBooked = slotCounts.rows.map(r => formatToYYYYMMDD(r.date));

    const allUnavailable = [...new Set([...fullyBlocked, ...fullyBooked])];
    return { booked: fullyBooked, blocked: fullyBlocked, allUnavailable };
  }

  async isDateAvailable(dateStr) {
    // Legacy support, now we should probably use isSlotAvailable. But for the date itself:
    const fullDayBlock = await query("SELECT id FROM blocked_dates WHERE date = $1", [dateStr]);
    if (fullDayBlock.rows.length > 0) return false;
    
    const holiday = await query("SELECT id FROM holidays WHERE date = $1", [dateStr]);
    if (holiday.rows.length > 0) return false;
    return true;
  }

  async isSlotAvailable(dateStr, startTime) {
    const slots = await this.getAvailableSlots(dateStr);
    const target = slots.find(s => s.startTime === startTime);
    return target ? target.available : false;
  }

  async blockDate(dateStr, reason) {
    return query("INSERT INTO blocked_dates (date, reason) VALUES ($1, $2) ON CONFLICT (date) DO NOTHING RETURNING *", [dateStr, reason]);
  }

  async unblockDate(dateStr) {
    return query("DELETE FROM blocked_dates WHERE date = $1 RETURNING *", [dateStr]);
  }

  async getBlockedDates() {
    const result = await query("SELECT * FROM blocked_dates ORDER BY date");
    return result.rows;
  }

  async getHolidays() {
    const result = await query("SELECT * FROM holidays ORDER BY date");
    return result.rows;
  }

  async addHoliday(date, reason) {
    return query("INSERT INTO holidays (date, reason) VALUES ($1, $2) ON CONFLICT (date) DO NOTHING RETURNING *", [date, reason]);
  }

  async removeHoliday(id) {
    return query("DELETE FROM holidays WHERE id = $1 RETURNING *", [id]);
  }

  async getBlockedSlotsForDate(dateStr) {
    const result = await query("SELECT * FROM blocked_slots WHERE date = $1 ORDER BY start_time", [dateStr]);
    return result.rows;
  }

  async blockSlot(dateStr, startTime, endTime, reason) {
    return query(
      "INSERT INTO blocked_slots (date, start_time, end_time, reason) VALUES ($1, $2, $3, $4) ON CONFLICT (date, start_time) DO NOTHING RETURNING *",
      [dateStr, startTime, endTime, reason]
    );
  }

  async unblockSlot(id) {
    return query("DELETE FROM blocked_slots WHERE id = $1 RETURNING *", [id]);
  }
}

module.exports = new DateService();
