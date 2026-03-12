import { NextRequest, NextResponse } from 'next/server';
import { issueNonce } from '@/lib/peer-registry';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { peer_id } = body;

    if (!peer_id) {
      return NextResponse.json({ ok: false, error: 'peer_id required' }, { status: 400 });
    }

    const nonce = issueNonce(peer_id);
    return NextResponse.json({ ok: true, data: { nonce } });
  } catch (e) {
    return NextResponse.json({ ok: false, error: String(e) }, { status: 500 });
  }
}
