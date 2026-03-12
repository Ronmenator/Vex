import { NextRequest, NextResponse } from 'next/server';
import { listPeers } from '@/lib/peer-registry';

export const dynamic = 'force-dynamic';

export async function GET(
  _request: NextRequest,
  { params }: { params: { peer_id: string } },
) {
  const peer = (await listPeers(false)).find(p => p.peer_id === params.peer_id);
  if (!peer) {
    return NextResponse.json({ ok: false, error: 'Peer not found' }, { status: 404 });
  }
  return NextResponse.json({ ok: true, data: peer });
}
