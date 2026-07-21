const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || '/api';

// Speech-end tuning, taken from SAIF's hands-free tutor surface, which has been
// through many iterations and fires reliably.
//
// The previous 500ms ended a learner's answer after half a second of pause.
// Someone reaching for a word in a second language pauses far longer than that,
// so extended answers were being cut off mid-sentence - the single most
// damaging failure available here, because it punishes exactly the production
// the app exists to elicit.
//
// SAIF's note on why this is generous: "so a mid-sentence pause to find a word
// isn't cut off. The 'finished' timer only starts once speech has been heard,
// so a learner who pauses to think BEFORE answering is never cut off." Silero's
// redemption window has the same semantics - it only runs after speech - so a
// long silence before they begin costs them nothing.
const SILENCE_MS = 2500;

// Backstop against a stuck mic in a noisy room, where the detector may never see
// silence. Timed from the moment SPEECH starts, not from the mic opening, so
// thinking time before answering is never counted - the learner may take as long
// as they like to begin. In effect: "you have been talking for 60 seconds
// without a 2.5s pause", which normal speech does not reach.
//
// Deliberately looser than SAIF's 25s. Theirs can afford to be tight because
// their cap still submits the audio it captured; Silero gives no way to flush
// speech in progress, so ours loses the utterance and must therefore only ever
// fire when something is genuinely broken.
const MAX_SPEECH_MS = 60000;

export class SpeechManager {
    private vad: any = null;
    private micStream: MediaStream | null = null;
    private vadReady: Promise<void> | null = null;
    private currentAudio: HTMLAudioElement | null = null;
    private maxListenTimer: ReturnType<typeof setTimeout> | null = null;
    private speechStartedAt: number = 0;
    isListening: boolean = false;
    isTranscribing: boolean = false;

    onResult: (text: string) => void;
    onError?: (error: string) => void;
    onListeningChange?: (listening: boolean) => void;
    onTranscribing?: (transcribing: boolean) => void;
    /** Fires true the moment speech is detected and false when it ends.
     *  The silence prompt needs this: "the mic is open" and "nobody is talking"
     *  are different things, and interrupting someone mid-sentence because a
     *  timer started when the mic opened is the worst thing this app can do. */
    onSpeechActivity?: (active: boolean) => void;

    constructor(
        onResult: (text: string) => void,
        onError?: (error: string) => void,
        onListeningChange?: (listening: boolean) => void,
        onTranscribing?: (transcribing: boolean) => void,
        onSpeechActivity?: (active: boolean) => void
    ) {
        this.onResult = onResult;
        this.onError = onError;
        this.onListeningChange = onListeningChange;
        this.onTranscribing = onTranscribing;
        this.onSpeechActivity = onSpeechActivity;
    }

    // Cached MicVAD constructor — loaded lazily on first use.
    private static _MicVAD: any = null;

    /** Fire-and-forget: warm up the dynamic import on mount so it's ready before first click. */
    static preload(): void {
        SpeechManager.loadMicVAD().catch(() => {});
    }

    /**
     * Acquire the mic MediaStream. Must be called within a browser user-gesture
     * (e.g. a click handler) for the first invocation. Subsequent calls are
     * no-ops — the stream is reused so permission is only requested once.
     */
    async acquireMicStream(): Promise<void> {
        if (this.micStream) return;
        this.micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    }

    private static async loadMicVAD(): Promise<any> {
        if (SpeechManager._MicVAD) return SpeechManager._MicVAD;
        // next.config.ts resolveAlias redirects onnxruntime-web → ort.min.js so
        // Turbopack bundles a single pre-built UMD file instead of creating
        // dynamic .mjs WASM-backend chunks that 404 in production.
        const { MicVAD } = await import("@ricky0123/vad-web");
        SpeechManager._MicVAD = MicVAD;
        return MicVAD;
    }

