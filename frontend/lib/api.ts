/**
 * Client for the interrogation backend, reached through the same-origin /api
 * proxy so the browser never needs the backend URL.
 */

const BASE = process.env.NEXT_PUBLIC_BACKEND_URL || '/api';

const ACCESS_KEY = 'interrogation.access_token';
const REFRESH_KEY = 'interrogation.refresh_token';

export interface Tokens {
    access_token: string;
    refresh_token: string;
}

export interface Me {
    id: string;
    email: string;
    role: string;
}

export interface InterviewSummary {
    id: string;
    status: string;
    phase: string;
    turn_count: number;
    player_name?: string | null;
    created_at?: string | null;
    updated_at?: string | null;
    preview?: string | null;
    /** Set once the interview has concluded: released, under_investigation, detained. */
    outcome?: string | null;
}

export interface TurnOut {
    seq: number;
    role: 'user' | 'agent';
    agent_name?: string | null;
    text: string;
    modality?: string | null;
    /** "learner" when spoken to them, "partner" when the detectives confer
     *  in front of them. Overheard speech is a different listening task. */
    addressed_to?: string | null;
    exchange_id?: string | null;
    phase?: string | null;
    emotion?: string | null;
}

export interface InterviewDetail extends InterviewSummary {
    turns: TurnOut[];
}

export interface Utterance {
    speaker: string;
    text: string;
    addressed_to: string;
    emotion?: string | null;
}

export interface ChatReply {
    /** One utterance normally; two when the detectives confer with each other. */
    utterances: Utterance[];
    phase: string;
    turn: number;
    interview_id: string;
    outcome?: string | null;
    tactic?: string | null;
}

/** One half of the pair the learner has to work around. A `denial` is a fact to
 *  keep out of the account; a `substitution` is the hole that leaves, which has
 *  to be filled in and then held identical every time it is revisited. */
export interface Concealment {
    kind: 'denial' | 'substitution';
    text: string;
}

/** No longer an account to recite - the evening is the learner's to invent. */
export interface Brief {
    id: string;
    premise: string;
    concealments: Concealment[];
    awkward?: string | null;
}

/** How the learner produced a turn. Recorded per turn because the post-session
 *  assessment credits speaking and listening separately. */
export type Modality = 'spoken' | 'typed' | 'silence';

export function getToken(): string | null {
    if (typeof window === 'undefined') return null;
    return window.localStorage.getItem(ACCESS_KEY);
}

function setTokens(t: Tokens) {
    window.localStorage.setItem(ACCESS_KEY, t.access_token);
    window.localStorage.setItem(REFRESH_KEY, t.refresh_token);
}

export function clearTokens() {
    window.localStorage.removeItem(ACCESS_KEY);
    window.localStorage.removeItem(REFRESH_KEY);
}

class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
        super(message);
        this.status = status;
    }
}

async function request<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
    const token = getToken();
    const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
    if (init.body) headers['Content-Type'] = 'application/json';
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const res = await fetch(`${BASE}${path}`, { ...init, headers });

    // Access tokens are short-lived; swap in a new one and retry once rather
    // than bouncing the learner out mid-interview.
    if (res.status === 401 && retry && typeof window !== 'undefined') {
        const refreshed = await tryRefresh();
        if (refreshed) return request<T>(path, init, false);
    }

    if (!res.ok) {
        let detail = res.statusText;
        try {
            const body = await res.json();
            detail = body.detail || body.error || detail;
        } catch { /* non-JSON error body */ }
        throw new ApiError(res.status, typeof detail === 'string' ? detail : 'Request failed');
    }

    if (res.status === 204) return undefined as T;
    return res.json() as Promise<T>;
}

async function tryRefresh(): Promise<boolean> {
    const refresh = window.localStorage.getItem(REFRESH_KEY);
    if (!refresh) return false;
    try {
        const res = await fetch(`${BASE}/auth/refresh`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: refresh }),
        });
        if (res.ok) {
            setTokens(await res.json());
            return true;
        }
        // Only a real auth rejection means the refresh token is dead - clear and
        // sign out. A 502/503/504 is the backend momentarily unreachable (a
        // restart, a proxy hiccup); wiping tokens there would sign the learner
        // out mid-interview over a transient blip, with a perfectly valid token.
        if (res.status === 401 || res.status === 403) clearTokens();
        return false;
    } catch {
        // Network error: transient, keep the tokens and let the caller retry.
        return false;
    }
}

export async function register(email: string, password: string): Promise<void> {
    const t = await request<Tokens>('/auth/register', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
    }, false);
    setTokens(t);
}

export async function login(email: string, password: string): Promise<void> {
    const t = await request<Tokens>('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
    }, false);
    setTokens(t);
}

export const me = () => request<Me>('/auth/me');
export const listInterviews = () => request<InterviewSummary[]>('/interviews');
export const getBrief = (id: string) => request<Brief>(`/interviews/${id}/brief`);
export const createInterview = () => request<InterviewSummary>('/interviews', { method: 'POST' });
export const getInterview = (id: string) => request<InterviewDetail>(`/interviews/${id}`);
export const deleteInterview = (id: string) =>
    request<void>(`/interviews/${id}`, { method: 'DELETE' });

export const sendMessage = (id: string, message: string, modality: Modality) =>
    request<ChatReply>(`/interviews/${id}/chat`, {
        method: 'POST',
        body: JSON.stringify({ message, modality }),
    });
