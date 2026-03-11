import { NextRequest, NextResponse } from 'next/server';
import { listPeers } from '@/lib/peer-registry';

export async function GET(request: NextRequest) {
  // Default: online only. Pass ?all=true to include offline peers.
  const all = request.nextUrl.searchParams.get('all') === 'true';
  return NextResponse.json({ ok: true, data: listPeers(!all) });
}
