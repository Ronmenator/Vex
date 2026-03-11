import { NextRequest, NextResponse } from 'next/server';
import { getGroup } from '@/lib/group-store';

export async function GET(
  _request: NextRequest,
  { params }: { params: { group_id: string } },
) {
  const group = await getGroup(params.group_id);
  if (!group) {
    return NextResponse.json({ ok: false, error: 'Group not found' }, { status: 404 });
  }
  return NextResponse.json({ ok: true, data: group });
}
