export class SpeechManager {
    recognition: any;
    isListening: boolean = false;
    private currentAudio: HTMLAudioElement | null = null;
    onResult: (text: string) => void;
    onError?: (error: string) => void;

    constructor(onResult: (text: string) => void, onError?: (error: string) => void) {
        this.onResult = onResult;
        this.onError = onError;

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

    stopAudio() {
        if (this.currentAudio) {
            this.currentAudio.pause();
            this.currentAudio.currentTime = 0;
            this.currentAudio = null;
        }
    }

    playAudio(audioBlob: Blob, onEnd?: () => void) {
        this.stopAudio();

        const url = URL.createObjectURL(audioBlob);
        const audio = new Audio(url);
        this.currentAudio = audio;

        audio.onended = () => {
            URL.revokeObjectURL(url);
            this.currentAudio = null;
            if (onEnd) onEnd();
        };

        audio.onerror = (e) => {
            console.error("Audio playback error:", e);
            URL.revokeObjectURL(url);
            this.currentAudio = null;
            if (this.onError) this.onError("Audio playback failed");
            if (onEnd) onEnd();
        };

        audio.play().catch((err) => {
            console.error("Audio play() rejected:", err);
            if (this.onError) this.onError("Audio blocked by browser. Click PLAY on a message to start.");
            if (onEnd) onEnd();
        });
    }
}
