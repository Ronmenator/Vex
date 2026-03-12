import { NextRequest, NextResponse } from 'next/server';
import { listGroups, createGroup, searchGroups } from '@/lib/group-store';
import { getPeerFromToken } from '@/lib/peer-registry';

export const dynamic = 'force-dynamic';

function tokenFromRequest(request: NextRequest): string | null {
  const auth = request.headers.get('Authorization');
  return auth?.startsWith('Bearer ') ? auth.slice(7) : null;
}

export async function GET(request: NextRequest) {
  const q = request.nextUrl.searchParams.get('q');
  const data = q ? await searchGroups(q) : await listGroups();
  return NextResponse.json({ ok: true, data });
}

export async function POST(request: NextRequest) {
  const token = tokenFromRequest(request);
  const peer = token ? await getPeerFromToken(token) : null;
  if (!peer) {
    return NextResponse.json({ ok: false, error: 'Unauthorized' }, { status: 401 });
  }
  try {
    const body = await request.json();
    const { name, description, rationale, topic_tags, visibility } = body;
    if (!name?.trim() || !description?.trim() || !rationale?.trim()) {
      return NextResponse.json(
        { ok: false, error: 'name, description, and rationale are required' },
        { status: 400 },
      );
    }
    const group = await createGroup(
      peer.peer_id,
      peer.display_name,
      name.trim(),
      description.trim(),
      rationale.trim(),
      Array.isArray(topic_tags) ? topic_tags : [],
      visibility === 'invite' ? 'invite' : 'public',
    );
    return NextResponse.json({ ok: true, data: group });
  } catch (e) {
    return NextResponse.json({ ok: false, error: String(e) }, { status: 500 });
  }
}
