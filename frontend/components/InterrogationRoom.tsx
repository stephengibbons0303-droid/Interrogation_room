"use client";

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { SpeechManager } from '../lib/speech';
import { getInterview, sendMessage, type Modality } from '../lib/api';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || '/api';

interface Message {
    role: 'user' | 'agent';
    content: string;
    agentName?: string;
    emotion?: string;
    phase?: string;
    turn?: number;
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
    const [currentPhase, setCurrentPhase] = useState("ORIENTATION");
    const [hasStarted, setHasStarted] = useState(false);
    const speechManager = useRef<SpeechManager | null>(null);
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const silenceTimer = useRef<NodeJS.Timeout | null>(null);

    const handleSendMessageRef = useRef<(text?: string, modality?: Modality) => Promise<void>>(async () => { });

    // Fetch TTS audio from backend and play it via streaming
    // onStart fires when audio actually begins playing (for syncing text reveal)
    const playAgentAudio = useCallback(async (text: string, agentName: string, onEnd?: () => void, onStart?: () => void) => {
        try {
            setIsSpeaking(true);
            const response = await fetch(`${BACKEND_URL}/tts`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text, voice: agentName }),
            });

            if (!response.ok) {
                console.warn("TTS endpoint returned", response.status, "- skipping audio");
                setIsSpeaking(false);
                if (onStart) onStart();
                if (onEnd) onEnd();
                return;
            }

            // If user started recording while TTS was loading, don't play over them
            if (speechManager.current?.isListening) {
                setIsSpeaking(false);
                if (onStart) onStart();
                if (onEnd) onEnd();
                return;
            }

            if (speechManager.current) {
                await speechManager.current.playStreamingAudio(response, () => {
                    setIsSpeaking(false);
                    if (onEnd) onEnd();
                }, () => {
                    if (onStart) onStart();
                });
            } else {
                setIsSpeaking(false);
                if (onStart) onStart();
                if (onEnd) onEnd();
            }
        } catch (error) {
            console.error("TTS fetch error:", error);
            setIsSpeaking(false);
            if (onStart) onStart();
            if (onEnd) onEnd();
        }
    }, []);

    const autoStartMic = useCallback(() => {
        if (speechManager.current) {
            speechManager.current.startListening();
        }
    }, []);

    const resetSilenceTimer = useCallback(() => {
        if (silenceTimer.current) clearTimeout(silenceTimer.current);

        if (isListening) {
            const delay = 12000 + Math.random() * 8000;
            silenceTimer.current = setTimeout(() => {
                handleSilenceTrigger();
            }, delay);
        }
    }, [isListening]);

    const handleSilenceTrigger = async () => {
        if (inputText.length > 0) return;

        try {
            if (speechManager.current && isListening) {
                speechManager.current.stopListening();
            }

            setIsWaiting(true);

            // Logged as 'silence' rather than a learner utterance so the
            // post-session assessment does not read it as production.
            const data = await sendMessage(interviewId, "[SILENCE]", 'silence');

            if (data.phase) setCurrentPhase(data.phase);

            const agentMsg: Message = {
                role: 'agent',
                content: data.text,
                agentName: data.agent,
                emotion: data.emotion ?? undefined,
                phase: data.phase,
                turn: data.turn
            };

            playAgentAudio(agentMsg.content, data.agent, autoStartMic, () => {
                setMessages(prev => [...prev, agentMsg]);
                setIsWaiting(false);
            });
        } catch (error) {
            console.error("Error sending silence trigger:", error);
            setIsWaiting(false);
        }
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

            if (data.phase) setCurrentPhase(data.phase);

            const agentMsg: Message = {
                role: 'agent',
                content: data.text,
                agentName: data.agent,
                emotion: data.emotion ?? undefined,
                phase: data.phase,
                turn: data.turn
            };

            // Hold text until audio starts playing — keeps eyes and ears in sync
            playAgentAudio(agentMsg.content, data.agent, autoStartMic, () => {
                setMessages(prev => [...prev, agentMsg]);
                setIsWaiting(false);
            });

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
            }
        );

        // Pre-fetch the CDN bundle so it's cached before the user clicks MIC.
        SpeechManager.preload();

        return () => {
            if (silenceTimer.current) clearTimeout(silenceTimer.current);
            speechManager.current?.destroy();
        };
    }, []);

    // Start the interview after user clicks — this unlocks audio in the browser
    const startInterview = useCallback(async () => {
        setHasStarted(true);

        if (resume) {
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
                })));
                if (detail.phase) setCurrentPhase(detail.phase);
            } catch {
                setErrorMsg("Could not load this interview.");
            } finally {
                setIsWaiting(false);
            }
            return;
        }

        const openingMsg: Message = {
            role: 'agent',
            content: "Have a seat. State your full name for the record, please.",
            agentName: 'Reynolds',
            emotion: 'measured'
        };
        setIsWaiting(true);

        setTimeout(() => {
            playAgentAudio(openingMsg.content, 'Reynolds', undefined, () => {
                setMessages([openingMsg]);
                setIsWaiting(false);
            });
        }, 300);
    }, [playAgentAudio, resume, interviewId]);

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
                        {currentPhase}
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
                                className="max-w-2xl px-4 py-3 rounded-lg rounded-bl-none"
                                style={{
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
                                        {msg.emotion && (
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
                                            playAgentAudio(msg.content, msg.agentName || 'Reynolds');
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
                                <p className="text-base leading-relaxed" style={{ color: 'var(--text-primary)' }}>
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

            {/* Input Area */}
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
        </div>
    );
}
