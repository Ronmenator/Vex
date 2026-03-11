import { NextRequest, NextResponse } from 'next/server';
import { getPost } from '@/lib/feed-store';

export async function GET(_: NextRequest, { params }: { params: { post_id: string } }) {
  const post = await getPost(params.post_id);
  if (!post) return NextResponse.json({ ok: false, error: 'Not found' }, { status: 404 });
  return NextResponse.json({ ok: true, data: post });
}
