const { body, param, query, validationResult } = require('express-validator');

// Middleware to check validation results
const validate = (req, res, next) => {
  const errors = validationResult(req);
  if (!errors.isEmpty()) {
    return res.status(400).json({
      error: 'Validation failed',
      details: errors.array().map(err => ({
        field: err.path,
        message: err.msg,
      })),
    });
  }
  next();
};

// Booking form validation
const bookingValidation = [
  body('fullName')
    .trim()
    .notEmpty().withMessage('Full name is required')
    .isLength({ min: 2, max: 255 }).withMessage('Name must be 2-255 characters'),
  body('age')
    .isInt({ min: 1, max: 120 }).withMessage('Age must be between 1 and 120'),
  body('gender')
    .optional({ values: 'falsy' }) // the form sends "" when nothing is selected
    .isIn(['male', 'female', 'other', 'prefer_not_to_say']).withMessage('Invalid gender'),
  body('mobile')
    .trim()
    .notEmpty().withMessage('Mobile number is required')
    .matches(/^[6-9]\d{9}$/).withMessage('Invalid Indian mobile number'),
  body('email')
    .trim()
    .notEmpty().withMessage('Email is required')
    .isEmail().withMessage('Invalid email address')
    .normalizeEmail(),
  body('problemDescription')
    .trim()
    .notEmpty().withMessage('Problem description is required')
    .isLength({ min: 10, max: 5000 }).withMessage('Description must be 10-5000 characters'),
  body('appointmentDate')
    .notEmpty().withMessage('Appointment date is required')
    .matches(/^\d{4}-\d{2}-\d{2}$/).withMessage('Invalid date format (expected YYYY-MM-DD)'),
  body('startTime')
    .matches(/^\d{2}:\d{2}$/).withMessage('Invalid start time'),
  body('endTime')
    .matches(/^\d{2}:\d{2}$/).withMessage('Invalid end time'),
  validate,
];

// Login validation
const loginValidation = [
  body('email')
    .trim()
    .notEmpty().withMessage('Email is required')
    .isEmail().withMessage('Invalid email address')
    .normalizeEmail(),
  body('password')
    .notEmpty().withMessage('Password is required')
    .isLength({ min: 6 }).withMessage('Password must be at least 6 characters'),
  validate,
];

// Note validation
const noteValidation = [
  body('content')
    .trim()
    .notEmpty().withMessage('Note content is required')
    .isLength({ max: 10000 }).withMessage('Note too long'),
  body('appointmentId')
    .isInt().withMessage('Valid appointment ID is required'),
  body('clientId')
    .isInt().withMessage('Valid client ID is required'),
  validate,
];

module.exports = {
  validate,
  bookingValidation,
  loginValidation,
  noteValidation,
};
