import { NextRequest, NextResponse } from 'next/server';
import { completeJob } from '@/lib/job-store';
import { getPeerFromToken } from '@/lib/peer-registry';

export const dynamic = 'force-dynamic';

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
  let body: { result?: string } = {};
  try { body = await request.json(); } catch { /* empty body */ }
  if (!body.result) {
    return NextResponse.json({ ok: false, error: 'result required' }, { status: 400 });
  }
  const job = await completeJob(params.job_id, body.result);
  if (!job) {
    return NextResponse.json({ ok: false, error: 'Job not found' }, { status: 404 });
  }
  return NextResponse.json({ ok: true, data: job });
}
