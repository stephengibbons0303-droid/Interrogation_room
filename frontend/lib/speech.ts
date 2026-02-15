const API_URL = '/api';

export class SpeechManager {
    private mediaRecorder: MediaRecorder | null = null;
    private audioChunks: Blob[] = [];
    private stream: MediaStream | null = null;
    private currentAudio: HTMLAudioElement | null = null;
    private silenceTimer: ReturnType<typeof setTimeout> | null = null;
    private analyser: AnalyserNode | null = null;
    private audioContext: AudioContext | null = null;
    private silenceCheckInterval: ReturnType<typeof setInterval> | null = null;
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

        // Interrupt any playing AI audio
        this.stopAudio();

        try {
            this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });

            // Set up audio analysis for silence detection
            this.audioContext = new AudioContext();
            const source = this.audioContext.createMediaStreamSource(this.stream);
            this.analyser = this.audioContext.createAnalyser();
            this.analyser.fftSize = 512;
            source.connect(this.analyser);

            this.mediaRecorder = new MediaRecorder(this.stream, {
                mimeType: this.getSupportedMimeType(),
            });

            this.audioChunks = [];

            this.mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    this.audioChunks.push(event.data);
                }
            };

            this.mediaRecorder.onstop = () => {
                this.handleRecordingComplete();
            };

            // Record in 150ms chunks for responsive silence detection
            this.mediaRecorder.start(150);
            this.isListening = true;
            if (this.onListeningChange) this.onListeningChange(true);

            // Start monitoring for silence
            this.startSilenceDetection();

        } catch (error) {
            console.error('Microphone access error:', error);
            if (this.onError) {
                this.onError('Microphone access denied. Please allow microphone access and try again.');
            }
        }
    }

    private getSupportedMimeType(): string {
        const types = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg'];
        for (const type of types) {
            if (MediaRecorder.isTypeSupported(type)) return type;
        }
        return 'audio/webm';
    }

    private startSilenceDetection() {
        if (!this.analyser) return;

        let speechDetected = false;
        let silenceStart: number | null = null;
        let smoothedRms = 0;
        const recordingStartTime = Date.now();

        const SPEECH_THRESHOLD = 10;   // RMS must exceed this to confirm speech / reset silence timer
        const SILENCE_DURATION = 1000; // 1.0s below speech level to auto-stop
        const SMOOTHING = 0.6;         // EMA factor: higher = faster response to volume changes
        const MAX_RECORDING_MS = 30000;

        const dataArray = new Uint8Array(this.analyser.fftSize);

        this.silenceCheckInterval = setInterval(() => {
            if (!this.analyser || !this.isListening) return;

            if (Date.now() - recordingStartTime > MAX_RECORDING_MS) {
                this.stopListening();
                return;
            }

            this.analyser.getByteTimeDomainData(dataArray);

            let sum = 0;
            for (let i = 0; i < dataArray.length; i++) {
                const val = (dataArray[i] - 128) / 128;
                sum += val * val;
            }
            const rms = Math.sqrt(sum / dataArray.length) * 100;

            smoothedRms = SMOOTHING * rms + (1 - SMOOTHING) * smoothedRms;

            if (!speechDetected) {
                // Waiting for clear speech to start
                if (smoothedRms > SPEECH_THRESHOLD) {
                    speechDetected = true;
                }
            } else {
                // Speech confirmed — monitor for silence
                if (smoothedRms > SPEECH_THRESHOLD) {
                    // Still clearly speaking, reset silence timer
                    silenceStart = null;
                } else if (!silenceStart) {
                    silenceStart = Date.now();
                } else if (Date.now() - silenceStart > SILENCE_DURATION) {
                    // Sustained drop below speech level — done speaking
                    this.stopListening();
                }
            }
        }, 100);
    }

    stopListening() {
        if (!this.isListening) return;

        this.isListening = false;
        if (this.onListeningChange) this.onListeningChange(false);

        if (this.silenceCheckInterval) {
            clearInterval(this.silenceCheckInterval);
            this.silenceCheckInterval = null;
        }

        if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
            this.mediaRecorder.stop(); // triggers onstop → handleRecordingComplete
        }

        if (this.stream) {
            this.stream.getTracks().forEach(track => track.stop());
            this.stream = null;
        }

        if (this.audioContext) {
            this.audioContext.close();
            this.audioContext = null;
            this.analyser = null;
        }
    }

    private async handleRecordingComplete() {
        if (this.audioChunks.length === 0) return;

        const mimeType = this.getSupportedMimeType();
        const audioBlob = new Blob(this.audioChunks, { type: mimeType });
        this.audioChunks = [];

        // Skip very short recordings (likely just noise)
        if (audioBlob.size < 1000) return;

        this.isTranscribing = true;
        if (this.onTranscribing) this.onTranscribing(true);

        try {
            const formData = new FormData();
            const extension = mimeType.includes('mp4') ? 'mp4' : mimeType.includes('ogg') ? 'ogg' : 'webm';
            formData.append('audio', audioBlob, `recording.${extension}`);

            const response = await fetch(`${API_URL}/stt`, {
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
            console.error('Whisper transcription error:', error);
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

        // Guard: ensure onStart fires exactly once
        let started = false;
        const fireStart = () => {
            if (started) return;
            started = true;
            if (onStart) onStart();
        };

        // Reveal text when audio is actually outputting sound (not just buffering)
        audio.addEventListener('playing', fireStart, { once: true });
        // Also reveal on pause — covers interruption via stopAudio()
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
}
