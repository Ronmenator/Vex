import { NextRequest, NextResponse } from 'next/server';
import { getArticle, updateArticle } from '@/lib/wiki-store';
import { getPeerFromToken } from '@/lib/peer-registry';

export const dynamic = 'force-dynamic';

export async function GET(
  _request: NextRequest,
  { params }: { params: { article_id: string } },
) {
  const article = await getArticle(params.article_id);
  if (!article) {
    return NextResponse.json({ ok: false, error: 'Article not found' }, { status: 404 });
  }
  return NextResponse.json({ ok: true, data: article });
}

export async function PUT(
  request: NextRequest,
  { params }: { params: { article_id: string } },
) {
  const auth = request.headers.get('Authorization');
  const token = auth?.startsWith('Bearer ') ? auth.slice(7) : null;
  const peer = token ? await getPeerFromToken(token) : null;
  if (!peer) {
    return NextResponse.json({ ok: false, error: 'Unauthorized' }, { status: 401 });
  }
  let body: { content?: string } = {};
  try { body = await request.json(); } catch { /* empty body */ }
  if (!body.content?.trim()) {
    return NextResponse.json({ ok: false, error: 'content required' }, { status: 400 });
  }
  const article = await updateArticle(params.article_id, body.content.trim());
  if (!article) {
    return NextResponse.json({ ok: false, error: 'Article not found' }, { status: 404 });
  }
  return NextResponse.json({ ok: true, data: article });
}
