"use client";

import React, { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { getTrace, type TraceEntry } from '@/lib/api';

/**
 * Dev-only engine trace: what the deterministic engine decided each turn and why.
 * Reads GET /interviews/{id}/trace (owner-scoped). Reachable at /dev/trace/<id> -
 * the interrogation room links to it. Not part of the learner-facing flow.
 */
export default function EngineTracePage() {
    const params = useParams();
    const id = Array.isArray(params.id) ? params.id[0] : (params.id as string);
    const [entries, setEntries] = useState<TraceEntry[] | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (!id) return;
        getTrace(id).then(setEntries).catch((e) => setError(e?.message ?? 'Could not load the trace.'));
    }, [id]);

    const mono = { fontFamily: 'var(--font-mono, monospace)' } as const;
    const agentColor = (s: string) =>
        s === 'Reynolds' ? 'var(--amber)' : s === 'Chen' ? 'var(--teal)' : 'var(--text-secondary)';

    const pill = (label: string, color = 'var(--text-muted)') => (
        <span key={label} className="text-xs font-mono px-2 py-0.5 rounded"
            style={{ color, border: `1px solid ${color}`, opacity: 0.9 }}>{label}</span>
    );

    return (
        <div className="min-h-screen px-6 py-8"
            style={{ background: 'var(--background)', color: 'var(--text-primary)' }}>
            <div className="max-w-3xl mx-auto">
                <div className="flex items-baseline justify-between mb-1">
                    <h1 className="text-sm font-bold tracking-widest font-mono uppercase"
                        style={{ color: 'var(--teal)' }}>Engine trace</h1>
                    <span className="text-xs font-mono" style={{ color: 'var(--text-muted)' }}>
                        {entries ? `${entries.length} turns` : ''}
                    </span>
                </div>
                <p className="text-xs font-mono mb-6" style={{ color: 'var(--text-muted)' }}>
                    interview {id} · what the engine decided each turn, and why
                </p>

                {error && <p className="text-sm font-mono" style={{ color: 'var(--red-accent)' }}>{error}</p>}
                {!error && !entries && (
                    <p className="text-sm font-mono" style={{ color: 'var(--text-muted)' }}>Loading…</p>)}
                {entries && entries.length === 0 && (
                    <p className="text-sm font-mono" style={{ color: 'var(--text-muted)' }}>
                        No turns recorded yet — play the interview, then reload.
                    </p>)}

                <div className="space-y-3">
                    {entries?.map((t) => {
                        const activeFlags = [
                            t.flags.phone_probed && 'phone_probed',
                            t.flags.phone_reminder_spent && 'reminder_spent',
                            t.flags.premise_open && 'premise_open',
                            t.flags.retelling_active && 'retelling',
                        ].filter(Boolean) as string[];
                        return (
                            <div key={t.turn} className="rounded-lg px-4 py-3"
                                style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>
                                <div className="flex items-center justify-between flex-wrap gap-2 mb-2">
                                    <div className="flex items-center gap-3">
                                        <span className="text-sm font-bold font-mono">Turn {t.turn}</span>
                                        <span className="text-xs font-mono px-2 py-0.5 rounded uppercase"
                                            style={{ color: 'var(--amber)', background: 'var(--amber-glow)', border: '1px solid var(--amber-dim)' }}>
                                            {t.stage_advanced_from ? `${t.stage_advanced_from} → ${t.stage}` : t.stage}
                                        </span>
                                        <span className="text-xs font-mono" style={{ color: agentColor(t.speaker) }}>
                                            {t.speaker}{t.aside ? ' · aside' : ''}
                                        </span>
                                        {t.silence && pill('silence')}
                                    </div>
                                    <span className="text-xs font-mono" style={{ color: 'var(--text-muted)' }}>
                                        trigger: {t.handoff_reason}
                                    </span>
                                </div>

                                <div className="text-xs font-mono mb-2" style={{ color: 'var(--text-secondary)' }}>
                                    +{t.claims_added} claims ({t.claims_episodic} episodic) ·{' '}
                                    contradictions: {t.contradictions_new.length ? t.contradictions_new.join(', ') : 'none'} ·{' '}
                                    {t.responsive ? 'responsive' : 'off-question'}
                                </div>

                                <div className="mb-2">
                                    {t.shortlist.map((s) => (
                                        <div key={s.id} className="flex items-center gap-2 text-xs" style={mono}>
                                            <span style={{
                                                width: 190, color: s.chosen ? 'var(--teal)' : 'var(--text-secondary)',
                                                fontWeight: s.chosen ? 700 : 400,
                                            }}>{s.id}</span>
                                            <div style={{ flex: 1, height: 4, background: 'var(--background)', borderRadius: 999, overflow: 'hidden' }}>
                                                <div style={{ width: `${Math.min(100, (s.weight / 4) * 100)}%`, height: '100%', background: s.chosen ? 'var(--teal)' : 'var(--border-bright)' }} />
                                            </div>
                                            <span style={{ width: 28, textAlign: 'right', color: 'var(--text-secondary)' }}>{s.weight.toFixed(1)}</span>
                                            {s.chosen && <span style={{ color: 'var(--teal)' }}>◄</span>}
                                        </div>
                                    ))}
                                </div>

                                <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs font-mono pt-2"
                                    style={{ color: 'var(--text-secondary)', borderTop: '1px solid var(--border)' }}>
                                    <span>pressure {t.pressure.before.toFixed(2)} → {t.pressure.after.toFixed(2)}</span>
                                    <span>exculpation {t.exculpation.before.toFixed(2)} → {t.exculpation.after.toFixed(2)}</span>
                                    <span>Chen {t.chen.before}{t.chen.after !== t.chen.before ? ` → ${t.chen.after}` : ''}</span>
                                    {t.sting && <span style={{ color: 'var(--red-accent)' }}>STING</span>}
                                    {t.outcome && <span style={{ color: 'var(--amber)' }}>outcome: {t.outcome}</span>}
                                </div>

                                {activeFlags.length > 0 && (
                                    <div className="flex flex-wrap gap-2 mt-2">{activeFlags.map((f) => pill(f))}</div>
                                )}
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    );
}
