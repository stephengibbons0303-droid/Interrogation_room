"use client";

import React, { useState } from 'react';
import { login, register } from '../lib/api';

export default function AuthScreen({ onAuthed }: { onAuthed: () => void }) {
    const [mode, setMode] = useState<'login' | 'register'>('login');
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);

    const submit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError(null);

        if (mode === 'register' && password.length < 8) {
            setError('Password must be at least 8 characters.');
            return;
        }

        setBusy(true);
        try {
            if (mode === 'login') await login(email.trim(), password);
            else await register(email.trim(), password);
            onAuthed();
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Something went wrong.');
        } finally {
            setBusy(false);
        }
    };

    const field: React.CSSProperties = {
        background: 'var(--background)',
        border: '1px solid var(--border-bright)',
        color: 'var(--text-primary)',
    };

    return (
        <div
            className="flex flex-col h-screen items-center justify-center px-4"
            style={{ background: 'var(--background)', color: 'var(--text-primary)' }}
        >
            <div className="scanline-overlay" />

            <div className="w-full max-w-sm">
                <div className="text-center mb-8">
                    <h1
                        className="text-sm font-bold tracking-widest font-mono uppercase"
                        style={{ color: 'var(--teal)' }}
                    >
                        Interview Room A
                    </h1>
                    <p className="text-xs font-mono mt-2" style={{ color: 'var(--text-muted)' }}>
                        Metropolitan Police — Major Crimes
                    </p>
                </div>

                <form onSubmit={submit} className="space-y-3">
                    <label className="block text-xs font-mono uppercase tracking-wider"
                        style={{ color: 'var(--text-muted)' }}>
                        Email
                        <input
                            type="email"
                            required
                            autoComplete="email"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            className="w-full mt-1 rounded-lg px-3 py-2.5 text-base font-mono focus:outline-none"
                            style={field}
                        />
                    </label>

                    <label className="block text-xs font-mono uppercase tracking-wider"
                        style={{ color: 'var(--text-muted)' }}>
                        Password
                        <input
                            type="password"
                            required
                            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            className="w-full mt-1 rounded-lg px-3 py-2.5 text-base font-mono focus:outline-none"
                            style={field}
                        />
                    </label>

                    {error && (
                        <div
                            className="px-3 py-2 rounded text-sm text-center font-mono"
                            style={{
                                background: 'rgba(212, 54, 74, 0.1)',
                                border: '1px solid var(--red-accent)',
                                color: 'var(--red-accent)',
                            }}
                        >
                            {error}
                        </div>
                    )}

                    <button
                        type="submit"
                        disabled={busy}
                        className="w-full px-8 py-3 rounded-lg font-bold text-sm tracking-wider transition-all font-mono uppercase"
                        style={{
                            background: 'var(--teal-dim)',
                            border: '1px solid var(--teal)',
                            color: 'var(--teal)',
                            opacity: busy ? 0.5 : 1,
                        }}
                    >
                        {busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
                    </button>
                </form>

                <button
                    onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(null); }}
                    className="w-full mt-4 text-xs font-mono"
                    style={{ color: 'var(--text-muted)' }}
                >
                    {mode === 'login'
                        ? 'No account? Create one'
                        : 'Already have an account? Sign in'}
                </button>
            </div>
        </div>
    );
}
