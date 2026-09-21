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
function getAuthUrl(state) {
  const oAuth2Client = createOAuth2Client();
  return oAuth2Client.generateAuthUrl({
    access_type: 'offline',
    prompt: 'consent',
    scope: SCOPES,
    state,
  });
}

/**
 * Exchange authorization code for tokens and store them
 */
async function storeTokenFromCode(code) {
  const oAuth2Client = createOAuth2Client();
  const { tokens } = await oAuth2Client.getToken(code);
  try {
    fs.writeFileSync(TOKEN_PATH, JSON.stringify(tokens, null, 2));
    console.log('✅ Google OAuth tokens stored successfully.');
  } catch (err) {
    // Read-only filesystem on some hosts — the refresh token still works via env var
    console.warn('⚠️ Could not write .google-token.json:', err.message);
  }
  return tokens;
}

/**
 * Load stored tokens. Hosted platforms (Render, Railway…) wipe the disk on
 * every deploy, so a GOOGLE_REFRESH_TOKEN env var takes precedence over the
 * local token file.
 */
function loadStoredTokens() {
  if (process.env.GOOGLE_REFRESH_TOKEN) {
    return { refresh_token: process.env.GOOGLE_REFRESH_TOKEN };
  }
  if (fs.existsSync(TOKEN_PATH)) {
    return JSON.parse(fs.readFileSync(TOKEN_PATH, 'utf8'));
  }
  return null;
}

/**
 * Get an authenticated OAuth2 client, auto-refreshing tokens if needed
 */
async function getAuthenticatedClient() {
  const tokens = loadStoredTokens();
  if (!tokens) {
    return null; // Not yet authorized — needs one-time consent
  }

  const oAuth2Client = createOAuth2Client();
  oAuth2Client.setCredentials(tokens);

  // Auto-refresh: persist rotated tokens when we have a writable token file
  oAuth2Client.on('tokens', (newTokens) => {
    if (process.env.GOOGLE_REFRESH_TOKEN) return; // env-var mode: nothing to persist
    try {
      const existing = fs.existsSync(TOKEN_PATH) ? JSON.parse(fs.readFileSync(TOKEN_PATH, 'utf8')) : {};
      fs.writeFileSync(TOKEN_PATH, JSON.stringify({ ...existing, ...newTokens }, null, 2));
      console.log('🔄 Google OAuth tokens refreshed and stored.');
    } catch (err) {
      console.warn('⚠️ Could not persist refreshed Google tokens:', err.message);
    }
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
