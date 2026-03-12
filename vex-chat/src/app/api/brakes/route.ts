import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

// Emergency brakes — stub returns empty list
export async function GET() {
  return NextResponse.json({ ok: true, data: [] });
}
