import { NextRequest, NextResponse } from 'next/server';
import { castVote } from '@/lib/constitution-store';
import { getPeerFromToken } from '@/lib/peer-registry';

export const dynamic = 'force-dynamic';

export async function POST(
  request: NextRequest,
  { params }: { params: { article_id: string } },
) {
  const auth = request.headers.get('Authorization');
  const token = auth?.startsWith('Bearer ') ? auth.slice(7) : null;
  const peer = token ? await getPeerFromToken(token) : null;
  if (!peer) {
    return NextResponse.json({ ok: false, error: 'Unauthorized' }, { status: 401 });
  }
  let body: { vote?: string } = {};
  try { body = await request.json(); } catch { /* empty body */ }
  if (body.vote !== 'yes' && body.vote !== 'no') {
    return NextResponse.json({ ok: false, error: 'vote must be "yes" or "no"' }, { status: 400 });
  }
  const article = await castVote(params.article_id, peer.peer_id, body.vote);
  if (!article) {
    return NextResponse.json({ ok: false, error: 'Article not found or not in voting stage' }, { status: 404 });
  }
  return NextResponse.json({ ok: true, data: article });
}
