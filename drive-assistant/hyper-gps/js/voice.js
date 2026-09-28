/**
 * voice.js - Voice Recognition & Speech Synthesis Core
 */

export class VoiceAssistant {
    constructor(onCommandRecognized, onStatusChange) {
        this.onCommandRecognized = onCommandRecognized;
        this.onStatusChange = onStatusChange;
        this.lang = 'el-GR';
        this.recognition = null;
        this.synthesis = window.speechSynthesis;
        this.isListening = false;

        this.initRecognition();
    }

    initRecognition() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            console.warn('Speech Recognition not supported in this browser.');
            return;
        }

        this.recognition = new SpeechRecognition();
        this.recognition.lang = this.lang;
        this.recognition.continuous = false;
        this.recognition.interimResults = false;

        this.recognition.onstart = () => {
            this.isListening = true;
            if (this.onStatusChange) this.onStatusChange(true, 'Σε ακούω...');
        };

        this.recognition.onresult = (event) => {
            const transcript = event.results[0][0].transcript.toLowerCase();
            if (this.onStatusChange) this.onStatusChange(false, `Εντολή: "${transcript}"`);
            this.parseVoiceCommand(transcript);
        };

        this.recognition.onerror = (e) => {
            this.isListening = false;
            if (this.onStatusChange) this.onStatusChange(false, 'Σφάλμα φωνής');
        };

        this.recognition.onend = () => {
            this.isListening = false;
            if (this.onStatusChange) this.onStatusChange(false, 'Πάτησε για Εντολή');
        };
    }

    toggleListening() {
        if (!this.recognition) return;
        if (this.isListening) {
            this.recognition.stop();
        } else {
            this.recognition.start();
        }
    }

    // Φυσική ανάλυση φωνητικών εντολών (NLP Logic)
    parseVoiceCommand(text) {
        text = text.trim().toLowerCase();

        // 1. Πλοήγηση σε γενικό προορισμό
        if (text.includes('πήγαινέ με') || text.includes('πήγαινε με') || text.includes('navigate to')) {
            let destination = text
                .replace('πήγαινέ με', '')
                .replace('πήγαινε με', '')
                .replace('navigate to', '')
                .replace('στο', '')
                .replace('στην', '')
                .replace('στον', '')
                .replace('στα', '')
                .trim();

            this.onCommandRecognized({ type: 'NAVIGATE', destination });
            return;
        }

        // 2. Αναζήτηση Σημείων Ενδιαφέροντος (POIs)
        if (text.includes('βρες') || text.includes('find')) {
            if (text.includes('βενζιν') || text.includes('gas') || text.includes('fuel')) {
                this.onCommandRecognized({ type: 'POI', category: 'fuel' });
            } else if (text.includes('φαρμακ') || text.includes('pharmacy')) {
                this.onCommandRecognized({ type: 'POI', category: 'pharmacy' });
            } else if (text.includes('ξενοδοχ') || text.includes('hotel')) {
                this.onCommandRecognized({ type: 'POI', category: 'hotel' });
            } else if (text.includes('φαγητό') || text.includes('εστιατόρ') || text.includes('food')) {
                this.onCommandRecognized({ type: 'POI', category: 'restaurant' });
            }
            return;
        }

        // 3. Ακύρωση διαδρομής
        if (text.includes('ακύρωση') || text.includes('σταμάτα') || text.includes('cancel')) {
            this.onCommandRecognized({ type: 'CANCEL_NAV' });
            return;
        }

        // 4. Default Search
        this.onCommandRecognized({ type: 'SEARCH', query: text });
    }

    // Φωνητική εκφώνηση οδηγίας (TTS)
    speak(text) {
        if (!this.synthesis) return;
        this.synthesis.cancel(); // Σταματάει προηγούμενη ομιλία

        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = this.lang;
        utterance.rate = 1.05;
        utterance.pitch = 1.0;

        // Επιλογή καθαρής φωνής εάν είναι διαθέσιμη
        const voices = this.synthesis.getVoices();
        const greekVoice = voices.find(v => v.lang.includes('el') || v.lang.includes('GR'));
        if (greekVoice) utterance.voice = greekVoice;

        this.synthesis.speak(utterance);
    }
}
