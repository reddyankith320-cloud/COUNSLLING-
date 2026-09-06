const { getCalendarClient } = require('../config/google');
require('dotenv').config();

class MeetService {
  /**
   * Create a Google Calendar event with a Google Meet link
   * @param {Object} options
   * @param {string} options.summary - Event title
   * @param {string} options.description - Event description
   * @param {string} options.startTime - ISO 8601 datetime string
   * @param {number} options.duration - Duration in minutes
   * @param {string} options.attendeeEmail - Client email to add as attendee
   * @returns {Object} { eventId, meetLink, calendarLink }
   */
  async createMeeting({ summary, description, startTime, duration = 60, attendeeEmail }) {
    try {
      const calendar = await getCalendarClient();

      if (!calendar) {
        console.warn('⚠️ Google Calendar not authorized. Returning mock data.');
        return this._getMockMeeting();
      }

      const startDate = new Date(startTime);
      const endDate = new Date(startDate.getTime() + duration * 60 * 1000);

      const counselorEmail = process.env.GOOGLE_CALENDAR_ID || 'primary';

      const event = {
        summary: summary || 'Counseling Session - Adulla Sridevi Reddy',
        description: description || 'Confidential counseling session with Adulla Sridevi Reddy, Master of Social Work (MSW) - Postgraduate Degree.',
        start: {
          dateTime: startDate.toISOString(),
          timeZone: 'Asia/Kolkata',
        },
        end: {
          dateTime: endDate.toISOString(),
          timeZone: 'Asia/Kolkata',
        },
        attendees: attendeeEmail ? [{ email: attendeeEmail }] : [],
        conferenceData: {
          createRequest: {
            requestId: `meet-${Date.now()}-${Math.random().toString(36).substring(2, 8)}`,
            conferenceSolutionKey: {
              type: 'hangoutsMeet',
            },
          },
        },
        reminders: {
          useDefault: false,
          overrides: [
            { method: 'email', minutes: 60 },
            { method: 'popup', minutes: 15 },
          ],
        },
      };

      const response = await calendar.events.insert({
        calendarId: counselorEmail === 'primary' ? 'primary' : counselorEmail,
        resource: event,
        conferenceDataVersion: 1,
        sendUpdates: 'all', // Send email invitations to attendees
      });

      const createdEvent = response.data;
      const meetLink = createdEvent.conferenceData?.entryPoints?.find(
        (ep) => ep.entryPointType === 'video'
      )?.uri;

      return {
        eventId: createdEvent.id,
        meetLink: meetLink || createdEvent.hangoutLink || '',
        calendarLink: createdEvent.htmlLink || '',
      };
    } catch (error) {
      console.error('Google Meet creation failed:', error.message);

      // Return mock data in development if Google is not configured
      if (process.env.NODE_ENV === 'development') {
        return this._getMockMeeting();
      }
      throw new Error('Failed to create Google Meet meeting');
    }
  }

  /**
   * Delete a Google Calendar event
   * @param {string} eventId - Google Calendar event ID
   */
  async deleteMeeting(eventId) {
    try {
      const calendar = await getCalendarClient();
      if (!calendar) return;

      const calendarId = process.env.GOOGLE_CALENDAR_ID || 'primary';
      await calendar.events.delete({
        calendarId: calendarId === 'primary' ? 'primary' : calendarId,
        eventId,
        sendUpdates: 'all',
      });
      console.log(`Google Calendar event ${eventId} deleted.`);
    } catch (error) {
      console.error('Failed to delete Google Calendar event:', error.message);
    }
  }

  /**
   * Generate mock meeting data for development
   */
  _getMockMeeting() {
    const mockId = `mock_${Date.now()}_${Math.random().toString(36).substring(2, 8)}`;
    console.log(`[DEV] Mock Google Meet created: ${mockId}`);
    return {
      eventId: mockId,
      meetLink: `https://meet.google.com/${mockId.substring(0, 12)}`,
      calendarLink: `https://calendar.google.com/event?eid=${mockId}`,
    };
  }
}

module.exports = new MeetService();
