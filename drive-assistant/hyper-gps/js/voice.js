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
        this.wakeEnabled = false;
        this.directUntil = 0;
        this.armedUntil = 0;
        this.followupUntil = 0;
        this.speaking = false;
        this.voicePreference = localStorage.getItem('hyper-gps-voice') || 'female';
        this.audioContext = null;
        this.lastError = null;
        this.restartTimer = null;
        this.retryCount = 0;
        this.initRecognition();
        document.addEventListener('visibilitychange', () => {
            if (document.hidden && this.isListening) this.recognition?.stop();
            else if (!document.hidden && this.wakeEnabled && !this.isListening) this.startRecognition();
        });
    }

    status(message, listening = false) {
        if (this.onStatusChange) this.onStatusChange(listening, message);
    }

    initRecognition() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) return;
        this.recognition = new SpeechRecognition();
        this.recognition.lang = this.lang;
        this.recognition.interimResults = false;
        this.recognition.onstart = () => {
            this.isListening = true;
            this.lastError = null;
            this.retryCount = 0;
            this.status(this.wakeEnabled ? 'Ακούω μόνο «Τζούλι»' : 'Σε ακούω...', true);
        };
        this.recognition.onresult = event => {
            for (let i = event.resultIndex ?? 0; i < event.results.length; i++) {
                const result = event.results[i];
                if (result.isFinal === false) continue;
                this.handleTranscript(result[0].transcript);
            }
        };
        this.recognition.onerror = event => {
            this.isListening = false;
            if (event.error === 'no-speech' || event.error === 'aborted') return;
            const denied = event.error === 'not-allowed' || event.error === 'service-not-allowed';
            if (denied) this.wakeEnabled = false;
            this.lastError = denied ? 'Επίτρεψε το μικρόφωνο στις ρυθμίσεις του Chrome.'
                : event.error === 'network' ? 'Η αναγνώριση φωνής χρειάζεται σύνδεση δικτύου.'
                : `Σφάλμα μικροφώνου (${event.error}). Πάτησε ξανά.`;
            this.status(this.lastError);
        };
        this.recognition.onend = () => {
            this.isListening = false;
            if ((this.wakeEnabled || Date.now() < this.followupUntil) && !this.speaking && !document.hidden && !this.lastError) {
                clearTimeout(this.restartTimer);
                this.restartTimer = setTimeout(() => this.startRecognition(), 600);
            } else if (!this.lastError && !this.wakeEnabled) this.status('Πάτησε για Εντολή');
        };
    }

    startRecognition() {
        if (!this.recognition || this.isListening || this.speaking || document.hidden) return;
        this.recognition.continuous = this.wakeEnabled;
        try { this.recognition.start(); }
        catch (error) {
            if (error.name === 'InvalidStateError' && this.retryCount++ < 4 && this.wakeEnabled) {
                clearTimeout(this.restartTimer);
                this.restartTimer = setTimeout(() => this.startRecognition(), 750);
            } else {
                this.wakeEnabled = false;
                this.lastError = 'Η ακρόαση δεν ξεκίνησε. Πάτησε ξανά.';
                this.status(this.lastError);
            }
        }
    }

    toggleListening() {
        if (!this.recognition) return this.status('Η φωνή δεν υποστηρίζεται εδώ. Γράψε προορισμό.');
        this.directUntil = Date.now() + 10000;
        this.lastError = null;
        if (this.isListening) this.status('Πες την εντολή σου τώρα.', true);
        else this.startRecognition();
    }

    toggleWakeMode() {
        if (!this.recognition) {
            this.status('Η συνεχής ακρόαση δεν υποστηρίζεται εδώ.');
            return false;
        }
        this.wakeEnabled = !this.wakeEnabled;
        this.directUntil = 0;
        this.armedUntil = 0;
        this.followupUntil = 0;
        this.lastError = null;
        clearTimeout(this.restartTimer);
        if (this.wakeEnabled) {
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            if (AudioContext && !this.audioContext) this.audioContext = new AudioContext();
            this.audioContext?.resume().catch(() => {});
            if (this.isListening) this.recognition.stop();
            else this.startRecognition();
            this.status('Ακούω μόνο «Τζούλι»', true);
        } else {
            if (this.isListening) this.recognition.stop();
            this.status('Η Τζούλι είναι κλειστή.');
        }
        return this.wakeEnabled;
    }

    handleTranscript(raw) {
        const text = String(raw || '').trim();
        const normalized = text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
        const wake = normalized.match(/^(?:ε[ι]?\s+)?(?:τζουλ[ιη]|ζουλ[ιη]|julie|juli)(?:[\s,.:;!?]+|$)/);
        let command = normalized;
        if (this.wakeEnabled) {
            if (wake) {
                this.playWakeTone();
                command = normalized.slice(wake[0].length).trim();
                if (!command) {
                    this.armedUntil = Date.now() + 8000;
                    this.status('Τζούλι: πες την εντολή μέσα σε 8 δευτερόλεπτα.', true);
                    return;
                }
                this.armedUntil = 0;
            } else if (Date.now() < this.directUntil || Date.now() < this.armedUntil || Date.now() < this.followupUntil) {
                this.armedUntil = 0;
            } else return; // Ignore unrelated conversation in wake mode.
        }
        this.directUntil = 0;
        this.followupUntil = 0;
        if (!command) return;
        this.status(`Εντολή: ${command}`);
        this.parseVoiceCommand(command);
    }

    // Command intent is based on the destination and action, not a single trigger verb.
    parseVoiceCommand(text) {
        const command = text.trim().toLowerCase();
        if (/^(ναι|ξεκινα|ξεκινησε|παμε|οδηγησε με|δειξε τη διαδρομη|yes|start)(?:\b|$)/.test(command)) {
            this.onCommandRecognized({ type: 'CONFIRM_ROUTE' });
            return;
        }
        if (/^(οχι|ακυρο|μην ξεκινησεις|no)(?:\b|$)/.test(command)) {
            this.onCommandRecognized({ type: 'DECLINE_ROUTE' });
            return;
        }
        if (/(ακυρ|σταματα|τελος διαδρομης|cancel|stop)/.test(command)) {
            this.onCommandRecognized({ type: 'CANCEL_NAV' });
            return;
        }
        const category = /(βενζιν|καυσιμ|πρατηρι|gas|fuel)/.test(command) ? 'fuel'
            : /(φαρμακ|pharmacy)/.test(command) ? 'pharmacy'
            : /(ξενοδοχ|hotel)/.test(command) ? 'hotel'
            : /(φαστ φουντ|fast food|ταχυφαγει)/.test(command) ? 'fast_food'
            : /(βουλκανιζατερ|λαστιχ|ελαστικ|tyre|tire)/.test(command) ? 'tyres'
            : /(συνεργει|επισκευ.{0,12}αυτοκιν|car repair|garage)/.test(command) ? 'car_repair'
            : /(φαγητ|εστιατορ|restaurant|food)/.test(command) ? 'restaurant'
            : /(καφε|καφετερι|cafe|coffee)/.test(command) ? 'cafe'
            : /(μουσει|museum)/.test(command) ? 'museum'
            : /(γυμναστηρι|fitness|gym)/.test(command) ? 'gym'
            : /(αθλητικ|γηπεδ|sports)/.test(command) ? 'sports'
            : /(νοσοκομ|hospital)/.test(command) ? 'hospital'
            : /(κεντρ.{0,12}υγει|κλινικ|clinic)/.test(command) ? 'clinic'
            : /(σιδηροδρομ|σταθμ.{0,10}τρεν|train station)/.test(command) ? 'railway'
            : /(αεροδρομ|airport)/.test(command) ? 'airport'
            : /(λιμαν|λιμεν|port|harbour)/.test(command) ? 'port' : null;
        if (category) {
            const remote = !/(κοντιν|πλησιεστερ|εδω γυρω)/.test(command) && /(?:^|\s)(?:στην|στον|στη|στο)\s+\S+/.test(command);
            if (remote) {
                const destination = command.replace(/^(?:(?:βρες|δειξε|που ειναι|θελω να παω|πηγαινε με|οδηγησε με|σε παρακαλω|μου|το|η|ο|που)\s+)+/, '').trim();
                this.onCommandRecognized({ type: 'SEARCH_PLACE', destination });
                return;
            }
            const navigate = /(παω|πηγαιν|οδηγησ|διαδρομ|navigate|take me)/.test(command);
            this.onCommandRecognized({ type: 'POI', category, navigate });
            return;
        }
        if (/^(?:(?:πες μου|μπορεις να)\s+)?(?:που ειναι|βρες μου|δειξε μου|βρες|δειξε|θελω να δω)\s+/.test(command)) {
            const destination = command.replace(/^(?:(?:πες μου|μπορεις να)\s+)?(?:που ειναι|βρες μου|δειξε μου|βρες|δειξε|θελω να δω)\s+/, '')
                .replace(/^(?:τα|το|την|τον|τη|ο|η)\s+/, '').trim();
            if (destination) this.onCommandRecognized({ type: 'SEARCH_PLACE', destination });
            return;
        }
        if (/(παω|πηγαιν|οδηγησ|διαδρομη προς|navigate to)/.test(command)) {
            const destination = command.replace(/^(θελω να |μπορεις να |σε παρακαλω )*/, '')
                .replace(/^(παω|πηγαινε με|πηγαινε|οδηγησε με|διαδρομη προς|navigate to)\s*/, '')
                .replace(/^(στο|στη|στην|στον|στα|σε)\s+/, '').trim();
            if (destination) this.onCommandRecognized({ type: 'NAVIGATE', destination });
            else this.status('Πες μου τον προορισμό.');
            return;
        }
        this.status('Πες, για παράδειγμα, «Τζούλι, δείξε το κοντινότερο βενζινάδικο».');
    }

    playWakeTone() {
        const context = this.audioContext;
        if (!context || context.state !== 'running') return;
        const oscillator = context.createOscillator();
        const gain = context.createGain();
        oscillator.type = 'sine';
        oscillator.frequency.value = 740;
        gain.gain.setValueAtTime(0.04, context.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, context.currentTime + 0.13);
        oscillator.connect(gain).connect(context.destination);
        oscillator.start();
        oscillator.stop(context.currentTime + 0.14);
    }

    expectFollowup(ms = 12000) {
        this.followupUntil = Date.now() + ms;
        if (!this.wakeEnabled && !this.isListening) this.startRecognition();
        clearTimeout(this.followupTimer);
        this.followupTimer = setTimeout(() => {
            this.followupUntil = 0;
            if (!this.wakeEnabled && this.isListening) this.recognition.stop();
        }, ms);
    }

    setVoicePreference(value) {
        this.voicePreference = value === 'male' ? 'male' : 'female';
        localStorage.setItem('hyper-gps-voice', this.voicePreference);
    }

    availableGreekVoices() {
        return this.synthesis?.getVoices().filter(v => /^el(?:-|_)/i.test(v.lang)) || [];
    }

    // Device voices vary; select distinct Greek voices when provided by the device.
    selectedVoice() {
        const voices = this.availableGreekVoices();
        const names = this.voicePreference === 'male' ? /nestoras|male|ανδρ/i : /athina|female|γυναικ/i;
        return voices.find(v => names.test(v.name)) || voices[0];
    }

    speak(text, { followup = false } = {}) {
        if (!this.synthesis) return;
        this.synthesis.cancel();
        this.speaking = true;
        clearTimeout(this.restartTimer);
        if (this.isListening) this.recognition?.stop();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = this.lang;
        utterance.rate = 1.05;
        const voice = this.selectedVoice();
        if (voice) utterance.voice = voice;
        const done = () => {
            this.speaking = false;
            if (followup) this.expectFollowup();
            else if (this.wakeEnabled) this.startRecognition();
        };
        utterance.onend = done;
        utterance.onerror = done;
        this.synthesis.speak(utterance);
    }
}