    private async _initVAD(): Promise<void> {
        const MicVAD = await SpeechManager.loadMicVAD();
        this.vad = await (MicVAD.new as any)({
            stream: this.micStream,   // pre-acquired — skips internal getUserMedia
            positiveSpeechThreshold: 0.5,
            negativeSpeechThreshold: 0.35,
            minSpeechMs: 250,
            redemptionMs: SILENCE_MS,
            preSpeechPadMs: 300,
            // Assets served from public/ (copied by prebuild script).
            workletURL: '/vad.worklet.bundle.min.js',
            modelURL: '/silero_vad_legacy.onnx',
            ortConfig: (ort: any) => {
                // WASM binaries served from public/; numThreads=1 avoids
                // SharedArrayBuffer so COEP is not required.
                ort.env.wasm.wasmPaths = '/';
                ort.env.wasm.numThreads = 1;
            },
            // The runaway guard is armed when speech actually begins, so a
            // learner can take as long as they need to gather their thoughts
            // before saying anything.
            onSpeechStart: () => {
                this.speechStartedAt = Date.now();
                console.info('[mic] speech started');
                this.armSpeechCap();
                if (this.onSpeechActivity) this.onSpeechActivity(true);
            },
            onSpeechEnd: (audio: Float32Array) => {
                const heldMs = Date.now() - (this.speechStartedAt || Date.now());
                console.info(`[mic] speech ended after ${heldMs}ms, ${audio.length} samples`);
                this.clearSpeechCap();
                if (this.onSpeechActivity) this.onSpeechActivity(false);
                this.handleSpeechEnd(audio);
            },
            // The VAD decided the speech was too short to be real and threw the
            // audio away. Without this handler that happens silently, and the
            // learner sees a recording light, no transcript, and detectives
            // carrying on as though they had said nothing.
            onVADMisfire: () => {
                const heldMs = Date.now() - (this.speechStartedAt || Date.now());
                console.warn(`[mic] VAD MISFIRE - audio discarded after ${heldMs}ms `
                    + `(shorter than minSpeechMs). Nothing was sent.`);
                this.clearSpeechCap();
                if (this.onSpeechActivity) this.onSpeechActivity(false);
                if (this.onError) this.onError("Didn't catch that — try again, a little longer.");
            },
        });
    }

    async startListening() {
        if (this.isListening) return;
        this.stopAudio();

        try {
            // Phase 1 — must run within a user gesture for the first call.
            // acquireMicStream() is a no-op on subsequent calls (stream cached).
            await this.acquireMicStream();

            // Phase 2 — async VAD init; gesture context not required because
            // the MediaStream was already acquired above.
            if (!this.vad) {
                if (!this.vadReady) this.vadReady = this._initVAD();
                await this.vadReady;
                this.vadReady = null;
            }

            this.vad.start();
            this.isListening = true;
            if (this.onListeningChange) this.onListeningChange(true);
        } catch (error) {
            console.error('VAD initialization error:', error);
            if (this.onError) {
                const isPermissionError =
                    error instanceof DOMException &&
                    (error.name === 'NotAllowedError' || error.name === 'PermissionDeniedError');
                this.onError(
                    isPermissionError
                        ? 'Microphone access denied. Please allow microphone access and try again.'
                        : 'Microphone could not be started. Please check browser permissions and reload.'
                );
            }
        }
    }

    private armSpeechCap() {
        this.clearSpeechCap();
        this.maxListenTimer = setTimeout(() => {
            if (!this.isListening) return;
            console.warn('Mic ran past the safety cap while speech was still detected.');
            this.stopListening();
            if (this.onError) {
                this.onError('Microphone stopped. Press MIC to carry on.');
            }
        }, MAX_SPEECH_MS);
    }

    private clearSpeechCap() {
        if (this.maxListenTimer) {
            clearTimeout(this.maxListenTimer);
            this.maxListenTimer = null;
        }
    }

    stopListening() {
        this.clearSpeechCap();
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

        // Skip very short audio (< 100ms at 16kHz = noise). Logged, because a
        // silent drop here is indistinguishable to the learner from a broken mic.
        if (audio.length < 1600) {
            console.warn(`[mic] discarded ${audio.length} samples as too short to be speech`);
            return;
        }

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
            console.info(`[mic] transcript: ${JSON.stringify(data.text ?? '')}`);

            if (data.text && data.text.trim()) {
                this.onResult(data.text.trim());
            } else {
                // Whisper heard nothing usable. Say so rather than leaving them
                // staring at a recording light that produced no result.
                console.warn('[mic] STT returned an empty transcript');
                if (this.onError) this.onError("Didn't catch that — try again.");
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

        // Only take the MediaSource path when the response really is MP3. The local
        // Kokoro sidecar returns a complete audio/wav, which MediaSource cannot
        // buffer — feeding WAV bytes into an audio/mpeg SourceBuffer just fails.
        const contentType = response.headers.get('content-type') || '';
        const canStream = contentType.includes('audio/mpeg')
            && typeof MediaSource !== 'undefined'
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
        if (this.micStream) {
            this.micStream.getTracks().forEach(t => t.stop());
            this.micStream = null;
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
