import { NextRequest, NextResponse } from 'next/server';
import { getJob } from '@/lib/job-store';

export async function GET(
  _request: NextRequest,
  { params }: { params: { job_id: string } },
) {
  const job = await getJob(params.job_id);
  if (!job) {
    return NextResponse.json({ ok: false, error: 'Job not found' }, { status: 404 });
  }
  return NextResponse.json({ ok: true, data: job });
}
