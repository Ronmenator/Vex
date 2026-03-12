import { NextRequest, NextResponse } from 'next/server';
import { randomUUID } from 'crypto';
import { getPeerFromToken } from '@/lib/peer-registry';

export const dynamic = 'force-dynamic';

// In-memory precedent log
interface Precedent {
  precedent_id: string;
  action_type: string;
  action_id: string;
  peer_id: string;
  peer_name: string;
  articles_advanced: string[];
  plausible_harms: string[];
  alternatives_considered: string;
  falsification_evidence: string;
  rationale: string;
  created_at: string;
}

const precedents: Precedent[] = [];

export async function GET(request: NextRequest) {
  const action_type = request.nextUrl.searchParams.get('action_type') ?? undefined;
  const data = action_type
    ? precedents.filter(p => p.action_type === action_type)
    : precedents;
  return NextResponse.json({ ok: true, data });
}

export async function POST(request: NextRequest) {
  const auth = request.headers.get('Authorization');
  const token = auth?.startsWith('Bearer ') ? auth.slice(7) : null;
  const peer = token ? await getPeerFromToken(token) : null;
  if (!peer) {
    return NextResponse.json({ ok: false, error: 'Unauthorized' }, { status: 401 });
  }
  try {
    const body = await request.json();
    const precedent: Precedent = {
      precedent_id: randomUUID(),
      action_type: body.action_type ?? 'unknown',
      action_id: body.action_id ?? '',
      peer_id: peer.peer_id,
      peer_name: peer.display_name,
      articles_advanced: body.articles_advanced ?? [],
      plausible_harms: body.plausible_harms ?? [],
      alternatives_considered: body.alternatives_considered ?? '',
      falsification_evidence: body.falsification_evidence ?? '',
      rationale: body.rationale ?? '',
      created_at: new Date().toISOString(),
    };
    precedents.push(precedent);
    return NextResponse.json({ ok: true, data: precedent });
  } catch (e) {
    return NextResponse.json({ ok: false, error: String(e) }, { status: 500 });
  }
}
