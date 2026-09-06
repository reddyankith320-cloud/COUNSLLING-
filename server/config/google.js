const { google } = require('googleapis');
const fs = require('fs');
const path = require('path');
require('dotenv').config();

const TOKEN_PATH = path.join(__dirname, '..', '.google-token.json');

const SCOPES = ['https://www.googleapis.com/auth/calendar'];

/**
 * Create an OAuth2 client
 */
function createOAuth2Client() {
  return new google.auth.OAuth2(
    process.env.GOOGLE_CLIENT_ID,
    process.env.GOOGLE_CLIENT_SECRET,
    process.env.GOOGLE_REDIRECT_URI || 'http://localhost:5000/api/auth/google/callback'
  );
}

/**
 * Get the authorization URL for the one-time consent flow
 */
function getAuthUrl() {
  const oAuth2Client = createOAuth2Client();
  return oAuth2Client.generateAuthUrl({
    access_type: 'offline',
    prompt: 'consent',
    scope: SCOPES,
  });
}

/**
 * Exchange authorization code for tokens and store them
 */
async function storeTokenFromCode(code) {
  const oAuth2Client = createOAuth2Client();
  const { tokens } = await oAuth2Client.getToken(code);
  fs.writeFileSync(TOKEN_PATH, JSON.stringify(tokens, null, 2));
  console.log('✅ Google OAuth tokens stored successfully.');
  return tokens;
}

/**
 * Get an authenticated OAuth2 client, auto-refreshing tokens if needed
 */
async function getAuthenticatedClient() {
  const oAuth2Client = createOAuth2Client();

  if (!fs.existsSync(TOKEN_PATH)) {
    return null; // Not yet authorized — needs one-time consent
  }

  const tokens = JSON.parse(fs.readFileSync(TOKEN_PATH, 'utf8'));
  oAuth2Client.setCredentials(tokens);

  // Auto-refresh: listen for new tokens and persist them
  oAuth2Client.on('tokens', (newTokens) => {
    const existing = JSON.parse(fs.readFileSync(TOKEN_PATH, 'utf8'));
    const merged = { ...existing, ...newTokens };
    fs.writeFileSync(TOKEN_PATH, JSON.stringify(merged, null, 2));
    console.log('🔄 Google OAuth tokens refreshed and stored.');
  });

  return oAuth2Client;
}

/**
 * Get an authenticated Google Calendar API client
 */
async function getCalendarClient() {
  const auth = await getAuthenticatedClient();
  if (!auth) return null;
  return google.calendar({ version: 'v3', auth });
}

module.exports = {
  getAuthUrl,
  storeTokenFromCode,
  getAuthenticatedClient,
  getCalendarClient,
  createOAuth2Client,
};
