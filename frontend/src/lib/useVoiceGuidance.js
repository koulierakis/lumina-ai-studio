import { useCallback, useEffect, useRef, useState } from 'react';

export function useVoiceGuidance({ onTranscript, defaultInstructionText } = {}) {
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [voiceSupported, setVoiceSupported] = useState(false);
  const [ttsSupported, setTtsSupported] = useState(false);
  const [voiceMessage, setVoiceMessage] = useState('');
  const recognitionRef = useRef(null);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      const hasSpeech = 'webkitSpeechRecognition' in window || 'SpeechRecognition' in window;
      const hasTTS = 'speechSynthesis' in window;
      setVoiceSupported(Boolean(hasSpeech));
      setTtsSupported(Boolean(hasTTS));
    }
  }, []);

  // Text-To-Speech (Φωνητική καθοδήγηση / Εκφώνηση οδηγιών στα Ελληνικά)
  const speak = useCallback((text) => {
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) {
      setVoiceMessage('Η φωνητική ανάγνωση δεν υποστηρίζεται σε αυτό το πρόγραμμα περιήγησης.');
      return;
    }

    try {
      window.speechSynthesis.cancel();

      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = 'el-GR';
      utterance.rate = 1.0;
      utterance.pitch = 1.0;

      // Select Greek voice if available
      const voices = window.speechSynthesis.getVoices();
      const greekVoice = voices.find((v) => v.lang.startsWith('el') || v.lang.includes('Greek'));
      if (greekVoice) {
        utterance.voice = greekVoice;
      }

      utterance.onstart = () => {
        setIsSpeaking(true);
        setVoiceMessage('🔊 Η φωνητική καθοδήγηση εκφωνεί οδηγίες...');
      };

      utterance.onend = () => {
        setIsSpeaking(false);
        setVoiceMessage('');
      };

      utterance.onerror = () => {
        setIsSpeaking(false);
        setVoiceMessage('');
      };

      window.speechSynthesis.speak(utterance);
    } catch {
      setIsSpeaking(false);
    }
  }, []);

  const stopSpeaking = useCallback(() => {
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel();
      setIsSpeaking(false);
      setVoiceMessage('');
    }
  }, []);

  // Speech-To-Text (Φωνητική υπαγόρευση prompt με μικρόφωνο)
  const startListening = useCallback(() => {
    if (typeof window === 'undefined') return;
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      setVoiceMessage('Το μικρόφωνο δεν υποστηρίζεται σε αυτό το browser. Πληκτρολογήστε το prompt.');
      return;
    }

    try {
      if (recognitionRef.current) {
        recognitionRef.current.abort();
      }

      const recognition = new SpeechRecognition();
      recognition.lang = 'el-GR';
      recognition.continuous = true;
      recognition.interimResults = true;

      recognition.onstart = () => {
        setIsListening(true);
        setVoiceMessage('🎙️ Ακούω... Μιλήστε τώρα για να υπαγορεύσετε το prompt.');
      };

      recognition.onresult = (event) => {
        const transcript = Array.from(event.results)
          .map((res) => res[0]?.transcript || '')
          .join('');
        if (onTranscript) {
          onTranscript(transcript);
        }
      };

      recognition.onerror = (event) => {
        setIsListening(false);
        if (event.error === 'not-allowed') {
          setVoiceMessage('⚠️ Δεν δόθηκε άδεια πρόσβασης στο μικρόφωνο.');
        } else {
          setVoiceMessage(`Σφάλμα μικροφώνου: ${event.error}`);
        }
      };

      recognition.onend = () => {
        setIsListening(false);
        setVoiceMessage('');
      };

      recognitionRef.current = recognition;
      recognition.start();
    } catch {
      setIsListening(false);
      setVoiceMessage('Αδυναμία έναρξης μικροφώνου.');
    }
  }, [onTranscript]);

  const stopListening = useCallback(() => {
    if (recognitionRef.current) {
      recognitionRef.current.stop();
      setIsListening(false);
      setVoiceMessage('');
    }
  }, []);

  const toggleListening = useCallback(() => {
    if (isListening) {
      stopListening();
    } else {
      startListening();
    }
  }, [isListening, startListening, stopListening]);

  return {
    isSpeaking,
    isListening,
    voiceSupported,
    ttsSupported,
    voiceMessage,
    speak,
    stopSpeaking,
    startListening,
    stopListening,
    toggleListening,
  };
}
