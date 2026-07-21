"use client";

import React, { useCallback, useEffect, useState } from 'react';
import {
    clearTokens, createInterview, deleteInterview, listInterviews,
    type InterviewSummary,
} from '../lib/api';

interface Props {
    email: string;
    onOpen: (interviewId: string, resume: boolean) => void;
    onSignOut: () => void;
}

export default function InterviewPicker({ email, onOpen, onSignOut }: Props) {
    const [interviews, setInterviews] = useState<InterviewSummary[] | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);

    const load = useCallback(async () => {
        try {
            setInterviews(await listInterviews());
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Could not load interviews.');
            setInterviews([]);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const startFresh = async () => {
        setBusy(true);
        setError(null);
        try {
            // Creates a new interview; earlier ones are left intact rather than
            // overwritten, so "start fresh" never destroys previous work.
            const iv = await createInterview();
            onOpen(iv.id, false);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Could not start a new interview.');
            setBusy(false);
        }
    };

    const remove = async (id: string) => {
        try {
            await deleteInterview(id);
            await load();
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Could not delete.');
        }
    };

    const signOut = () => { clearTokens(); onSignOut(); };

    const when = (iso?: string | null) => {
        if (!iso) return '';
        const d = new Date(iso.endsWith('Z') ? iso : `${iso}Z`);
        return isNaN(d.getTime()) ? '' : d.toLocaleString();
    };

    return (
        <div
            className="flex flex-col h-screen"
            style={{ background: 'var(--background)', color: 'var(--text-primary)' }}
        >
            <div className="scanline-overlay" />

            <div
                className="px-5 py-3 flex justify-between items-center"
                style={{ background: 'var(--surface)', borderBottom: '1px solid var(--border)' }}
            >
                <h1 className="text-sm font-bold tracking-widest font-mono uppercase"
                    style={{ color: 'var(--teal)' }}>
                    Interview Room A
                </h1>
                <div className="flex items-center gap-3">
                    <span className="text-xs font-mono" style={{ color: 'var(--text-muted)' }}>
                        {email}
                    </span>
                    <button
                        onClick={signOut}
                        className="text-xs px-2 py-1 rounded font-mono uppercase tracking-wider"
                        style={{ color: 'var(--text-muted)', border: '1px solid var(--border)' }}
                    >
                        Sign out
                    </button>
                </div>
            </div>

            <div className="flex-1 overflow-y-auto px-6 py-6">
                <div className="max-w-2xl mx-auto">
                    <button
                        onClick={startFresh}
                        disabled={busy}
                        className="w-full px-6 py-4 rounded-lg font-bold text-sm tracking-wider transition-all font-mono uppercase"
                        style={{
                            background: 'var(--teal-dim)',
                            border: '1px solid var(--teal)',
                            color: 'var(--teal)',
                            opacity: busy ? 0.5 : 1,
                        }}
                    >
                        {busy ? 'Preparing the room…' : 'Start a new interview'}
                    </button>

                    {error && (
                        <div
                            className="mt-4 px-3 py-2 rounded text-sm text-center font-mono"
                            style={{
                                background: 'rgba(212, 54, 74, 0.1)',
                                border: '1px solid var(--red-accent)',
                                color: 'var(--red-accent)',
                            }}
                        >
                            {error}
                        </div>
                    )}

                    <h2 className="mt-8 mb-3 text-xs font-mono uppercase tracking-widest"
                        style={{ color: 'var(--text-muted)' }}>
                        Previous interviews
                    </h2>

                    {interviews === null && (
                        <p className="text-xs font-mono" style={{ color: 'var(--text-muted)' }}>
                            Loading…
                        </p>
                    )}

                    {interviews?.length === 0 && (
                        <p className="text-xs font-mono" style={{ color: 'var(--text-muted)' }}>
                            None yet. Start a new interview above.
                        </p>
                    )}

                    <div className="space-y-2">
                        {interviews?.map((iv) => (
                            <div
                                key={iv.id}
                                className="px-4 py-3 rounded-lg flex items-center justify-between gap-4"
                                style={{
                                    background: 'var(--surface)',
                                    border: '1px solid var(--border)',
                                }}
                            >
                                <div className="min-w-0">
                                    <div className="flex items-center gap-2">
                                        <span className="text-sm font-mono"
                                            style={{ color: 'var(--text-primary)' }}>
                                            {iv.player_name || 'Unnamed witness'}
                                        </span>
                                        <span
                                            className="text-xs font-mono px-2 py-0.5 rounded"
                                            style={{
                                                color: 'var(--amber)',
                                                background: 'var(--amber-glow)',
                                                border: '1px solid var(--amber-dim)',
                                            }}
                                        >
                                            {iv.phase}
                                        </span>
                                    </div>
                                    <div className="text-xs font-mono mt-1 truncate"
                                        style={{ color: 'var(--text-muted)' }}>
                                        {iv.turn_count} turns · {when(iv.updated_at)}
                                    </div>
                                </div>

                                <div className="flex items-center gap-2 shrink-0">
                                    <button
                                        onClick={() => onOpen(iv.id, true)}
                                        className="px-4 py-2 rounded-lg font-bold text-xs tracking-wider font-mono uppercase"
                                        style={{
                                            background: 'var(--surface-raised)',
                                            border: '1px solid var(--teal)',
                                            color: 'var(--teal)',
                                        }}
                                    >
                                        Resume
                                    </button>
                                    <button
                                        onClick={() => remove(iv.id)}
                                        title="Delete interview"
                                        className="px-2 py-2 rounded-lg text-xs font-mono"
                                        style={{
                                            color: 'var(--text-muted)',
                                            border: '1px solid var(--border)',
                                        }}
                                    >
                                        ✕
                                    </button>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    );
}
