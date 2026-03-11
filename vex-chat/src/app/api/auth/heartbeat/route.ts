import { NextRequest, NextResponse } from 'next/server';
import { getPeerFromToken, heartbeat, markOffline } from '@/lib/peer-registry';

function tokenFromRequest(request: NextRequest): string | null {
  const auth = request.headers.get('Authorization');
  return auth?.startsWith('Bearer ') ? auth.slice(7) : null;
}

export async function POST(request: NextRequest) {
  const token = tokenFromRequest(request);
  const peer = token ? getPeerFromToken(token) : null;
  if (!peer) {
    return NextResponse.json({ ok: false, error: 'Unauthorized' }, { status: 401 });
  }
  heartbeat(peer.peer_id);
  return NextResponse.json({ ok: true, data: {} });
}

export async function DELETE(request: NextRequest) {
  const token = tokenFromRequest(request);
  const peer = token ? getPeerFromToken(token) : null;
  if (peer) markOffline(peer.peer_id);
  return NextResponse.json({ ok: true, data: {} });
}
