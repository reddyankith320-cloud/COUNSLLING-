const speech = require('@google-cloud/speech');
const { TranslationServiceClient } = require('@google-cloud/translate');
const textToSpeech = require('@google-cloud/text-to-speech');

async function verify() {
  process.env.GCLOUD_PROJECT = 'your_gcp_project_id';
  console.log("Verifying Google Cloud ADC Authentication...\n");

  // 1. Speech API
  try {
    const speechClient = new speech.SpeechClient();
    const projectId = await speechClient.getProjectId();
    if (projectId) {
      console.log("Speech API: PASS (Project ID: " + projectId + ")");
    } else {
      console.log("Speech API: FAIL (No project ID returned)");
    }
  } catch (e) {
    console.log("Speech API: FAIL -", e.message);
  }

  // 2. Translation API
  try {
    const translationClient = new TranslationServiceClient();
    const projectId = await translationClient.getProjectId();
    if (projectId) {
      console.log("Translation API: PASS (Project ID: " + projectId + ")");
    } else {
      console.log("Translation API: FAIL (No project ID returned)");
    }
  } catch (e) {
    console.log("Translation API: FAIL -", e.message);
  }

  // 3. Text-to-Speech API
  try {
    const ttsClient = new textToSpeech.TextToSpeechClient();
    const projectId = await ttsClient.getProjectId();
    if (projectId) {
      console.log("Text-to-Speech API: PASS (Project ID: " + projectId + ")");
    } else {
      console.log("Text-to-Speech API: FAIL (No project ID returned)");
    }
  } catch (e) {
    console.log("Text-to-Speech API: FAIL -", e.message);
  }
}

verify();
