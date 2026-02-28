import { StreamClient } from '@stream-io/node-sdk';
import { NextResponse } from 'next/server';

export async function POST(req: Request) {
    try {
        const { userId } = await req.json();

        if (!userId) {
            return NextResponse.json({ error: 'User ID is required' }, { status: 400 });
        }

        const apiKey = process.env.NEXT_PUBLIC_STREAM_API_KEY;
        const apiSecret = process.env.STREAM_API_SECRET;

        if (!apiKey || !apiSecret) {
            return NextResponse.json({ error: 'Stream credentials not configured' }, { status: 500 });
        }

        const client = new StreamClient(apiKey, apiSecret);

        // Create token valid for 1 hour
        const token = client.generateUserToken({ user_id: userId });

        return NextResponse.json({ token });
    } catch (error) {
        console.error("Token generation error:", error);
        return NextResponse.json({ error: 'Failed to generate token' }, { status: 500 });
    }
}
