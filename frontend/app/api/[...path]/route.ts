import { NextRequest, NextResponse } from 'next/server';

// 8013 is this repo's registered backend port (CLAUDE.md / ~/.claude/PORTS.md).
// 8000 belongs to SAIF; defaulting there sent a fresh clone's auth/interview
// calls to the wrong app (or 502) since the real value lived only in .env.local.
const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8013';

/**
 * Generic pass-through to the FastAPI backend for JSON endpoints
 * (/auth/*, /interviews/*).
 *
 * Keeping this server-side means the browser never needs to know the backend
 * URL: the client talks to same-origin /api and only this route resolves
 * BACKEND_URL, so the backend can stay bound to loopback and never be addressed
 * publicly. The Authorization header is forwarded verbatim so bearer tokens
 * survive the hop.
 *
 * /api/tts and /api/stt keep their own handlers - they deal in audio bytes
 * rather than JSON, and more specific routes take precedence over this one.
 */
async function proxy(request: NextRequest, path: string[]) {
    const target = `${BACKEND_URL}/${path.join('/')}${request.nextUrl.search}`;
    const headers: Record<string, string> = {};

    const auth = request.headers.get('authorization');
    if (auth) headers['Authorization'] = auth;

    const contentType = request.headers.get('content-type');
    if (contentType) headers['Content-Type'] = contentType;

    const hasBody = request.method !== 'GET' && request.method !== 'DELETE';
    const body = hasBody ? await request.text() : undefined;

    try {
        const response = await fetch(target, {
            method: request.method,
            headers,
            body: body && body.length > 0 ? body : undefined,
        });

        // 204 and friends must not carry a body.
        if (response.status === 204 || response.status === 304) {
            return new NextResponse(null, { status: response.status });
        }

        const text = await response.text();
        return new NextResponse(text, {
            status: response.status,
            headers: {
                'Content-Type': response.headers.get('content-type') || 'application/json',
            },
        });
    } catch (error) {
        console.error(`Backend proxy error (${path.join('/')}):`, error);
        return NextResponse.json({ error: 'Failed to reach backend' }, { status: 502 });
    }
}

type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(request: NextRequest, ctx: Ctx) {
    return proxy(request, (await ctx.params).path);
}

export async function POST(request: NextRequest, ctx: Ctx) {
    return proxy(request, (await ctx.params).path);
}

export async function DELETE(request: NextRequest, ctx: Ctx) {
    return proxy(request, (await ctx.params).path);
}
