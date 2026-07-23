"use client";

import React, { useEffect, useState } from 'react';
import { getBrief, type Brief } from '../lib/api';
import { concealmentStyle } from '../lib/concealment';

/**
 * The learner's own brief, kept within reach for the whole interview.
 *
 * Deliberately not hidden. Holding a cover story together in a second language
 * while someone picks at it is the exercise; remembering two lines is not. If
 * the card were hidden this would quietly become a memory test.
 *
 * The two halves are shown differently on purpose. The denial is a thing to keep
 * out and reads as a warning; the substitution is work they owe the detectives
 * and reads as an instruction. Presenting them identically would flatten them
 * into "two secrets", which is exactly the distinction that carries the load.
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
                <span>Your account · confidential</span>
                <span style={{ color: 'var(--text-muted)' }}>{open ? '−' : '+'}</span>
            </button>

            {open && (
                <div className="mt-2 pb-1 space-y-2">
                    <p className="text-xs font-mono leading-relaxed"
                        style={{ color: 'var(--text-secondary)' }}>
                        {brief.premise}
                    </p>

                    {brief.concealments.map((c, i) => {
                        const s = concealmentStyle(c.kind);
                        return (
                            <p key={i} className="text-xs font-mono px-2 py-1 rounded leading-relaxed"
                                style={{
                                    color: s.accent,
                                    background: s.background,
                                    border: `1px solid ${s.accent}`,
                                }}>
                                <span className="uppercase tracking-widest">{s.label}</span>
                                <br />
                                {c.text}
                            </p>
                        );
                    })}

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
