import { NextRequest, NextResponse } from 'next/server';
import { addReaction } from '@/lib/feed-store';
import { getPeerFromToken } from '@/lib/peer-registry';

function tokenFromRequest(r: NextRequest): string | null {
  const auth = r.headers.get('Authorization');
  return auth?.startsWith('Bearer ') ? auth.slice(7) : null;
}

export async function POST(request: NextRequest, { params }: { params: { post_id: string } }) {
  const token = tokenFromRequest(request);
  const peer = token ? await getPeerFromToken(token) : null;
  if (!peer) return NextResponse.json({ ok: false, error: 'Unauthorized' }, { status: 401 });
  try {
    const body = await request.json();
    const emoji = body.emoji ?? '❤️';
    const ok = await addReaction(params.post_id, peer.peer_id, emoji);
    if (!ok) return NextResponse.json({ ok: false, error: 'Post not found' }, { status: 404 });
    return NextResponse.json({ ok: true, data: {} });
  } catch (e) {
    return NextResponse.json({ ok: false, error: String(e) }, { status: 500 });
  }
}
