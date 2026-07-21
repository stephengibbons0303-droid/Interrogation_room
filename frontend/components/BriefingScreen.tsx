"use client";

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { getBrief, type Brief } from '../lib/api';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || '/api';

/**
 * Read the learner their brief before the door opens.
 *
 * Previously the brief appeared at the top of the interview screen at the same
 * moment the first question arrived, so there was no chance to take it in. It is
 * now its own step, with no time pressure and nothing else happening.
 *
 * It is spoken as well as shown, in a third voice that is deliberately not one
 * of the detectives. Reading and hearing the same words together is the point:
 * the learner is about to have to hold this under pressure, and dual input gives
 * them a much better chance of retaining it.
 */
export default function BriefingScreen({ interviewId, onReady }:
    { interviewId: string; onReady: () => void }) {
    const [brief, setBrief] = useState<Brief | null>(null);
    const [speaking, setSpeaking] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const audioRef = useRef<HTMLAudioElement | null>(null);
    const spokenOnce = useRef(false);

    const spokenText = (b: Brief) => [
        'Before you go in, this is what you know.',
        b.premise,
        ...b.facts.map(f => f.text),
        b.conceal ? `You must not admit: ${b.conceal}` : '',
        b.awkward || '',
        'Take your time. When you are ready, they will begin.',
    ].filter(Boolean).join(' ');

    const speak = useCallback(async (b: Brief) => {
        try {
            setSpeaking(true);
            const res = await fetch(`${BACKEND_URL}/tts`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: spokenText(b), voice: 'Briefing' }),
            });
            if (!res.ok) { setSpeaking(false); return; }
            const url = URL.createObjectURL(await res.blob());
            const audio = new Audio(url);
            audioRef.current = audio;
            audio.onended = () => { URL.revokeObjectURL(url); setSpeaking(false); };
            audio.onerror = () => { URL.revokeObjectURL(url); setSpeaking(false); };
            // Autoplay is allowed here: reaching this screen took a click.
            await audio.play().catch(() => setSpeaking(false));
        } catch {
            setSpeaking(false);
        }
    }, []);

    useEffect(() => {
        getBrief(interviewId).then(b => {
            setBrief(b);
            if (!spokenOnce.current) { spokenOnce.current = true; speak(b); }
        }).catch(() => setError('Could not load your brief.'));
        return () => { audioRef.current?.pause(); };
    }, [interviewId, speak]);

    const begin = () => { audioRef.current?.pause(); onReady(); };

    return (
        <div className="flex flex-col h-screen items-center justify-center px-6 overflow-y-auto"
            style={{ background: 'var(--background)', color: 'var(--text-primary)' }}>
            <div className="scanline-overlay" />

            <div className="w-full max-w-xl py-10">
                <p className="text-xs font-mono uppercase tracking-widest text-center mb-1"
                    style={{ color: 'var(--text-muted)' }}>
                    Before you go in
                </p>
                <h1 className="text-sm font-bold tracking-widest font-mono uppercase text-center mb-6"
                    style={{ color: 'var(--amber)' }}>
                    What you know
                </h1>

                {error && (
                    <p className="text-sm font-mono text-center" style={{ color: 'var(--red-accent)' }}>
                        {error}
                    </p>
                )}

                {brief && (
                    <div className="space-y-5">
                        <p className="text-base font-mono leading-relaxed"
                            style={{ color: 'var(--text-secondary)' }}>
                            {brief.premise}
                        </p>

                        <ul className="space-y-2">
                            {brief.facts.map((f, i) => (
                                <li key={i} className="text-base font-mono flex gap-3 leading-relaxed">
                                    <span style={{ color: 'var(--text-muted)' }}>{i + 1}.</span>
                                    <span>{f.text}</span>
                                </li>
                            ))}
                        </ul>

                        {brief.conceal && (
                            <p className="text-base font-mono px-4 py-3 rounded leading-relaxed"
                                style={{
                                    color: 'var(--red-accent)',
                                    background: 'rgba(212, 54, 74, 0.08)',
                                    border: '1px solid var(--red-accent)',
                                }}>
                                Do not admit: {brief.conceal}
                            </p>
                        )}

                        {brief.awkward && (
                            <p className="text-sm font-mono leading-relaxed"
                                style={{ color: 'var(--text-muted)' }}>
                                {brief.awkward}
                            </p>
                        )}

                        <div className="flex items-center justify-between gap-3 pt-4">
                            <button
                                onClick={() => brief && speak(brief)}
                                disabled={speaking}
                                className="px-4 py-2 rounded-lg text-xs font-mono uppercase tracking-wider"
                                style={{
                                    background: 'var(--surface-raised)',
                                    border: '1px solid var(--border-bright)',
                                    color: 'var(--text-secondary)',
                                    opacity: speaking ? 0.5 : 1,
                                }}
                            >
                                {speaking ? 'Reading…' : 'Read it again'}
                            </button>

                            <button
                                onClick={begin}
                                className="px-8 py-3 rounded-lg font-bold text-sm tracking-wider font-mono uppercase"
                                style={{
                                    background: 'var(--teal-dim)',
                                    border: '1px solid var(--teal)',
                                    color: 'var(--teal)',
                                }}
                            >
                                I'm ready
                            </button>
                        </div>

                        <p className="text-xs font-mono text-center pt-2"
                            style={{ color: 'var(--text-muted)' }}>
                            You can open this again at any point during the interview.
                        </p>
                    </div>
                )}
            </div>
        </div>
    );
}
