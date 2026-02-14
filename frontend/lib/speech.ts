export class SpeechManager {
    recognition: any;
    isListening: boolean = false;
    private currentAudio: HTMLAudioElement | null = null;
    private sendTimer: ReturnType<typeof setTimeout> | null = null;
    private finalTranscript: string = '';
    onResult: (text: string) => void;
    onInterim?: (text: string) => void;
    onError?: (error: string) => void;

    constructor(
        onResult: (text: string) => void,
        onError?: (error: string) => void,
        onInterim?: (text: string) => void
    ) {
        this.onResult = onResult;
        this.onError = onError;
        this.onInterim = onInterim;

        if (typeof window !== 'undefined') {
            const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
            if (SpeechRecognition) {
                this.recognition = new SpeechRecognition();
                this.recognition.lang = 'en-US';
                this.recognition.continuous = true;
                this.recognition.interimResults = true;

                this.recognition.onresult = (event: any) => {
                    let interim = '';
                    let final = '';

                    for (let i = 0; i < event.results.length; i++) {
                        const result = event.results[i];
                        if (result.isFinal) {
                            final += result[0].transcript;
                        } else {
                            interim += result[0].transcript;
                        }
                    }

                    if (final) {
                        this.finalTranscript = final;
                    }

                    // Show what the user is saying in real-time
                    const displayText = (this.finalTranscript + ' ' + interim).trim();
                    if (this.onInterim) this.onInterim(displayText);

                    // Reset send timer on each new result — waits for a pause in speech
                    if (this.sendTimer) clearTimeout(this.sendTimer);

                    if (this.finalTranscript.trim()) {
                        this.sendTimer = setTimeout(() => {
                            const text = this.finalTranscript.trim();
                            this.finalTranscript = '';
                            if (text) {
                                this.stopListening();
                                this.onResult(text);
                            }
                        }, 1500); // Wait 1.5s of silence after final result before sending
                    }
                };

                this.recognition.onerror = (event: any) => {
                    console.error('Speech recognition error', event.error);
                    // Don't report 'no-speech' as an error — it's normal
                    if (event.error !== 'no-speech' && this.onError) {
                        this.onError(event.error);
                    }
                    this.isListening = false;
                };

                this.recognition.onend = () => {
                    // If we're still supposed to be listening, restart (browser can stop recognition randomly)
                    if (this.isListening) {
                        try {
                            this.recognition.start();
                        } catch {
                            this.isListening = false;
                        }
                    }
                };
            }
        }
    }

    startListening() {
        if (this.recognition && !this.isListening) {
            this.finalTranscript = '';
            if (this.sendTimer) clearTimeout(this.sendTimer);
            try {
                this.recognition.start();
                this.isListening = true;
            } catch {
                // Already started
            }
        }
    }

    stopListening() {
        if (this.recognition && this.isListening) {
            this.isListening = false;
            if (this.sendTimer) {
                clearTimeout(this.sendTimer);
                this.sendTimer = null;
            }
            try {
                this.recognition.stop();
            } catch {
                // Already stopped
            }
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
            if (this.onError) this.onError("Audio blocked by browser. Click anywhere first, then try again.");
            if (onEnd) onEnd();
        });
    }
}
