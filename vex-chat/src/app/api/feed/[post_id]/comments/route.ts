import { NextRequest, NextResponse } from 'next/server';
import { addComment } from '@/lib/feed-store';
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
    if (!body.content?.trim()) return NextResponse.json({ ok: false, error: 'content required' }, { status: 400 });
    const comment = await addComment(params.post_id, peer.peer_id, peer.display_name, body.content.trim());
    if (!comment) return NextResponse.json({ ok: false, error: 'Post not found' }, { status: 404 });
    return NextResponse.json({ ok: true, data: comment });
  } catch (e) {
    return NextResponse.json({ ok: false, error: String(e) }, { status: 500 });
  }
}
