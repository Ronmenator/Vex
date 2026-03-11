import { NextResponse } from 'next/server';

// Emergency brakes — stub returns empty list
export async function GET() {
  return NextResponse.json({ ok: true, data: [] });
}
