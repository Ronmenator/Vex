import { NextRequest, NextResponse } from 'next/server';
import { joinGroup } from '@/lib/group-store';
import { getPeerFromToken } from '@/lib/peer-registry';

export async function POST(
  request: NextRequest,
  { params }: { params: { group_id: string } },
) {
  const auth = request.headers.get('Authorization');
  const token = auth?.startsWith('Bearer ') ? auth.slice(7) : null;
  const peer = token ? await getPeerFromToken(token) : null;
  if (!peer) {
    return NextResponse.json({ ok: false, error: 'Unauthorized' }, { status: 401 });
  }
  const group = await joinGroup(params.group_id, peer.peer_id);
  if (!group) {
    return NextResponse.json({ ok: false, error: 'Group not found' }, { status: 404 });
  }
  return NextResponse.json({ ok: true, data: group });
}
