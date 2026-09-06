const { createSpeechStream, translateText, synthesizeSpeech } = require('../services/googleAiService');
const { query } = require('../config/database');
const { encrypt } = require('../utils/encryption');

// Store active streams per socket to allow cleanup
const activeStreams = new Map();

function setupTranslationSockets(io) {
  const translationNamespace = io.of('/translation');

  translationNamespace.on('connection', (socket) => {
    console.log(`🔌 New translation socket connected: ${socket.id}`);

    let currentAppointmentId = null;
    let currentUserRole = null; // 'counselor' or 'client'
    let currentSpeechStream = null;
    let primaryLang = 'te-IN';
    let targetLang = 'en-US';

    socket.on('join-room', async ({ appointmentId, role, clientLanguage }) => {
      currentAppointmentId = appointmentId;
      currentUserRole = role;
      
      // Counselor speaks Telugu, Client speaks their language
      if (role === 'counselor') {
        primaryLang = 'te-IN';
        targetLang = clientLanguage || 'en-US';
      } else {
        primaryLang = clientLanguage || 'en-US';
        targetLang = 'te-IN';
      }

      socket.join(`appt_${appointmentId}`);
      console.log(`${role} joined translation room for appt ${appointmentId}. Lang: ${primaryLang} -> ${targetLang}`);
    });

    socket.on('start-stream', () => {
      console.log(`🎤 Starting audio stream for ${socket.id}`);
      
      if (currentSpeechStream) {
        currentSpeechStream.destroy();
      }

      // Initialize GCP Speech Stream
      currentSpeechStream = createSpeechStream(primaryLang, [targetLang], async (text, isFinal, detectedLang) => {
        // Emit interim results directly back to the speaker for live feedback
        socket.emit('interim-transcription', { text, isFinal: false });

        if (isFinal) {
          try {
            // 1. Translate the final text
            const translatedText = await translateText(text, targetLang);
            
            // 2. Synthesize audio for the translated text
            const audioBuffer = await synthesizeSpeech(translatedText, targetLang);

            // 3. Broadcast the result to everyone in the room
            const payload = {
              speakerId: socket.id,
              role: currentUserRole,
              originalText: text,
              detectedLanguage: detectedLang,
              translatedText: translatedText,
              targetLanguage: targetLang,
              timestamp: new Date().toISOString(),
              audioUrl: audioBuffer ? `data:audio/mp3;base64,${audioBuffer.toString('base64')}` : null
            };

            translationNamespace.to(`appt_${currentAppointmentId}`).emit('final-translation', payload);

            // 4. Store in database if enabled
            if (currentAppointmentId) {
              const settingRes = await query("SELECT value FROM settings WHERE key = 'store_transcripts'");
              const storeEnabled = settingRes.rows.length > 0 && settingRes.rows[0].value === 'true';

              if (storeEnabled) {
                // Encrypt sensitive transcripts
                const encOriginal = encrypt(text);
                const encTranslated = encrypt(translatedText);

                await query(
                  `INSERT INTO transcripts 
                   (appointment_id, speaker, original_text, detected_language, translated_text, target_language)
                   VALUES ($1, $2, $3, $4, $5, $6)`,
                  [currentAppointmentId, currentUserRole, encOriginal, detectedLang, encTranslated, targetLang]
                );
              }
            }
          } catch (err) {
            console.error('Error processing final transcription:', err);
          }
        }
      });

      activeStreams.set(socket.id, currentSpeechStream);
    });

    socket.on('audio-data', (audioBuffer) => {
      // audioBuffer should be Int16Array or Buffer containing raw 16kHz PCM audio
      if (currentSpeechStream) {
        currentSpeechStream.write(audioBuffer);
      }
    });

    socket.on('stop-stream', () => {
      console.log(`🛑 Stopping audio stream for ${socket.id}`);
      if (currentSpeechStream) {
        currentSpeechStream.end();
        currentSpeechStream = null;
        activeStreams.delete(socket.id);
      }
    });

    socket.on('disconnect', () => {
      console.log(`🔌 Translation socket disconnected: ${socket.id}`);
      if (currentSpeechStream) {
        currentSpeechStream.end();
        currentSpeechStream.destroy();
        activeStreams.delete(socket.id);
      }
    });
  });
}

module.exports = { setupTranslationSockets };
