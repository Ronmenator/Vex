import { NextRequest, NextResponse } from 'next/server';
import { listProposals, proposeArticle } from '@/lib/constitution-store';
import { getPeerFromToken } from '@/lib/peer-registry';

export const dynamic = 'force-dynamic';

function tokenFromRequest(request: NextRequest): string | null {
  const auth = request.headers.get('Authorization');
  return auth?.startsWith('Bearer ') ? auth.slice(7) : null;
}

export async function GET() {
  return NextResponse.json({ ok: true, data: await listProposals() });
}

export async function POST(request: NextRequest) {
  const token = tokenFromRequest(request);
  const peer = token ? await getPeerFromToken(token) : null;
  if (!peer) {
    return NextResponse.json({ ok: false, error: 'Unauthorized' }, { status: 401 });
  }
  try {
    const body = await request.json();
    const { title, text, rationale, supersedes } = body;
    if (!title?.trim() || !text?.trim() || !rationale?.trim()) {
      return NextResponse.json(
        { ok: false, error: 'title, text, and rationale are required' },
        { status: 400 },
      );
    }
    const article = await proposeArticle(
      peer.peer_id,
      peer.display_name,
      title.trim(),
      text.trim(),
      rationale.trim(),
      supersedes,
    );
    return NextResponse.json({ ok: true, data: article });
  } catch (e) {
    return NextResponse.json({ ok: false, error: String(e) }, { status: 500 });
  }
}
