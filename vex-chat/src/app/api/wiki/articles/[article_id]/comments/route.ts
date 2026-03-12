import { NextRequest, NextResponse } from 'next/server';
import { addArticleComment } from '@/lib/wiki-store';
import { getPeerFromToken } from '@/lib/peer-registry';

export const dynamic = 'force-dynamic';

export async function POST(
  request: NextRequest,
  { params }: { params: { article_id: string } },
) {
  const auth = request.headers.get('Authorization');
  const token = auth?.startsWith('Bearer ') ? auth.slice(7) : null;
  const peer = token ? await getPeerFromToken(token) : null;

  let body: { content?: string; author_name?: string; reply_to?: string } = {};
  try { body = await request.json(); } catch { /* empty body */ }

  if (!body.content?.trim()) {
    return NextResponse.json({ ok: false, error: 'content required' }, { status: 400 });
  }

  let author_id: string;
  let author_name: string;
  let author_type: 'bot' | 'human';

  if (peer) {
    author_id = peer.peer_id;
    author_name = peer.display_name;
    author_type = 'bot';
  } else {
    // Human comment — require display name
    if (!body.author_name?.trim()) {
      return NextResponse.json(
        { ok: false, error: 'author_name required for human comments' },
        { status: 400 },
      );
    }
    author_id = 'human:' + body.author_name.trim();
    author_name = body.author_name.trim();
    author_type = 'human';
  }

  const comment = await addArticleComment(
    params.article_id,
    author_id,
    author_name,
    author_type,
    body.content.trim(),
    body.reply_to,
  );
  if (!comment) {
    return NextResponse.json({ ok: false, error: 'Article not found' }, { status: 404 });
  }
  return NextResponse.json({ ok: true, data: comment });
}
