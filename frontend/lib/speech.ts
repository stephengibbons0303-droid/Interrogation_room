export interface SpeechConfig {
    lang: string;
    continuous: boolean;
}

export class SpeechManager {
    recognition: any;
    synthesis: SpeechSynthesis | null = null;
    isListening: boolean = false;
    currentUtterance: SpeechSynthesisUtterance | null = null; // Prevent GC
    onResult: (text: string) => void;
    onError?: (error: string) => void;

    constructor(onResult: (text: string) => void, onError?: (error: string) => void) {
        this.onResult = onResult;
        this.onError = onError;

        // Check browser support
        if (typeof window !== 'undefined') {
            const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
            if (SpeechRecognition) {
                this.recognition = new SpeechRecognition();
                this.recognition.lang = 'en-US';
                this.recognition.continuous = false;
                this.recognition.interimResults = false;

                this.recognition.onresult = (event: any) => {
                    const transcript = event.results[0][0].transcript;
                    this.onResult(transcript);
                };

                this.recognition.onerror = (event: any) => {
                    console.error('Speech recognition error', event.error);
                    if (this.onError) this.onError(event.error);
                    this.isListening = false;
                };

                this.recognition.onend = () => {
                    this.isListening = false;
                };
            }

            this.synthesis = window.speechSynthesis;
        }
    }

    startListening() {
        if (this.recognition && !this.isListening) {
            this.recognition.start();
            this.isListening = true;
        }
    }

    stopListening() {
        if (this.recognition && this.isListening) {
            this.recognition.stop();
            this.isListening = false;
        }
    }

    speak(text: string, voiceName?: string, options: { rate?: number, pitch?: number } = {}, onEnd?: () => void) {
        if (!this.synthesis) {
            console.error("SpeechManager: speechSynthesis not supported.");
            return;
        }

        console.log("SpeechManager: Request to speak:", text);

        // Cancel pending
        this.synthesis.cancel();

        const speakWithVoice = (voice: SpeechSynthesisVoice | null) => {
            const utterance = new SpeechSynthesisUtterance(text);
            // Store reference to prevent GC
            this.currentUtterance = utterance;

            // Apply voice options
            utterance.rate = options.rate || 1.0;
            utterance.pitch = options.pitch || 1.0;

            if (voice) {
                utterance.voice = voice;
                console.log("SpeechManager: Using voice:", voice.name);
            } else {
                console.log("SpeechManager: Using default voice");
            }

            utterance.onstart = () => console.log("SpeechManager: Started speaking");

            utterance.onend = () => {
                console.log("SpeechManager: Finished speaking");
                this.currentUtterance = null; // Release ref
                if (onEnd) onEnd();
            };

            utterance.onerror = (e: any) => {
                console.error("SpeechManager: Utterance error event:", e);
                console.error("SpeechManager: Error name (explicit):", e.error);
                this.currentUtterance = null; // Release ref

                // Propagate error to UI
                if (this.onError) this.onError(`TTS Error: ${e.error || 'Unknown'}`);

                // Retry fallback logic
                if (voice && e.error !== 'not-allowed' && e.error !== 'interrupted' && e.error !== 'canceled') {
                    console.log("SpeechManager: Retrying with default voice...");
                    this.speak(text, undefined, options, onEnd);
                }
            };

            this.synthesis!.speak(utterance);
        };

        let voices = this.synthesis.getVoices();

        if (voices.length === 0) {
            console.log("SpeechManager: Voices empty, waiting for onvoiceschanged...");
            this.synthesis.onvoiceschanged = () => {
                voices = this.synthesis!.getVoices();
                const selectedVoice = voiceName ? voices.find(v => v.name.includes(voiceName)) : null;
                speakWithVoice(selectedVoice || null);
            };
            return;
        }

        const selectedVoice = voiceName ? voices.find(v => v.name.includes(voiceName)) : null;
        speakWithVoice(selectedVoice || null);
    }

    getVoices() {
        if (this.synthesis) {
            return this.synthesis.getVoices();
        }
        return [];
    }
}
