const dateService = require('../services/slotService');

async function test() {
  try {
    console.log('Testing getUnavailableDates...');
    const result = await dateService.getUnavailableDates(2026, 7);
    console.log('Result:', result);
    process.exit(0);
  } catch (err) {
    console.error('Test failed with error:', err);
    process.exit(1);
  }
}

test();
