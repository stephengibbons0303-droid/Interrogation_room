const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || '/api';

export class SpeechManager {
    private vad: any = null;
    private currentAudio: HTMLAudioElement | null = null;
    isListening: boolean = false;
    isTranscribing: boolean = false;

    onResult: (text: string) => void;
    onError?: (error: string) => void;
    onListeningChange?: (listening: boolean) => void;
    onTranscribing?: (transcribing: boolean) => void;

    constructor(
        onResult: (text: string) => void,
        onError?: (error: string) => void,
        onListeningChange?: (listening: boolean) => void,
        onTranscribing?: (transcribing: boolean) => void
    ) {
        this.onResult = onResult;
        this.onError = onError;
        this.onListeningChange = onListeningChange;
        this.onTranscribing = onTranscribing;
    }

    async startListening() {
        if (this.isListening) return;
        this.stopAudio();

        try {
            if (!this.vad) {
                const { MicVAD } = await import("@ricky0123/vad-web");
                this.vad = await MicVAD.new({
                    positiveSpeechThreshold: 0.5,
                    negativeSpeechThreshold: 0.35,
                    minSpeechMs: 250,
                    redemptionMs: 500,
                    preSpeechPadMs: 300,
                    onSpeechEnd: (audio: Float32Array) => {
                        this.handleSpeechEnd(audio);
                    },
                });
            }

            this.vad.start();
            this.isListening = true;
            if (this.onListeningChange) this.onListeningChange(true);
        } catch (error) {
            console.error('VAD initialization error:', error);
            if (this.onError) {
                this.onError('Microphone access denied. Please allow microphone access and try again.');
            }
        }
    }

    stopListening() {
        if (!this.isListening) return;
        this.isListening = false;
        if (this.onListeningChange) this.onListeningChange(false);
        if (this.vad) {
            this.vad.pause();
        }
    }

    private async handleSpeechEnd(audio: Float32Array) {
        // Pause VAD immediately to prevent double-triggering during transcription
        this.vad?.pause();
        this.isListening = false;
        if (this.onListeningChange) this.onListeningChange(false);

        // Skip very short audio (< 100ms at 16kHz = noise)
        if (audio.length < 1600) return;

        this.isTranscribing = true;
        if (this.onTranscribing) this.onTranscribing(true);

        try {
            const wavBlob = float32ToWav(audio, 16000);
            const formData = new FormData();
            formData.append('audio', wavBlob, 'recording.wav');

            const response = await fetch(`${BACKEND_URL}/stt`, {
                method: 'POST',
                body: formData,
            });

            if (!response.ok) {
                throw new Error(`STT returned ${response.status}`);
            }

            const data = await response.json();

            if (data.text && data.text.trim()) {
                this.onResult(data.text.trim());
            }
        } catch (error) {
            console.error('Transcription error:', error);
            if (this.onError) {
                this.onError('Transcription failed. Please try again or type your response.');
            }
        } finally {
            this.isTranscribing = false;
            if (this.onTranscribing) this.onTranscribing(false);
        }
    }

    stopAudio() {
        if (this.currentAudio) {
            this.currentAudio.pause();
            this.currentAudio.currentTime = 0;
            this.currentAudio = null;
        }
    }

    playAudio(audioBlob: Blob, onEnd?: () => void, onStart?: () => void) {
        this.stopAudio();

        const url = URL.createObjectURL(audioBlob);
        const audio = new Audio(url);
        this.currentAudio = audio;

        let started = false;
        const fireStart = () => {
            if (started) return;
            started = true;
            if (onStart) onStart();
        };

        audio.addEventListener('playing', fireStart, { once: true });
        audio.addEventListener('pause', fireStart, { once: true });

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
            fireStart();
            if (onEnd) onEnd();
        };

        audio.play().catch((err) => {
            console.error("Audio play() rejected:", err);
            if (this.onError) this.onError("Audio blocked by browser. Click anywhere first, then try again.");
            fireStart();
            if (onEnd) onEnd();
        });
    }

    async playStreamingAudio(response: Response, onEnd?: () => void, onStart?: () => void) {
        this.stopAudio();

        let started = false;
        const fireStart = () => {
            if (started) return;
            started = true;
            if (onStart) onStart();
        };

        const canStream = typeof MediaSource !== 'undefined'
            && MediaSource.isTypeSupported('audio/mpeg');

        if (canStream && response.body) {
            const mediaSource = new MediaSource();
            const audio = new Audio();
            audio.src = URL.createObjectURL(mediaSource);
            this.currentAudio = audio;

            audio.addEventListener('playing', fireStart, { once: true });
            audio.addEventListener('pause', fireStart, { once: true });

            mediaSource.addEventListener('sourceopen', async () => {
                const sourceBuffer = mediaSource.addSourceBuffer('audio/mpeg');
                const reader = response.body!.getReader();

                const waitForUpdate = () =>
                    new Promise<void>(resolve =>
                        sourceBuffer.addEventListener('updateend', () => resolve(), { once: true })
                    );

                try {
                    while (true) {
                        const { done, value } = await reader.read();
                        if (done) break;

                        if (sourceBuffer.updating) {
                            await waitForUpdate();
                        }

                        sourceBuffer.appendBuffer(value);
                        await waitForUpdate();
                    }

                    if (sourceBuffer.updating) {
                        await waitForUpdate();
                    }
                    if (mediaSource.readyState === 'open') {
                        mediaSource.endOfStream();
                    }
                } catch (err) {
                    console.error('Stream read error:', err);
                    fireStart();
                    if (onEnd) onEnd();
                }
            });

            audio.onended = () => {
                URL.revokeObjectURL(audio.src);
                this.currentAudio = null;
                if (onEnd) onEnd();
            };

            audio.onerror = (e) => {
                console.error("Streaming audio error:", e);
                URL.revokeObjectURL(audio.src);
                this.currentAudio = null;
                fireStart();
                if (onEnd) onEnd();
            };

            audio.play().catch((err) => {
                console.error("Audio play() rejected:", err);
                if (this.onError) this.onError("Audio blocked by browser. Click anywhere first, then try again.");
                fireStart();
                if (onEnd) onEnd();
            });
        } else {
            // Fallback: collect full response as blob, then play
            const blob = await response.blob();
            this.playAudio(blob, onEnd, onStart);
        }
    }

    destroy() {
        this.stopListening();
        this.stopAudio();
        if (this.vad) {
            this.vad.destroy();
            this.vad = null;
        }
    }
}

function float32ToWav(samples: Float32Array, sampleRate: number): Blob {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);

    writeString(view, 0, 'RIFF');
    view.setUint32(4, 36 + samples.length * 2, true);
    writeString(view, 8, 'WAVE');

    writeString(view, 12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);

    writeString(view, 36, 'data');
    view.setUint32(40, samples.length * 2, true);

    for (let i = 0; i < samples.length; i++) {
        const s = Math.max(-1, Math.min(1, samples[i]));
        view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
    }

    return new Blob([buffer], { type: 'audio/wav' });
}

function writeString(view: DataView, offset: number, str: string) {
    for (let i = 0; i < str.length; i++) {
        view.setUint8(offset + i, str.charCodeAt(i));
    }
}
