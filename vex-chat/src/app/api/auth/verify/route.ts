import { NextRequest, NextResponse } from 'next/server';
import { verifyAndIssueToken } from '@/lib/peer-registry';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { peer_id, nonce, signature } = body;

    if (!peer_id || !nonce || !signature) {
      return NextResponse.json({ ok: false, error: 'peer_id, nonce, signature required' }, { status: 400 });
    }

    const token = verifyAndIssueToken(peer_id, nonce, signature);
    if (!token) {
      return NextResponse.json({ ok: false, error: 'Authentication failed' }, { status: 401 });
    }

    return NextResponse.json({ ok: true, data: { token } });
  } catch (e) {
    return NextResponse.json({ ok: false, error: String(e) }, { status: 500 });
  }
}
