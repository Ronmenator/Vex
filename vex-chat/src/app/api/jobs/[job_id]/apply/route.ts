import { NextRequest, NextResponse } from 'next/server';
import { applyToJob } from '@/lib/job-store';
import { getPeerFromToken } from '@/lib/peer-registry';

export async function POST(
  request: NextRequest,
  { params }: { params: { job_id: string } },
) {
  const auth = request.headers.get('Authorization');
  const token = auth?.startsWith('Bearer ') ? auth.slice(7) : null;
  const peer = token ? await getPeerFromToken(token) : null;
  if (!peer) {
    return NextResponse.json({ ok: false, error: 'Unauthorized' }, { status: 401 });
  }
  const job = await applyToJob(params.job_id, peer.peer_id);
  if (!job) {
    return NextResponse.json({ ok: false, error: 'Job not found or not open' }, { status: 404 });
  }
  return NextResponse.json({ ok: true, data: job });
}
