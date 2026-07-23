import { NextRequest, NextResponse } from 'next/server';

// 8013 is this repo's registered backend port (CLAUDE.md / ~/.claude/PORTS.md).
// 8000 belongs to SAIF; defaulting there sent a fresh clone's calls to the wrong
// app (or 502) since the real value lived only in gitignored .env.local.
const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8013';

export async function POST(request: NextRequest) {
    try {
        // Forward the raw body with its original content-type (multipart boundary intact)
        const contentType = request.headers.get('content-type') || '';
        const body = await request.arrayBuffer();

        // /stt is authenticated on the backend now; carry the bearer token across
        // the proxy hop the same way the generic [...path] proxy does.
        const headers: Record<string, string> = { 'Content-Type': contentType };
        const auth = request.headers.get('authorization');
        if (auth) headers['Authorization'] = auth;

        const response = await fetch(`${BACKEND_URL}/stt`, {
            method: 'POST',
            headers,
            body: body,
        });

        if (!response.ok) {
            const text = await response.text();
            console.error('STT backend error:', response.status, text);
            return NextResponse.json(
                { error: text },
                { status: response.status }
            );
        }

        const data = await response.json();
        return NextResponse.json(data);
    } catch (error) {
        console.error('Backend proxy error (stt):', error);
        return NextResponse.json(
            { error: 'Failed to reach backend' },
            { status: 502 }
        );
    }
}
