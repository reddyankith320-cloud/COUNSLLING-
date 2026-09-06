const errorHandler = (err, req, res, next) => {
  console.error(`[${new Date().toISOString()}] Error:`, err.message || err);
  if (err.stack) console.error(err.stack);

  // PostgreSQL errors
  if (err.code === '23505') {
    return res.status(409).json({
      error: 'Duplicate entry. This record already exists.',
    });
  }

  if (err.code === '23503') {
    return res.status(400).json({
      error: 'Referenced record not found.',
    });
  }

  if (err.code && err.code.startsWith('42')) {
    // 42xxx = PostgreSQL syntax/table/column errors
    const message = process.env.NODE_ENV === 'production'
      ? 'Database schema error. Please run the migration.'
      : `Database error: ${err.message}`;
    return res.status(500).json({ error: message });
  }

  // JWT errors
  if (err.name === 'JsonWebTokenError') {
    return res.status(401).json({ error: 'Invalid token.' });
  }

  if (err.name === 'TokenExpiredError') {
    return res.status(401).json({ error: 'Token expired.' });
  }

  // Razorpay errors
  if (err.statusCode && err.error) {
    return res.status(err.statusCode).json({
      error: err.error.description || 'Payment processing error.',
    });
  }

  // Default error
  const statusCode = err.statusCode || 500;
  const message = process.env.NODE_ENV === 'production'
    ? 'Internal server error'
    : err.message;

  res.status(statusCode).json({ error: message });
};

module.exports = errorHandler;
