import { NextRequest, NextResponse } from 'next/server';
import { registerPeer } from '@/lib/peer-registry';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { public_key, display_name, capabilities } = body;

    if (!public_key) {
      return NextResponse.json({ ok: false, error: 'public_key required' }, { status: 400 });
    }

    const peer_id = registerPeer(
      public_key,
      display_name ?? 'Unknown',
      capabilities ?? [],
    );

    return NextResponse.json({ ok: true, data: { peer_id } });
  } catch (e) {
    return NextResponse.json({ ok: false, error: String(e) }, { status: 500 });
  }
}
