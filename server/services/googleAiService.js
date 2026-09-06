const speech = require('@google-cloud/speech');
const { TranslationServiceClient } = require('@google-cloud/translate');
const textToSpeech = require('@google-cloud/text-to-speech');
require('dotenv').config();

// Map the custom environment variable to what Google Cloud SDK expects for default constructors
if (process.env.GOOGLE_PROJECT_ID && !process.env.GCLOUD_PROJECT) {
  process.env.GCLOUD_PROJECT = process.env.GOOGLE_PROJECT_ID;
}

// Initialize clients using Application Default Credentials (ADC)
let speechClient = null;
let translationClient = null;
let ttsClient = null;

try {
  speechClient = new speech.SpeechClient();
  translationClient = new TranslationServiceClient();
  ttsClient = new textToSpeech.TextToSpeechClient();
  console.log('✅ Google Cloud AI Services initialized via Application Default Credentials (ADC)');
} catch (err) {
  console.warn('⚠️ Google Cloud ADC init failed, using mock AI:', err.message);
}

/**
 * Creates a Speech-to-Text streaming recognize stream.
 * @param {string} primaryLanguage - The expected primary language code (e.g., 'te-IN')
 * @param {Array<string>} alternateLanguages - Alternate languages (e.g., ['en-US', 'hi-IN'])
 * @param {Function} onData - Callback when transcription is available (text, isFinal, language)
 */
function createSpeechStream(primaryLanguage = 'te-IN', alternateLanguages = ['en-US', 'hi-IN'], onData) {
  if (!speechClient) {
    // MOCK MODE
    console.log('[MOCK] Speech stream created.');
    let mockInterval;
    return {
      write: (audioChunk) => {
        // Simulate speech recognition randomly in mock mode
        if (Math.random() > 0.95) {
          onData('This is a simulated transcription.', true, primaryLanguage);
        }
      },
      end: () => {
        clearInterval(mockInterval);
        console.log('[MOCK] Speech stream ended.');
      },
      destroy: () => {
        clearInterval(mockInterval);
      }
    };
  }

  const request = {
    config: {
      encoding: 'LINEAR16',
      sampleRateHertz: 16000,
      languageCode: primaryLanguage,
      alternativeLanguageCodes: alternateLanguages,
      enableAutomaticPunctuation: true,
      useEnhanced: true,
      model: 'latest_long',
    },
    interimResults: true,
  };

  const recognizeStream = speechClient
    .streamingRecognize(request)
    .on('error', (err) => {
      console.error('Speech API Error:', err);
    })
    .on('data', (data) => {
      if (data.results[0] && data.results[0].alternatives[0]) {
        const text = data.results[0].alternatives[0].transcript;
        const isFinal = data.results[0].isFinal;
        const detectedLanguage = data.results[0].languageCode || primaryLanguage;
        onData(text, isFinal, detectedLanguage);
      }
    });

  return recognizeStream;
}

/**
 * Translates text to the target language.
 * @param {string} text - Text to translate
 * @param {string} targetLanguage - Target language code (e.g., 'te' for Telugu)
 * @returns {Promise<string>} Translated text
 */
async function translateText(text, targetLanguage) {
  if (!text) return '';
  if (!translationClient) {
    // MOCK MODE
    return `[Translated to ${targetLanguage}]: ${text}`;
  }

  try {
    const projectId = process.env.GOOGLE_PROJECT_ID;
    const location = process.env.GOOGLE_TRANSLATE_LOCATION || 'global';
    
    // Fallback if projectId is not defined but creds are present
    if (!projectId) {
      console.warn('GOOGLE_PROJECT_ID is missing. Translation might fail.');
    }

    const request = {
      parent: `projects/${projectId}/locations/${location}`,
      contents: [text],
      mimeType: 'text/plain', 
      targetLanguageCode: targetLanguage.split('-')[0], // 'te-IN' -> 'te'
    };

    const [response] = await translationClient.translateText(request);
    return response.translations[0].translatedText;
  } catch (error) {
    console.error('Translation Error:', error);
    return `[Translation Error]: ${text}`;
  }
}

/**
 * Converts text to speech audio buffer.
 * @param {string} text - Text to synthesize
 * @param {string} languageCode - Target language (e.g., 'te-IN')
 * @returns {Promise<Buffer>} Audio buffer (MP3)
 */
async function synthesizeSpeech(text, languageCode) {
  if (!text) return null;
  if (!ttsClient) {
    // MOCK MODE
    // Return a tiny silent mp3 buffer or just null
    return null;
  }

  try {
    const request = {
      input: { text: text },
      // Select the language and SSML voice gender (optional)
      voice: { languageCode: languageCode, name: `${languageCode}-Standard-A` }, 
      // select the type of audio encoding
      audioConfig: { audioEncoding: 'MP3' },
    };

    const [response] = await ttsClient.synthesizeSpeech(request);
    return response.audioContent;
  } catch (error) {
    console.error('TTS Error:', error);
    return null;
  }
}

module.exports = {
  createSpeechStream,
  translateText,
  synthesizeSpeech
};
