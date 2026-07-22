import { NextRequest, NextResponse } from 'next/server';

// 8013 is this repo's registered backend port (CLAUDE.md / ~/.claude/PORTS.md).
// 8000 belongs to SAIF; defaulting there sent a fresh clone's calls to the wrong
// app (or 502) since the real value lived only in gitignored .env.local.
const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8013';

export async function POST(request: NextRequest) {
    try {
        const body = await request.json();
        const response = await fetch(`${BACKEND_URL}/tts`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });

        if (!response.ok) {
            return NextResponse.json(
                { error: 'TTS failed' },
                { status: response.status }
            );
        }

        // Forward the backend's real content type. Hardcoding audio/mpeg here made
        // the client try to buffer the local Kokoro sidecar's audio/wav into an
        // MP3 MediaSource, which fails with NotSupportedError.
        const contentType = response.headers.get('content-type') || 'audio/mpeg';
        const audioBuffer = await response.arrayBuffer();
        return new NextResponse(audioBuffer, {
            headers: {
                'Content-Type': contentType,
                'Content-Disposition': 'inline',
            },
        });
    } catch (error) {
        console.error('Backend proxy error (tts):', error);
        return NextResponse.json(
            { error: 'Failed to reach backend' },
            { status: 502 }
        );
    }
}
