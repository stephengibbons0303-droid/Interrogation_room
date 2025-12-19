"use client";

import React, { useState, useEffect, useRef } from 'react';
import { SpeechManager } from '../lib/speech';

interface Message {
    role: 'user' | 'agent';
    content: string;
    agentName?: string;
    emotion?: string;
}

export default function InterrogationRoom() {
    const [messages, setMessages] = useState<Message[]>([]);
    const [isListening, setIsListening] = useState(false);
    const [inputText, setInputText] = useState("");
    const [errorMsg, setErrorMsg] = useState<string | null>(null);
    const speechManager = useRef<SpeechManager | null>(null);
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const silenceTimer = useRef<NodeJS.Timeout | null>(null);

    // Ref to access the latest function from within the SpeechManager closure
    const handleSendMessageRef = useRef<(text?: string) => Promise<void>>(async () => { });

    // Reset silence timer on any activity
    const resetSilenceTimer = () => {
        if (silenceTimer.current) clearTimeout(silenceTimer.current);

        // Only start timer if WE ARE listening (user's turn)
        if (isListening) {
            silenceTimer.current = setTimeout(() => {
                handleSilenceTrigger();
            }, 10000); // 10 seconds
        }
    };

    const handleSilenceTrigger = async () => {
        console.log("Silence trigger activated");
        if (inputText.length > 0) return;

        try {
            // Stop listening if silence triggers
            if (speechManager.current && isListening) {
                speechManager.current.stopListening();
                setIsListening(false);
            }

            const response = await fetch('http://localhost:8000/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: "[SILENCE]",
                    session_id: "test-session"
                }),
            });

            if (!response.ok) throw new Error('Network response was not ok');
            const data = await response.json();

            const agentMsg: Message = {
                role: 'agent',
                content: data.response || data.text,
                agentName: data.agent,
                emotion: data.emotion
            };

            setMessages(prev => [...prev, agentMsg]);

            if (speechManager.current) {
                const isReynolds = data.agent === 'Reynolds';
                const voice = isReynolds ? 'Male' : 'Female';
                const options = isReynolds ? { pitch: 0.7, rate: 1.1 } : { pitch: 1.1, rate: 0.95 };

                speechManager.current.speak(agentMsg.content, voice, options, () => {
                    // Auto-Start listening when agent finishes speaking (Silence response)
                    console.log("Agent finished (silence), auto-starting mic...");
                    if (speechManager.current) {
                        speechManager.current.startListening();
                        setIsListening(true);
                    }
                });
            }
        } catch (error) {
            console.error("Error sending silence trigger:", error);
        }
    };

    // Main Message Handler
    const handleSendMessage = async (textOverride?: string) => {
        const textToSend = textOverride || inputText;
        if (!textToSend.trim()) return;

        // Auto-Stop listening when user sends message
        if (speechManager.current) {
            speechManager.current.stopListening();
            setIsListening(false);
        }

        const userMsg: Message = { role: 'user', content: textToSend };
        setMessages(prev => [...prev, userMsg]);
        setInputText("");

        try {
            const response = await fetch('http://localhost:8000/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: textToSend,
                    session_id: "test-session"
                }),
            });

            if (!response.ok) throw new Error('Network response was not ok');
            const data = await response.json();

            const agentMsg: Message = {
                role: 'agent',
                content: data.response || data.text,
                agentName: data.agent,
                emotion: data.emotion
            };

            setMessages(prev => [...prev, agentMsg]);

            if (speechManager.current) {
                const isReynolds = data.agent === 'Reynolds';
                const voice = isReynolds ? 'Male' : 'Female';
                const options = isReynolds ? { pitch: 0.7, rate: 1.1 } : { pitch: 1.1, rate: 0.95 };

                // Auto-Start listening when agent finishes speaking
                speechManager.current.speak(agentMsg.content, voice, options, () => {
                    console.log("Agent finished, auto-starting mic...");
                    if (speechManager.current) {
                        speechManager.current.startListening();
                        setIsListening(true);
                    }
                });
            }

        } catch (error) {
            console.error("Error sending message:", error);
        }
    };

    // Update ref whenever function changes (though it likely won't change much)
    useEffect(() => {
        handleSendMessageRef.current = handleSendMessage;
    }, [handleSendMessage]);

    // Initialize Speech Manager
    useEffect(() => {
        speechManager.current = new SpeechManager(
            (text) => {
                setInputText(text);
                setErrorMsg(null);
                resetSilenceTimer();

                // Auto-Send Logic (Final Result)
                if (text.trim().length > 0) {
                    console.log("Transcript received, sending almost immediately:", text);
                    // 100ms delay to allow state to settle, then send using Ref to avoid stale closures
                    setTimeout(() => {
                        handleSendMessageRef.current(text);
                    }, 100);
                }
            },
            (error) => {
                if (error.startsWith("TTS Error")) {
                    const cleanError = error.replace("TTS Error: ", "");
                    if (cleanError === 'not-allowed' || cleanError === 'canceled') {
                        setErrorMsg("Auto-play blocked by browser. Please click the 'Play' button on the message.");
                    } else {
                        setErrorMsg(`Audio Error: ${cleanError}`);
                    }
                } else {
                    setErrorMsg(`Microphone Error: ${error}`);
                    if (error === 'network') {
                        setErrorMsg("Network Error: Speech-to-Text requires an active internet connection (Google servers). Please type your answer.");
                    }
                    setIsListening(false);
                }
            }
        );

        setMessages([
            { role: 'agent', content: "State your name for the record.", agentName: 'Reynolds', emotion: 'stern' }
        ]);

        return () => {
            if (silenceTimer.current) clearTimeout(silenceTimer.current);
        };
    }, []);

    useEffect(() => {
        resetSilenceTimer();
    }, [messages, isListening]);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages]);

    const toggleListening = () => {
        if (!speechManager.current) return;

        if (isListening) {
            speechManager.current.stopListening();
            setIsListening(false);
        } else {
            speechManager.current.startListening();
            setIsListening(true);
        }
    };

    return (
        <div className="flex flex-col h-screen bg-gray-900 text-white font-sans">
            {/* Header */}
            <div className="p-4 border-b border-gray-700 flex justify-between items-center bg-gray-800">
                <h1 className="text-xl font-bold tracking-wider text-red-500">INTERROGATION ROOM A</h1>
                <div className="flex space-x-2">
                    <span className="w-3 h-3 rounded-full bg-red-600 animate-pulse"></span>
                    <span className="text-xs text-gray-400">REC</span>
                </div>
            </div>

            {/* Chat Area */}
            <div className="flex-1 overflow-y-auto p-6 space-y-4">
                {messages.map((msg, idx) => (
                    <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                        <div className={`max-w-2xl p-4 rounded-lg shadow-lg ${msg.role === 'user'
                            ? 'bg-blue-600 text-white rounded-br-none'
                            : msg.agentName === 'Reynolds'
                                ? 'bg-gray-700 text-gray-200 border-l-4 border-red-800 rounded-bl-none'
                                : 'bg-gray-700 text-gray-200 border-l-4 border-blue-400 rounded-bl-none'
                            }`}>
                            {msg.role === 'agent' && (
                                <div className="flex justify-between items-center mb-1">
                                    <div className="text-xs font-bold uppercase tracking-wide opacity-70">
                                        {msg.agentName} <span className="text-gray-500">[{msg.emotion}]</span>
                                    </div>
                                    <button
                                        onClick={() => {
                                            const isReynolds = msg.agentName === 'Reynolds';
                                            const voice = isReynolds ? 'Male' : 'Female';
                                            const options = isReynolds ? { pitch: 0.7, rate: 1.1 } : { pitch: 1.1, rate: 0.95 };
                                            // Pass onEnd callback to auto-start mic after manual playback
                                            speechManager.current?.speak(msg.content, voice, options, () => {
                                                console.log("Manual playback finished, auto-starting mic...");
                                                if (speechManager.current) {
                                                    speechManager.current.startListening();
                                                    setIsListening(true);
                                                }
                                            });
                                        }}
                                        className="text-xs bg-gray-600 hover:bg-gray-500 px-2 py-1 rounded text-white"
                                        title="Replay Audio"
                                    >
                                        🔊 Play
                                    </button>
                                </div>
                            )}
                            <p className="text-lg leading-relaxed">{msg.content}</p>
                        </div>
                    </div>
                ))}
                <div ref={messagesEndRef} />
            </div>

            {/* Input Area */}
            <div className="p-4 bg-gray-800 border-t border-gray-700">
                {errorMsg && (
                    <div className="mb-2 p-2 bg-red-900 border border-red-500 rounded text-red-100 text-sm text-center">
                        ⚠️ {errorMsg}
                    </div>
                )}
                <div className="flex items-center space-x-2 max-w-4xl mx-auto">
                    <button
                        onClick={toggleListening}
                        className={`p-4 rounded-full transition-colors ${isListening ? 'bg-red-600 hover:bg-red-700' : 'bg-gray-600 hover:bg-gray-500'
                            }`}
                    >
                        {isListening ? '🛑' : '🎤'}
                    </button>

                    <input
                        type="text"
                        value={inputText}
                        onChange={(e) => setInputText(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
                        className="flex-1 bg-gray-900 border border-gray-600 rounded-lg px-4 py-3 text-white focus:outline-none focus:border-blue-500 text-lg"
                        placeholder="Type or speak your answer..."
                    />

                    <button
                        onClick={() => handleSendMessage()}
                        className="bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 rounded-lg font-bold tracking-wide transition-colors"
                    >
                        SEND
                    </button>
                </div>
            </div>
        </div>
    );
}
