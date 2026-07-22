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
 * It CAN be spoken as well as shown, in a third voice that is deliberately not
 * one of the detectives - reading and hearing the same words together gives the
 * learner a much better chance of holding it under pressure later. But it is
 * offered rather than imposed: it used to speak itself on arrival, and a brief
 * this long takes seconds to synthesise, so the narration would begin just as
 * the learner was ready to move on and then talk over the first question.
 */
export default function BriefingScreen({ interviewId, onReady }:
    { interviewId: string; onReady: () => void }) {
    const [brief, setBrief] = useState<Brief | null>(null);
    const [speaking, setSpeaking] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const audioRef = useRef<HTMLAudioElement | null>(null);
    // Set the moment the learner leaves this screen. Pausing audioRef is not
    // enough on its own: the narration has to be fetched and synthesised before
    // there is any audio object to pause, and if they press on during that gap
    // the ref is still null. The sound then arrives to an empty room and reads
    // the brief over the top of the detective.
    const gone = useRef(false);

    const spokenText = (b: Brief) => [
        'Before you go in, this is what you know.',
        b.premise,
        ...b.concealments.map(c => c.kind === 'denial'
            ? `You must not admit this. ${c.text}`
            : `And you must be ready to say this. ${c.text}`),
        b.awkward || '',
        'The rest of the evening is yours. Make it up as you like, but remember what you say.',
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

            // They pressed on while this was being synthesised. Throw it away
            // rather than playing it into a room that has moved on.
            if (gone.current) { URL.revokeObjectURL(url); setSpeaking(false); return; }

            const audio = new Audio(url);
            audioRef.current = audio;
            audio.onended = () => { URL.revokeObjectURL(url); setSpeaking(false); };
            audio.onerror = () => { URL.revokeObjectURL(url); setSpeaking(false); };
            // Allowed to play: getting here took a deliberate press.
            await audio.play().catch(() => setSpeaking(false));
        } catch {
            setSpeaking(false);
        }
    }, []);

    // Deliberately does NOT speak on arrival - see the note on the component.
    useEffect(() => {
        getBrief(interviewId)
            .then(setBrief)
            .catch(() => setError('Could not load your brief.'));
        return () => { gone.current = true; audioRef.current?.pause(); };
    }, [interviewId]);

    const begin = () => { gone.current = true; audioRef.current?.pause(); onReady(); };

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

                {/* A failed load used to render the message and nothing else, so
                    the only way past this screen disappeared with it. Whatever
                    went wrong, they must still be able to open the door. */}
                {error && (
                    <div className="space-y-4 text-center">
                        <p className="text-sm font-mono" style={{ color: 'var(--red-accent)' }}>
                            {error}
                        </p>
                        <button
                            onClick={begin}
                            className="px-8 py-3 rounded-lg font-bold text-sm tracking-wider font-mono uppercase"
                            style={{
                                background: 'var(--teal-dim)',
                                border: '1px solid var(--teal)',
                                color: 'var(--teal)',
                            }}
                        >
                            Go in anyway
                        </button>
                    </div>
                )}

                {brief && (
                    <div className="space-y-5">
                        <p className="text-base font-mono leading-relaxed"
                            style={{ color: 'var(--text-secondary)' }}>
                            {brief.premise}
                        </p>

                        {brief.concealments.map((c, i) => {
                            const denial = c.kind === 'denial';
                            return (
                                <div key={i} className="px-4 py-3 rounded space-y-1"
                                    style={{
                                        background: denial
                                            ? 'rgba(212, 54, 74, 0.08)'
                                            : 'rgba(212, 160, 54, 0.08)',
                                        border: `1px solid ${denial ? 'var(--red-accent)' : 'var(--amber)'}`,
                                    }}>
                                    <p className="text-xs font-mono uppercase tracking-widest"
                                        style={{ color: denial ? 'var(--red-accent)' : 'var(--amber)' }}>
                                        {denial ? 'Do not admit' : 'You must be able to say'}
                                    </p>
                                    <p className="text-base font-mono leading-relaxed"
                                        style={{ color: 'var(--text-primary)' }}>
                                        {c.text}
                                    </p>
                                </div>
                            );
                        })}

                        {brief.awkward && (
                            <p className="text-sm font-mono leading-relaxed"
                                style={{ color: 'var(--text-muted)' }}>
                                {brief.awkward}
                            </p>
                        )}

                        <p className="text-sm font-mono leading-relaxed"
                            style={{ color: 'var(--text-secondary)' }}>
                            Everything else about Thursday is yours to invent. Say whatever
                            you like happened - but remember what you say, because they
                            will ask you again.
                        </p>

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
                                {speaking ? 'Reading…' : '▶  Read it to me'}
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
