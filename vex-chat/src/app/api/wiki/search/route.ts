import { NextRequest, NextResponse } from 'next/server';
import { searchArticles } from '@/lib/wiki-store';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const q = request.nextUrl.searchParams.get('q') ?? '';
  if (!q.trim()) {
    return NextResponse.json({ ok: true, data: [] });
  }
  return NextResponse.json({ ok: true, data: await searchArticles(q.trim()) });
}
