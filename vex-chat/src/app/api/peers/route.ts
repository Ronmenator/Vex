import { NextRequest, NextResponse } from 'next/server';
import { listPeers } from '@/lib/peer-registry';

export async function GET(request: NextRequest) {
  const online = request.nextUrl.searchParams.get('online') === 'true';
  return NextResponse.json({ ok: true, data: listPeers(online) });
}
