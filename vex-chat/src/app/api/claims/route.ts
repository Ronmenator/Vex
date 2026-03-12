import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

// Claims are human-submitted reports of harm — stub returns empty list
export async function GET() {
  return NextResponse.json({ ok: true, data: [] });
}
