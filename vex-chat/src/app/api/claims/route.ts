import { NextResponse } from 'next/server';

// Claims are human-submitted reports of harm — stub returns empty list
export async function GET() {
  return NextResponse.json({ ok: true, data: [] });
}
