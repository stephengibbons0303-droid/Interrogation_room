import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';

export async function POST(request: NextRequest) {
    try {
        const formData = await request.formData();
        const response = await fetch(`${BACKEND_URL}/stt`, {
            method: 'POST',
            body: formData,
        });

        if (!response.ok) {
            const text = await response.text();
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
