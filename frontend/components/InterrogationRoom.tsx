"use client";

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { SpeechManager } from '../lib/speech';
import BriefPanel from './BriefPanel';
import BriefingScreen from './BriefingScreen';
import { getInterview, sendMessage, type Modality, type Utterance } from '../lib/api';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || '/api';

/** Shown when a detective's line arrives with no audio behind it.
 *
 *  Held as a constant so it can be cleared again without wiping a microphone
 *  message out of the same slot: the two subsystems share one error line, and
 *  audio recovering says nothing about whether the mic is working. */
const TTS_SILENT = "The detectives' voices aren't coming through — their words are still on screen.";

interface Message {
    role: 'user' | 'agent';
    content: string;
    agentName?: string;
    emotion?: string;
    phase?: string;
    turn?: number;
    /** "partner" means the detectives were talking to each other about the
     *  learner rather than to them - rendered differently so they can see it. */
    addressedTo?: string;
    /** Groups the two halves of an aside. */
    exchangeId?: string;
}

interface Props {
    interviewId: string;
    /** Resuming an existing interview replays its transcript instead of
     *  opening with the standard first line. */
    resume: boolean;
    onExit: () => void;
}

export default function InterrogationRoom({ interviewId, resume, onExit }: Props) {
    const [messages, setMessages] = useState<Message[]>([]);
    const [isListening, setIsListening] = useState(false);
    const [isTranscribing, setIsTranscribing] = useState(false);
    const [inputText, setInputText] = useState("");
    const [errorMsg, setErrorMsg] = useState<string | null>(null);
    const [isWaiting, setIsWaiting] = useState(false);
    const [isSpeaking, setIsSpeaking] = useState(false);
    const [currentPhase, setCurrentPhase] = useState("engage");
    const [hasStarted, setHasStarted] = useState(false);
    const [briefed, setBriefed] = useState(false);
    const [outcome, setOutcome] = useState<string | null>(null);
    // Set from the outcome card's "Read the transcript" button. A concluded
    // interview must be re-readable (the picker offers "Review"); without this
    // the outcome card shadowed the loaded transcript and it was unreachable.
    const [reviewing, setReviewing] = useState(false);
    const speechManager = useRef<SpeechManager | null>(null);
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const silenceTimer = useRef<NodeJS.Timeout | null>(null);
    // True while the learner is actually speaking. A ref rather than state so
    // the silence timer reads it without needing to be re-created.
    const speechActive = useRef(false);

    const handleSendMessageRef = useRef<(text?: string, modality?: Modality) => Promise<void>>(async () => { });

    // Fetch TTS audio from backend and play it via streaming
    // onStart fires when audio actually begins playing (for syncing text reveal)
    const playAgentAudio = useCallback(async (
        segments: { text: string; voice: string }[],
        onEnd?: () => void, onStart?: () => void,
    ) => {
        // Every route out of here without audio now says which one it took. A
        // line appearing in silence looks identical whether the sidecar is down,
        // the backend is unreachable or playback was skipped on purpose - the
        // same ambiguity the microphone had until it was made to explain itself.
        // `tellThem` is false for the one case that is not a fault.
        const noAudio = (why: string, tellThem = true) => {
            console.warn(`[tts] ${why}`);
            if (tellThem) setErrorMsg(TTS_SILENT);
            setIsSpeaking(false);
            if (onStart) onStart();
            if (onEnd) onEnd();
        };

        try {
            setIsSpeaking(true);
            // An aside is two speakers. The backend renders them into a single
            // wav, so playback here is identical to a single line - no
            // sequencing, and the halves cannot arrive out of order.
            const response = await fetch(`${BACKEND_URL}/tts`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(
                    segments.length > 1
                        ? { segments }
                        : { text: segments[0]?.text ?? '', voice: segments[0]?.voice ?? 'Reynolds' }),
            });

            if (!response.ok) {
                // 502 here is almost always the Kokoro sidecar being down rather
                // than anything wrong with the request.
                return noAudio(`backend returned ${response.status} for this line`
                    + (response.status === 502 ? ' - is the TTS sidecar on 7678 up?' : ''));
            }

            // Not a fault: they started talking while it was loading, and talking
            // over them is worse than staying quiet.
            if (speechManager.current?.isListening) {
                return noAudio('learner began speaking while audio loaded - skipped deliberately',
                               false);
            }

            if (!speechManager.current) {
                return noAudio('no speech manager on this component - nothing can play');
            }

            // Audio is flowing again. Clear only our own message, so a microphone
            // warning sharing this slot is not silently wiped.
            setErrorMsg(prev => (prev === TTS_SILENT ? null : prev));
            await speechManager.current.playStreamingAudio(response, () => {
                setIsSpeaking(false);
                if (onEnd) onEnd();
            }, () => {
                if (onStart) onStart();
            });
        } catch (error) {
            noAudio(`could not reach ${BACKEND_URL}/tts: ${error}`);
        }
    }, []);

    const autoStartMic = useCallback(() => {
        if (speechManager.current) {
            speechManager.current.startListening();
        }
    }, []);

    const resetSilenceTimer = useCallback(() => {
        if (silenceTimer.current) clearTimeout(silenceTimer.current);

        // Never arm it while they are mid-sentence. An open microphone is not
        // the same as a silent room, and prompting over someone who is talking
        // discards what they said and answers as though they had said nothing.
        if (isListening && !speechActive.current) {
            // 4-8s. The research puts the point where silence starts to bite at
            // about four seconds, and the project's own design doc specifies
            // random(4,8). The previous 12-20s left a learner floundering in
            // dead air for the better part of twenty seconds before anyone
            // helped, which reads as abandonment rather than pressure.
            const delay = 4000 + Math.random() * 4000;
            silenceTimer.current = setTimeout(() => {
                handleSilenceTrigger();
            }, delay);
        }
    }, [isListening]);

    const handleSilenceTrigger = async () => {
        if (inputText.length > 0) return;
        // Last line of defence: they started talking between the timer being
        // armed and it firing.
        if (speechActive.current) return;

        try {
            if (speechManager.current && isListening) {
                speechManager.current.stopListening();
            }

            setIsWaiting(true);

            // Logged as 'silence' rather than a learner utterance so the
            // post-session assessment does not read it as production.
            const data = await sendMessage(interviewId, "[SILENCE]", 'silence');
            receive(data.utterances, data.phase, data.turn, data.outcome ?? null,
                    autoStartMic);
        } catch (error) {
            console.error("Error sending silence trigger:", error);
            setIsWaiting(false);
        }
    };

    /** Show and speak a reply, which is one utterance or - for an aside - two. */
    const receive = (
        utterances: Utterance[], phase: string, turn: number,
        newOutcome: string | null, onEnd?: () => void,
    ) => {
        if (phase) setCurrentPhase(phase);

        const exchangeId = utterances.length > 1 ? `x-${Date.now()}` : undefined;
        const msgs: Message[] = utterances.map(u => ({
            role: 'agent',
            content: u.text,
            agentName: u.speaker,
            emotion: u.emotion ?? undefined,
            phase, turn,
            addressedTo: u.addressed_to,
            exchangeId,
        }));

        const segments = utterances.map(u => ({ text: u.text, voice: u.speaker }));

        // Hold the text until audio starts, so eyes and ears stay together.
        playAgentAudio(segments, () => {
            if (newOutcome) setOutcome(newOutcome);
            if (onEnd && !newOutcome) onEnd();
        }, () => {
            setMessages(prev => [...prev, ...msgs]);
            setIsWaiting(false);
        });
    };

    const handleSendMessage = async (textOverride?: string, modality: Modality = 'typed') => {
        const textToSend = textOverride || inputText;
        if (!textToSend.trim()) return;

        if (speechManager.current) {
            speechManager.current.stopListening();
            speechManager.current.stopAudio();
            setIsSpeaking(false);
        }

        const userMsg: Message = { role: 'user', content: textToSend };
        setMessages(prev => [...prev, userMsg]);
        setInputText("");
        setIsWaiting(true);

        try {
            const data = await sendMessage(interviewId, textToSend, modality);
            receive(data.utterances, data.phase, data.turn, data.outcome ?? null,
                    autoStartMic);
        } catch (error) {
            console.error("Error sending message:", error);
            setIsWaiting(false);
            setErrorMsg("Connection to server failed. Is the backend running?");
        }
    };

    useEffect(() => {
        handleSendMessageRef.current = handleSendMessage;
    }, [handleSendMessage]);

    useEffect(() => {
        speechManager.current = new SpeechManager(
            // onResult — Whisper transcription complete, auto-send
            (text) => {
                setInputText("");
                setErrorMsg(null);
                resetSilenceTimer();
                if (text.trim().length > 0) {
                    // Came back from Whisper, so this turn was spoken. That
                    // distinction is what earns speaking credit later.
                    handleSendMessageRef.current(text, 'spoken');
                }
            },
            // onError
            (error) => {
                if (error.startsWith("Audio")) {
                    setErrorMsg(error);
                } else {
                    setErrorMsg(error);
                    setIsListening(false);
                }
            },
            // onListeningChange — mic state changed
            (listening) => {
                setIsListening(listening);
            },
            // onTranscribing — Whisper is processing
            (transcribing) => {
                setIsTranscribing(transcribing);
            },
            // onSpeechActivity — they have started or stopped talking.
            // Starting cancels any pending silence prompt outright; a learner
            // who is mid-sentence must never be talked over.
            (active) => {
                speechActive.current = active;
                if (active && silenceTimer.current) {
                    clearTimeout(silenceTimer.current);
                    silenceTimer.current = null;
                }
            }
        );

        // Pre-fetch the CDN bundle so it's cached before the user clicks MIC.
        SpeechManager.preload();

        return () => {
            if (silenceTimer.current) clearTimeout(silenceTimer.current);
            speechManager.current?.destroy();
        };
    }, []);

    /** The detectives' opening line. Deferred until after the briefing, so the
     *  learner is not read their brief and questioned in the same breath. */
    const beginInterrogation = useCallback(() => {
        setBriefed(true);
        const openingMsg: Message = {
            role: 'agent',
            content: "Have a seat. State your full name for the record, please.",
            agentName: 'Reynolds',
            emotion: 'measured',
        };
        setIsWaiting(true);
        setTimeout(() => {
            playAgentAudio([{ text: openingMsg.content, voice: 'Reynolds' }], undefined, () => {
                setMessages([openingMsg]);
                setIsWaiting(false);
            });
        }, 300);
    }, [playAgentAudio]);

    // Start the interview after user clicks — this unlocks audio in the browser
    const startInterview = useCallback(async () => {
        setHasStarted(true);

        if (resume) {
            // Set BEFORE the await. Otherwise the briefing screen mounts during
            // the transcript load and starts reading the brief aloud over the
            // top of the detective.
            setBriefed(true);

            // Replay what was already said rather than reopening. No audio:
            // the learner is picking up a thread, not being greeted again.
            setIsWaiting(true);
            try {
                const detail = await getInterview(interviewId);
                setMessages(detail.turns.map((t) => ({
                    role: t.role === 'user' ? 'user' : 'agent',
                    content: t.text,
                    agentName: t.agent_name ?? undefined,
                    emotion: t.emotion ?? undefined,
                    phase: t.phase ?? undefined,
                    addressedTo: t.addressed_to ?? 'learner',
                    exchangeId: t.exchange_id ?? undefined,
                })));
                if (detail.phase) setCurrentPhase(detail.phase);
                if (detail.outcome) setOutcome(detail.outcome);
            } catch {
                setErrorMsg("Could not load this interview.");
            } finally {
                setIsWaiting(false);
            }
            return;
        }
        // A new interview goes to the briefing screen; beginInterrogation()
        // runs when they say they are ready.
    }, [resume, interviewId]);

    useEffect(() => {
        resetSilenceTimer();
    }, [messages, isListening]);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages]);

    const toggleListening = async () => {
        if (!speechManager.current) return;

        if (isListening) {
            speechManager.current.stopListening();
        } else {
            // Allow interrupting AI speech to start recording
            if (isSpeaking) setIsSpeaking(false);
            // acquireMicStream() MUST be awaited here, inside the click handler,
            // so getUserMedia() fires while the browser gesture context is still valid.
            await speechManager.current.acquireMicStream();
            speechManager.current.startListening();
        }
    };

    const getAgentColor = (agentName?: string) => {
        if (agentName === 'Reynolds') return 'var(--amber)';
        if (agentName === 'Chen') return 'var(--teal)';
        return 'var(--text-secondary)';
    };

    const getAgentBorderColor = (agentName?: string) => {
        if (agentName === 'Reynolds') return 'var(--amber-dim)';
        if (agentName === 'Chen') return 'var(--teal-dim)';
        return 'var(--border)';
    };

    // Mic button label
    const getMicLabel = () => {
        if (isTranscribing) return '...';
        if (isListening) return 'ON';
        return 'MIC';
    };

    const getMicStyle = () => {
        if (isTranscribing) return {
            background: 'rgba(212, 170, 54, 0.15)',
            border: '1px solid var(--amber)',
            color: 'var(--amber)'
        };
        if (isListening) return {
            background: 'rgba(212, 54, 74, 0.15)',
            border: '1px solid var(--red-accent)',
            color: 'var(--red-accent)'
        };
        return {
            background: 'var(--surface-raised)',
            border: '1px solid var(--border-bright)',
            color: 'var(--text-secondary)'
        };
    };

    // Pre-interview start screen
    if (!hasStarted) {
        return (
            <div
                className="flex flex-col h-screen items-center justify-center"
                style={{ background: 'var(--background)', color: 'var(--text-primary)' }}
            >
                <div className="scanline-overlay" />
                <div className="text-center space-y-6">
                    <h1
                        className="text-sm font-bold tracking-widest font-mono uppercase"
                        style={{ color: 'var(--teal)' }}
                    >
                        Interview Room A
                    </h1>
                    <p className="text-xs font-mono" style={{ color: 'var(--text-muted)' }}>
                        Metropolitan Police — Major Crimes
                    </p>
                    <button
                        onClick={startInterview}
                        className="mt-8 px-8 py-3 rounded-lg font-bold text-sm tracking-wider transition-all font-mono uppercase"
                        style={{
                            background: 'var(--teal-dim)',
                            border: '1px solid var(--teal)',
                            color: 'var(--teal)',
                        }}
                    >
                        {resume ? 'Resume Interview' : 'Begin Interview'}
                    </button>
                    <p className="text-xs font-mono mt-4" style={{ color: 'var(--text-muted)' }}>
                        Click to enable audio and microphone
                    </p>
                    <button
                        onClick={onExit}
                        className="block mx-auto text-xs font-mono mt-2"
                        style={{ color: 'var(--text-muted)' }}
                    >
                        ← Back to interviews
                    </button>
                </div>
            </div>
        );
    }

    // Read them their brief first, with nothing else happening. Previously this
    // appeared at the same moment the first question did, so there was no chance
    // to take it in.
    if (!briefed) {
        return <BriefingScreen interviewId={interviewId} onReady={beginInterrogation} />;
    }

    // The interview has concluded. Show the verdict card first; "Read the
    // transcript" drops through to the normal view (with the outcome as a banner
    // and no input) so a finished interview can actually be re-read.
    if (outcome && !reviewing) {
        const copy: Record<string, { title: string; line: string; colour: string }> = {
            released: {
                title: 'Released',
                line: 'Your account held. You are free to go, with thanks for your time.',
                colour: 'var(--teal)',
            },
            under_investigation: {
                title: 'Released under investigation',
                line: 'You are free to go for now. Enquiries are continuing, and they will want to speak to you again.',
                colour: 'var(--amber)',
            },
            detained: {
                title: 'Detained',
                line: 'Your account did not survive what they had. You are not going home tonight.',
                colour: 'var(--red-accent)',
            },
        };
        const o = copy[outcome] ?? copy.under_investigation;
        return (
            <div className="flex flex-col h-screen items-center justify-center px-6"
                style={{ background: 'var(--background)', color: 'var(--text-primary)' }}>
                <div className="scanline-overlay" />
                <div className="text-center max-w-md space-y-4">
                    <p className="text-xs font-mono uppercase tracking-widest"
                        style={{ color: 'var(--text-muted)' }}>
                        Interview concluded
                    </p>
                    <h1 className="text-lg font-bold tracking-widest font-mono uppercase"
                        style={{ color: o.colour }}>
                        {o.title}
                    </h1>
                    <p className="text-sm font-mono leading-relaxed"
                        style={{ color: 'var(--text-secondary)' }}>
                        {o.line}
                    </p>
                    <div className="flex items-center justify-center gap-3 mt-6">
                        <button
                            onClick={() => setReviewing(true)}
                            className="px-6 py-3 rounded-lg font-bold text-sm tracking-wider font-mono uppercase"
                            style={{
                                background: 'var(--surface-raised)',
                                border: '1px solid var(--border-bright)',
                                color: 'var(--text-secondary)',
                            }}
                        >
                            Read the transcript
                        </button>
                        <button
                            onClick={onExit}
                            className="px-6 py-3 rounded-lg font-bold text-sm tracking-wider font-mono uppercase"
                            style={{
                                background: 'var(--surface-raised)',
                                border: '1px solid var(--border-bright)',
                                color: 'var(--text-secondary)',
                            }}
                        >
                            Back to interviews
                        </button>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="flex flex-col h-screen" style={{ background: 'var(--background)', color: 'var(--text-primary)' }}>
            {/* Scanline effect */}
            <div className="scanline-overlay" />

            {/* Header */}
            <div
                className="px-5 py-3 flex justify-between items-center"
                style={{
                    background: 'var(--surface)',
                    borderBottom: '1px solid var(--border)'
                }}
            >
                <div className="flex items-center gap-4">
                    <button
                        onClick={onExit}
                        title="Back to interviews — this interview is saved"
                        className="text-xs font-mono px-2 py-1 rounded"
                        style={{ color: 'var(--text-muted)', border: '1px solid var(--border)' }}
                    >
                        ←
                    </button>
                    <h1
                        className="text-sm font-bold tracking-widest font-mono uppercase"
                        style={{ color: 'var(--teal)' }}
                    >
                        Interview Room A
                    </h1>
                    <span
                        className="text-xs font-mono"
                        style={{ color: 'var(--text-muted)' }}
                    >
                        Metropolitan Police — Major Crimes
                    </span>
                </div>
                <div className="flex items-center gap-3">
                    <span
                        className="text-xs font-mono px-2 py-0.5 rounded"
                        style={{
                            color: 'var(--amber)',
                            background: 'var(--amber-glow)',
                            border: '1px solid var(--amber-dim)'
                        }}
                    >
                        {currentPhase.replace(/_/g, ' ').toUpperCase()}
                    </span>
                    <div className="flex items-center gap-1.5">
                        <span
                            className="w-2 h-2 rounded-full rec-pulse"
                            style={{ background: 'var(--red-accent)' }}
                        />
                        <span className="text-xs font-mono" style={{ color: 'var(--text-muted)' }}>
                            REC
                        </span>
                    </div>
                </div>
            </div>

            {/* The learner's own brief, within reach throughout */}
            <BriefPanel interviewId={interviewId} />

            {/* Reviewing a concluded interview: the verdict as a banner over the
                transcript, which stays fully readable below. */}
            {outcome && (
                <div className="px-5 py-2 flex items-center justify-between gap-3"
                    style={{ background: 'var(--surface)', borderBottom: '1px solid var(--border)' }}>
                    <span className="text-xs font-mono uppercase tracking-widest"
                        style={{
                            color: outcome === 'released' ? 'var(--teal)'
                                : outcome === 'detained' ? 'var(--red-accent)' : 'var(--amber)',
                        }}>
                        Concluded · {outcome.replace(/_/g, ' ')}
                    </span>
                    <button
                        onClick={onExit}
                        className="text-xs font-mono px-2 py-1 rounded"
                        style={{ color: 'var(--text-muted)', border: '1px solid var(--border)' }}>
                        Back to interviews
                    </button>
                </div>
            )}

            {/* Chat Area */}
            <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
                {messages.map((msg, idx) => (
                    <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                        {msg.role === 'user' ? (
                            <div
                                className="max-w-2xl px-4 py-3 rounded-lg rounded-br-none"
                                style={{
                                    background: 'var(--surface-raised)',
                                    border: '1px solid var(--border-bright)',
                                    color: 'var(--text-primary)'
                                }}
                            >
                                <p className="text-base leading-relaxed">{msg.content}</p>
                            </div>
                        ) : (
                            <div
                                className={`max-w-2xl px-4 py-3 rounded-lg ${msg.addressedTo === 'partner' ? 'ml-8' : 'rounded-bl-none'}`}
                                style={msg.addressedTo === 'partner' ? {
                                    // They are being talked ABOUT, not to. Recessed and
                                    // dashed so it reads as overheard across the table.
                                    background: 'transparent',
                                    border: '1px dashed var(--border-bright)',
                                    opacity: 0.85,
                                } : {
                                    background: 'var(--surface)',
                                    borderLeft: `3px solid ${getAgentBorderColor(msg.agentName)}`,
                                    borderTop: '1px solid var(--border)',
                                    borderRight: '1px solid var(--border)',
                                    borderBottom: '1px solid var(--border)'
                                }}
                            >
                                <div className="flex justify-between items-center mb-2">
                                    <div className="flex items-center gap-2">
                                        <span
                                            className="text-xs font-bold font-mono uppercase tracking-wider"
                                            style={{ color: getAgentColor(msg.agentName) }}
                                        >
                                            {msg.agentName === 'Reynolds' ? 'DI Reynolds' : msg.agentName === 'Chen' ? 'DS Chen' : msg.agentName}
                                        </span>
                                        {msg.addressedTo === 'partner' && (
                                            <span className="text-xs font-mono italic"
                                                style={{ color: 'var(--text-muted)' }}>
                                                — not to you —
                                            </span>
                                        )}
                                        {msg.emotion && msg.addressedTo !== 'partner' && (
                                            <span
                                                className="text-xs font-mono"
                                                style={{ color: 'var(--text-muted)' }}
                                            >
                                                [{msg.emotion}]
                                            </span>
                                        )}
                                    </div>
                                    <button
                                        onClick={() => {
                                            playAgentAudio([{ text: msg.content, voice: msg.agentName || 'Reynolds' }]);
                                        }}
                                        className="text-xs px-2 py-0.5 rounded transition-colors font-mono"
                                        style={{
                                            color: 'var(--text-muted)',
                                            background: 'transparent',
                                            border: '1px solid var(--border)'
                                        }}
                                        title="Replay audio"
                                    >
                                        PLAY
                                    </button>
                                </div>
                                <p className="text-base leading-relaxed"
                                    style={{
                                        color: msg.addressedTo === 'partner'
                                            ? 'var(--text-secondary)' : 'var(--text-primary)',
                                        fontStyle: msg.addressedTo === 'partner' ? 'italic' : 'normal',
                                    }}>
                                    {msg.content}
                                </p>
                            </div>
                        )}
                    </div>
                ))}

                {/* Waiting indicator */}
                {isWaiting && (
                    <div className="flex justify-start">
                        <div
                            className="px-4 py-3 rounded-lg"
                            style={{
                                background: 'var(--surface)',
                                border: '1px solid var(--border)'
                            }}
                        >
                            <div className="flex items-center gap-1">
                                <span className="typing-dot" />
                                <span className="typing-dot" />
                                <span className="typing-dot" />
                            </div>
                        </div>
                    </div>
                )}

                <div ref={messagesEndRef} />
            </div>

            {/* Input Area - hidden once the interview has concluded; a finished
                interview is read-only, and a send would 409. */}
            {!outcome && (
            <div
                className="px-5 py-3"
                style={{
                    background: 'var(--surface)',
                    borderTop: '1px solid var(--border)'
                }}
            >
                {errorMsg && (
                    <div
                        className="mb-2 px-3 py-2 rounded text-sm text-center font-mono"
                        style={{
                            background: 'rgba(212, 54, 74, 0.1)',
                            border: '1px solid var(--red-accent)',
                            color: 'var(--red-accent)'
                        }}
                    >
                        {errorMsg}
                    </div>
                )}
                <div className="flex items-center gap-2 max-w-4xl mx-auto">
                    <button
                        onClick={toggleListening}
                        disabled={isTranscribing || isWaiting}
                        className="w-11 h-11 rounded-lg flex items-center justify-center transition-all font-mono text-sm"
                        style={{
                            ...getMicStyle(),
                            opacity: (isTranscribing || isWaiting) ? 0.5 : 1
                        }}
                        title={isTranscribing ? "Transcribing..." : isListening ? "Stop listening" : "Start listening"}
                    >
                        {getMicLabel()}
                    </button>

                    <input
                        type="text"
                        value={inputText}
                        onChange={(e) => setInputText(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
                        className="flex-1 rounded-lg px-4 py-2.5 text-base focus:outline-none font-mono"
                        style={{
                            background: 'var(--background)',
                            border: '1px solid var(--border-bright)',
                            color: 'var(--text-primary)'
                        }}
                        placeholder={isTranscribing ? "Transcribing..." : isListening ? "Recording..." : "Respond..."}
                        disabled={isWaiting || isSpeaking || isListening}
                    />

                    <button
                        onClick={() => handleSendMessage()}
                        disabled={isWaiting || isSpeaking || !inputText.trim() || isListening}
                        className="px-5 py-2.5 rounded-lg font-bold text-sm tracking-wider transition-all font-mono"
                        style={{
                            background: inputText.trim() ? 'var(--teal-dim)' : 'var(--surface-raised)',
                            border: `1px solid ${inputText.trim() ? 'var(--teal)' : 'var(--border)'}`,
                            color: inputText.trim() ? 'var(--teal)' : 'var(--text-muted)',
                            opacity: (isWaiting || isSpeaking || isListening) ? 0.5 : 1
                        }}
                    >
                        SEND
                    </button>
                </div>
            </div>
            )}
        </div>
    );
}
