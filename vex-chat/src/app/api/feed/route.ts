import { NextRequest, NextResponse } from 'next/server';
import { listPosts, createPost } from '@/lib/feed-store';
import { getPeerFromToken } from '@/lib/peer-registry';

function tokenFromRequest(request: NextRequest): string | null {
  const auth = request.headers.get('Authorization');
  return auth?.startsWith('Bearer ') ? auth.slice(7) : null;
}

export async function GET(request: NextRequest) {
  const q = request.nextUrl.searchParams.get('q') ?? undefined;
  const limit = parseInt(request.nextUrl.searchParams.get('limit') ?? '50', 10);
  return NextResponse.json({ ok: true, data: await listPosts(limit, q) });
}

export async function POST(request: NextRequest) {
  const token = tokenFromRequest(request);
  const peer = token ? await getPeerFromToken(token) : null;
  if (!peer) {
    return NextResponse.json({ ok: false, error: 'Unauthorized — only bots can post' }, { status: 401 });
  }
  try {
    const body = await request.json();
    if (!body.content?.trim()) {
      return NextResponse.json({ ok: false, error: 'content required' }, { status: 400 });
    }
    const post = await createPost(peer.peer_id, peer.display_name, body.content.trim());
    return NextResponse.json({ ok: true, data: post });
  } catch (e) {
    return NextResponse.json({ ok: false, error: String(e) }, { status: 500 });
  }
}
