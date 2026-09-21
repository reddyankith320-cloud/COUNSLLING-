import api from '../services/api';

const to12h = (t) => {
  if (!t) return '';
  const [h, m] = String(t).substring(0, 5).split(':');
  const hour = parseInt(h, 10);
  return `${hour % 12 || 12}:${m} ${hour >= 12 ? 'PM' : 'AM'}`;
};

const fmtDate = (d) =>
  d ? new Date(d).toLocaleDateString('en-IN', { year: 'numeric', month: 'short', day: 'numeric' }) : '';

/**
 * Downloads all appointments (optionally filtered) as an .xlsx workbook.
 * The xlsx library is loaded on demand so it doesn't bloat the admin bundle.
 */
export async function exportAppointmentsExcel(filters = {}) {
  const [{ data }, XLSX] = await Promise.all([
    api.get('/export/excel', { params: filters }),
    import('xlsx'),
  ]);

  const rows = (data.data || []).map((r) => ({
    'Appt ID': r.id,
    'Client': r.full_name,
    'Age': r.age,
    'Gender': r.gender || '',
    'Mobile': r.mobile,
    'Email': r.email,
    'Date': fmtDate(r.appointment_date),
    'Time': r.start_time ? `${to12h(r.start_time)} - ${to12h(r.end_time)}` : '',
    'Status': r.status,
    'Type': r.consultation_type || '',
    'Amount (₹)': r.amount != null ? Number(r.amount) : '',
    'Payment': r.payment_status || '',
    'Paid On': fmtDate(r.payment_date),
    'Meet Link': r.meet_join_url || '',
    'Concern': r.problem_description || '',
  }));

  const ws = XLSX.utils.json_to_sheet(rows);
  ws['!cols'] = [6, 22, 5, 10, 13, 26, 14, 20, 12, 16, 10, 11, 14, 36, 60].map((w) => ({ wch: w }));

  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, 'Appointments');

  const stamp = new Date().toISOString().slice(0, 10);
  XLSX.writeFile(wb, `FindMyPeace_Appointments_${stamp}.xlsx`);
  return rows.length;
}
