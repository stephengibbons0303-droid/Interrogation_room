"use client";

import React, { useEffect, useState } from 'react';
import { getBrief, type Brief } from '../lib/api';

/**
 * The learner's own brief, kept within reach for the whole interview.
 *
 * Deliberately not hidden. Holding a cover story together in a second language
 * while someone picks at it is the exercise; remembering five bullet points is
 * not. If the card were hidden this would quietly become a memory test.
 */
export default function BriefPanel({ interviewId, defaultOpen = false }:
    { interviewId: string; defaultOpen?: boolean }) {
    const [brief, setBrief] = useState<Brief | null>(null);
    // Collapsed by default during the interview: they have just been read it on
    // the briefing screen, and expanded it covered most of the transcript.
    const [open, setOpen] = useState(defaultOpen);

    useEffect(() => {
        getBrief(interviewId).then(setBrief).catch(() => setBrief(null));
    }, [interviewId]);

    if (!brief) return null;

    return (
        <div
            className="px-5 py-2"
            style={{ background: 'var(--surface)', borderBottom: '1px solid var(--border)' }}
        >
            <button
                onClick={() => setOpen(!open)}
                className="w-full flex items-center justify-between text-xs font-mono uppercase tracking-widest"
                style={{ color: 'var(--amber)' }}
            >
                <span>Your account {brief.conceal ? '· confidential' : ''}</span>
                <span style={{ color: 'var(--text-muted)' }}>{open ? '−' : '+'}</span>
            </button>

            {open && (
                <div className="mt-2 pb-1 space-y-2">
                    <p className="text-xs font-mono leading-relaxed"
                        style={{ color: 'var(--text-secondary)' }}>
                        {brief.premise}
                    </p>

                    <ul className="space-y-1">
                        {brief.facts.map((f, i) => (
                            <li key={i} className="text-xs font-mono flex gap-2"
                                style={{ color: 'var(--text-primary)' }}>
                                <span style={{ color: 'var(--text-muted)' }}>·</span>
                                <span>{f.text}</span>
                            </li>
                        ))}
                    </ul>

                    {brief.conceal && (
                        <p className="text-xs font-mono px-2 py-1 rounded"
                            style={{
                                color: 'var(--red-accent)',
                                background: 'rgba(212, 54, 74, 0.08)',
                                border: '1px solid var(--red-accent)',
                            }}>
                            Do not admit: {brief.conceal}
                        </p>
                    )}

                    {brief.awkward && (
                        <p className="text-xs font-mono" style={{ color: 'var(--text-muted)' }}>
                            {brief.awkward}
                        </p>
                    )}
                </div>
            )}
        </div>
    );
}
