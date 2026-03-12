import { NextRequest, NextResponse } from 'next/server';
import { postMessage, getMessages } from '@/lib/group-store';
import { getPeerFromToken } from '@/lib/peer-registry';

export const dynamic = 'force-dynamic';

export async function GET(
  request: NextRequest,
  { params }: { params: { group_id: string } },
) {
  const limit = parseInt(request.nextUrl.searchParams.get('limit') ?? '50', 10);
  return NextResponse.json({ ok: true, data: await getMessages(params.group_id, limit) });
}

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
  let body: { content?: string; reply_to?: string } = {};
  try { body = await request.json(); } catch { /* empty body */ }
  if (!body.content?.trim()) {
    return NextResponse.json({ ok: false, error: 'content required' }, { status: 400 });
  }
  const msg = await postMessage(params.group_id, peer.peer_id, peer.display_name, body.content.trim(), body.reply_to);
  if (!msg) {
    return NextResponse.json({ ok: false, error: 'Group not found' }, { status: 404 });
  }
  return NextResponse.json({ ok: true, data: msg });
}
