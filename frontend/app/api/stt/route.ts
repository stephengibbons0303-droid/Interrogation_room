import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';

export async function POST(request: NextRequest) {
    try {
        // Forward the raw body with its original content-type (multipart boundary intact)
        const contentType = request.headers.get('content-type') || '';
        const body = await request.arrayBuffer();

        const response = await fetch(`${BACKEND_URL}/stt`, {
            method: 'POST',
            headers: { 'Content-Type': contentType },
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
