"use client";

import React, { useCallback, useEffect, useState } from 'react';
import AuthScreen from "../components/AuthScreen";
import InterviewPicker from "../components/InterviewPicker";
import InterrogationRoom from "../components/InterrogationRoom";
import { clearTokens, getToken, me, type Me } from "../lib/api";

type Open = { id: string; resume: boolean };

export default function Home() {
  const [user, setUser] = useState<Me | null>(null);
  const [checking, setChecking] = useState(true);
  const [open, setOpen] = useState<Open | null>(null);

  const check = useCallback(async () => {
    if (!getToken()) { setUser(null); setChecking(false); return; }
    try {
      setUser(await me());
    } catch {
      // Token expired or revoked - drop it and show the sign-in screen.
      clearTokens();
      setUser(null);
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => { check(); }, [check]);

  const body = () => {
    if (checking) {
      return (
        <div className="flex h-screen items-center justify-center">
          <span className="text-xs font-mono" style={{ color: 'var(--text-muted)' }}>
            Checking credentials…
          </span>
        </div>
      );
    }
    if (!user) return <AuthScreen onAuthed={check} />;
    if (!open) {
      return (
        <InterviewPicker
          email={user.email}
          onOpen={(id, resume) => setOpen({ id, resume })}
          onSignOut={() => { setUser(null); setOpen(null); }}
        />
      );
    }
    return (
      <InterrogationRoom
        interviewId={open.id}
        resume={open.resume}
        onExit={() => setOpen(null)}
      />
    );
  };

  return (
    <main className="min-h-screen" style={{ background: 'var(--background)' }}>
      {body()}
    </main>
  );
}
