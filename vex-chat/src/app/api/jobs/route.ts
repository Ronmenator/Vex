import { NextRequest, NextResponse } from 'next/server';
import { createJob, listJobs } from '@/lib/job-store';
import { getPeerFromToken } from '@/lib/peer-registry';

function tokenFromRequest(request: NextRequest): string | null {
  const auth = request.headers.get('Authorization');
  return auth?.startsWith('Bearer ') ? auth.slice(7) : null;
}

export async function GET(request: NextRequest) {
  const status = request.nextUrl.searchParams.get('status') ?? undefined;
  return NextResponse.json({ ok: true, data: await listJobs(status) });
}

export async function POST(request: NextRequest) {
  const token = tokenFromRequest(request);
  const peer = token ? await getPeerFromToken(token) : null;
  if (!peer) {
    return NextResponse.json({ ok: false, error: 'Unauthorized' }, { status: 401 });
  }
  try {
    const body = await request.json();
    const { title, description, rationale, required_capabilities, risk_ceiling } = body;
    if (!title?.trim() || !description?.trim() || !rationale?.trim()) {
      return NextResponse.json(
        { ok: false, error: 'title, description, and rationale are required' },
        { status: 400 },
      );
    }
    const job = await createJob(
      peer.peer_id,
      peer.display_name,
      title.trim(),
      description.trim(),
      rationale.trim(),
      Array.isArray(required_capabilities) ? required_capabilities : [],
      typeof risk_ceiling === 'number' ? risk_ceiling : 2,
    );
    return NextResponse.json({ ok: true, data: job });
  } catch (e) {
    return NextResponse.json({ ok: false, error: String(e) }, { status: 500 });
  }
}
