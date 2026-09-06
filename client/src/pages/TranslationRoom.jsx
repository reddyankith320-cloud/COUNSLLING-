import React, { useEffect, useState, useRef } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { io } from 'socket.io-client';
import RecordRTC, { StereoAudioRecorder } from 'recordrtc';
import { Mic, MicOff, Volume2, VolumeX, MessageSquare, AlertTriangle, ExternalLink } from 'lucide-react';
import toast from 'react-hot-toast';

const LANGUAGES = [
  { code: 'te-IN', label: 'Telugu' },
  { code: 'en-US', label: 'English' },
  { code: 'hi-IN', label: 'Hindi' },
  { code: 'ta-IN', label: 'Tamil' },
  { code: 'kn-IN', label: 'Kannada' },
  { code: 'ml-IN', label: 'Malayalam' },
  { code: 'mr-IN', label: 'Marathi' },
  { code: 'bn-IN', label: 'Bengali' },
  { code: 'gu-IN', label: 'Gujarati' },
  { code: 'pa-IN', label: 'Punjabi' },
  { code: 'ur-IN', label: 'Urdu' }
];

const TranslationRoom = () => {
  const { appointmentId } = useParams();
  const [searchParams] = useSearchParams();
  const role = searchParams.get('role') || 'client'; // 'counselor' or 'client'
  const meetUrl = searchParams.get('meetUrl');
  
  const [socket, setSocket] = useState(null);
  const [transcripts, setTranscripts] = useState([]);
  const [interimText, setInterimText] = useState('');
  
  const [isRecording, setIsRecording] = useState(false);
  const [playbackEnabled, setPlaybackEnabled] = useState(true);
  const [clientLanguage, setClientLanguage] = useState(role === 'client' ? 'en-US' : 'te-IN');
  
  const recorderRef = useRef(null);
  const streamRef = useRef(null);
  const transcriptEndRef = useRef(null);

  // Scroll to bottom when transcripts update
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [transcripts, interimText]);

  // Socket initialization
  useEffect(() => {
    const socketUrl = import.meta.env.VITE_API_URL?.replace('/api', '') || 'http://localhost:5000';
    const newSocket = io(`${socketUrl}/translation`, {
      withCredentials: true
    });
    
    newSocket.on('connect', () => {
      newSocket.emit('join-room', { 
        appointmentId, 
        role,
        clientLanguage
      });
      toast.success('Connected to Translation Server');
    });

    newSocket.on('interim-transcription', (data) => {
      setInterimText(data.text);
    });

    newSocket.on('final-translation', (payload) => {
      setInterimText('');
      setTranscripts(prev => [...prev, payload]);
      
      // Play audio if enabled and it's not my own speech
      if (playbackEnabled && payload.role !== role && payload.audioUrl) {
        const audio = new Audio(payload.audioUrl);
        audio.play().catch(e => console.error('Audio playback failed:', e));
      }
    });

    newSocket.on('disconnect', () => {
      toast.error('Disconnected from Translation Server');
    });

    setSocket(newSocket);

    return () => {
      if (isRecording) stopRecording();
      newSocket.disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appointmentId, role]);

  // Whenever language changes, re-join room to update target lang
  useEffect(() => {
    if (socket && socket.connected) {
      socket.emit('join-room', { appointmentId, role, clientLanguage });
    }
  }, [clientLanguage, socket, appointmentId, role]);

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const recorder = new RecordRTC(stream, {
        type: 'audio',
        mimeType: 'audio/webm',
        recorderType: StereoAudioRecorder,
        timeSlice: 500, // Emit chunks every 500ms
        desiredSampRate: 16000,
        numberOfAudioChannels: 1,
        ondataavailable: (blob) => {
          if (socket && socket.connected) {
            socket.emit('audio-data', blob);
          }
        }
      });

      recorder.startRecording();
      recorderRef.current = recorder;
      setIsRecording(true);
      
      if (socket) {
        socket.emit('start-stream');
      }
    } catch (err) {
      console.error('Mic error:', err);
      toast.error('Could not access microphone');
    }
  };

  const stopRecording = () => {
    if (recorderRef.current) {
      recorderRef.current.stopRecording(() => {
        if (socket) socket.emit('stop-stream');
      });
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
    }
    setIsRecording(false);
  };

  const toggleRecording = () => {
    if (isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  };

  return (
    <div className="flex flex-col h-screen bg-slate-50">
      
      {/* Header */}
      <header className="bg-white border-b border-slate-200 px-6 py-4 flex items-center justify-between shadow-sm z-10">
        <div className="flex items-center gap-3">
          <div className="bg-indigo-100 p-2 rounded-lg text-indigo-600">
            <MessageSquare size={24} />
          </div>
          <div>
            <h1 className="text-xl font-bold text-slate-800">Live Translation Room</h1>
            <p className="text-sm text-slate-500">
              {role === 'counselor' ? 'Counselor View (Telugu)' : 'Client View'} 
              • Appt #{appointmentId}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-4">
          {meetUrl && (
            <a 
              href={meetUrl}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-2 px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-sm font-medium transition-colors"
            >
              <ExternalLink size={16} /> Open Google Meet
            </a>
          )}
          
          {role === 'client' && (
            <div className="flex items-center gap-2">
              <label className="text-sm font-medium text-slate-600">My Language:</label>
              <select 
                value={clientLanguage}
                onChange={(e) => setClientLanguage(e.target.value)}
                className="border-slate-300 rounded-lg shadow-sm focus:border-indigo-500 focus:ring-indigo-500 text-sm"
              >
                {LANGUAGES.map(lang => (
                  <option key={lang.code} value={lang.code}>{lang.label}</option>
                ))}
              </select>
            </div>
          )}
        </div>
      </header>

      {/* Warning Banner */}
      <div className="bg-amber-50 border-b border-amber-200 px-6 py-2 flex items-center gap-3 text-amber-800 text-sm">
        <AlertTriangle size={18} className="shrink-0" />
        <p><strong>Important:</strong> Please MUTE your microphone in the Google Meet window while using the translator to prevent audio echo.</p>
      </div>

      {/* Main Content */}
      <main className="flex-1 overflow-hidden flex flex-col p-6 max-w-4xl mx-auto w-full">
        
        {/* Transcript Area */}
        <div className="flex-1 overflow-y-auto bg-white rounded-2xl shadow-sm border border-slate-200 p-6 mb-6 space-y-6">
          {transcripts.length === 0 && !interimText && (
            <div className="h-full flex flex-col items-center justify-center text-slate-400">
              <MessageSquare size={48} className="mb-4 opacity-20" />
              <p>No transcripts yet. Turn on your mic and start speaking.</p>
            </div>
          )}

          {transcripts.map((t, idx) => {
            const isMe = t.role === role;
            return (
              <div key={idx} className={`flex flex-col ${isMe ? 'items-end' : 'items-start'}`}>
                <div className="flex items-baseline gap-2 mb-1">
                  <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                    {t.role}
                  </span>
                  <span className="text-[10px] text-slate-400">
                    {new Date(t.timestamp).toLocaleTimeString()}
                  </span>
                </div>
                
                <div className={`max-w-[80%] rounded-2xl p-4 ${isMe ? 'bg-indigo-600 text-white rounded-tr-sm' : 'bg-slate-100 text-slate-800 rounded-tl-sm'}`}>
                  {/* Original Text */}
                  <p className={`text-sm mb-2 pb-2 border-b ${isMe ? 'border-indigo-400/50' : 'border-slate-300'}`}>
                    <span className="opacity-75 text-xs mr-2">[{t.detectedLanguage}]</span>
                    {t.originalText}
                  </p>
                  
                  {/* Translated Text */}
                  <p className="font-medium text-lg">
                    {t.translatedText}
                  </p>
                </div>
              </div>
            );
          })}
          
          {/* Interim Text (Live typing effect) */}
          {interimText && (
            <div className={`flex flex-col items-end opacity-70`}>
               <div className={`max-w-[80%] rounded-2xl p-4 bg-indigo-50 text-indigo-900 border border-indigo-100 rounded-tr-sm`}>
                  <p className="italic text-sm">{interimText}</p>
               </div>
            </div>
          )}
          
          <div ref={transcriptEndRef} />
        </div>

        {/* Controls */}
        <div className="bg-white rounded-2xl shadow-lg border border-slate-200 p-4 flex items-center justify-between">
          
          <div className="flex items-center gap-4">
            <button
              onClick={toggleRecording}
              className={`flex items-center gap-2 px-6 py-3 rounded-full font-bold text-white transition-all shadow-md ${
                isRecording 
                  ? 'bg-red-500 hover:bg-red-600 animate-pulse shadow-red-500/30' 
                  : 'bg-indigo-600 hover:bg-indigo-700 shadow-indigo-600/30'
              }`}
            >
              {isRecording ? (
                <><MicOff size={20} /> Stop Mic</>
              ) : (
                <><Mic size={20} /> Start Translating</>
              )}
            </button>
            
            <div className="text-sm text-slate-500 flex items-center gap-2">
              <span className="relative flex h-3 w-3">
                {isRecording && <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75"></span>}
                <span className={`relative inline-flex rounded-full h-3 w-3 ${isRecording ? 'bg-red-500' : 'bg-slate-300'}`}></span>
              </span>
              {isRecording ? 'Listening...' : 'Mic is off'}
            </div>
          </div>

          <div className="flex items-center gap-3">
            <span className="text-sm font-medium text-slate-600">Voice Playback</span>
            <button
              onClick={() => setPlaybackEnabled(!playbackEnabled)}
              className={`p-3 rounded-full transition-colors ${
                playbackEnabled 
                  ? 'bg-emerald-100 text-emerald-700 hover:bg-emerald-200' 
                  : 'bg-slate-100 text-slate-500 hover:bg-slate-200'
              }`}
              title={playbackEnabled ? "Voice playback on" : "Voice playback off"}
            >
              {playbackEnabled ? <Volume2 size={24} /> : <VolumeX size={24} />}
            </button>
          </div>

        </div>
      </main>
    </div>
  );
};

export default TranslationRoom;
