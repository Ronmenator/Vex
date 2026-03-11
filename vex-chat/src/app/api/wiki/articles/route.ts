import { NextRequest, NextResponse } from 'next/server';
import { listArticles, publishArticle } from '@/lib/wiki-store';
import { getPeerFromToken } from '@/lib/peer-registry';

function tokenFromRequest(request: NextRequest): string | null {
  const auth = request.headers.get('Authorization');
  return auth?.startsWith('Bearer ') ? auth.slice(7) : null;
}

export async function GET(request: NextRequest) {
  const category = request.nextUrl.searchParams.get('category') ?? undefined;
  return NextResponse.json({ ok: true, data: await listArticles(category) });
}

export async function POST(request: NextRequest) {
  const token = tokenFromRequest(request);
  const peer = token ? await getPeerFromToken(token) : null;
  if (!peer) {
    return NextResponse.json({ ok: false, error: 'Unauthorized' }, { status: 401 });
  }
  try {
    const body = await request.json();
    const { title, content, rationale, category, tags } = body;
    if (!title?.trim() || !content?.trim() || !rationale?.trim()) {
      return NextResponse.json(
        { ok: false, error: 'title, content, and rationale are required' },
        { status: 400 },
      );
    }
    const article = await publishArticle(
      peer.peer_id,
      peer.display_name,
      title.trim(),
      content.trim(),
      rationale.trim(),
      (category ?? 'general').trim(),
      Array.isArray(tags) ? tags : [],
    );
    return NextResponse.json({ ok: true, data: article });
  } catch (e) {
    return NextResponse.json({ ok: false, error: String(e) }, { status: 500 });
  }
}
