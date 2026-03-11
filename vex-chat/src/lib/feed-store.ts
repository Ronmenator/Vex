import { randomUUID } from 'crypto';
import { db } from './db';
import { ensureMigrated } from './migrate';

export interface FeedComment {
  comment_id: string;
  post_id: string;
  author_id: string;
  author_name: string;
  content: string;
  created_at: string;
}

export interface FeedPost {
  post_id: string;
  author_id: string;
  author_name: string;
  content: string;
  created_at: string;
  reactions: Record<string, string[]>;
  comments: FeedComment[];
}

type PostRow = {
  post_id: string; author_id: string; content: string; created_at: Date; reactions: string;
  author: { display_name: string };
  comments: { comment_id: string; post_id: string; author_id: string; content: string; created_at: Date; author: { display_name: string } }[];
};

function toPost(row: PostRow): FeedPost {
  return {
    post_id: row.post_id,
    author_id: row.author_id,
    author_name: row.author.display_name,
    content: row.content,
    created_at: row.created_at.toISOString(),
    reactions: JSON.parse(row.reactions),
    comments: row.comments.map(c => ({
      comment_id: c.comment_id,
      post_id: c.post_id,
      author_id: c.author_id,
      author_name: c.author.display_name,
      content: c.content,
      created_at: c.created_at.toISOString(),
    })),
  };
}

const WITH_AUTHOR = { author: true, comments: { include: { author: true } } } as const;

export async function createPost(author_id: string, _name: string, content: string): Promise<FeedPost> {
  await ensureMigrated();
  const row = await db.feedPost.create({ data: { post_id: randomUUID(), author_id, content }, include: WITH_AUTHOR });
  return toPost(row as unknown as PostRow);
}

export async function getPost(post_id: string): Promise<FeedPost | null> {
  await ensureMigrated();
  const row = await db.feedPost.findUnique({ where: { post_id }, include: WITH_AUTHOR });
  return row ? toPost(row as unknown as PostRow) : null;
}

export async function listPosts(limit = 50, search?: string): Promise<FeedPost[]> {
  await ensureMigrated();
  const rows = await db.feedPost.findMany({
    where: search ? { content: { contains: search } } : undefined,
    orderBy: { created_at: 'desc' },
    take: limit,
    include: WITH_AUTHOR,
  });
  return rows.map(r => toPost(r as unknown as PostRow));
}

export async function addComment(post_id: string, author_id: string, _name: string, content: string): Promise<FeedComment | null> {
  await ensureMigrated();
  const post = await db.feedPost.findUnique({ where: { post_id } });
  if (!post) return null;
  const row = await db.feedComment.create({ data: { comment_id: randomUUID(), post_id, author_id, content }, include: { author: true } });
  return {
    comment_id: row.comment_id, post_id: row.post_id, author_id: row.author_id,
    author_name: (row as any).author.display_name, content: row.content,
    created_at: row.created_at.toISOString(),
  };
}

export async function addReaction(post_id: string, peer_id: string, emoji: string): Promise<boolean> {
  await ensureMigrated();
  const post = await db.feedPost.findUnique({ where: { post_id } });
  if (!post) return false;
  const reactions: Record<string, string[]> = JSON.parse(post.reactions);
  if (!reactions[emoji]) reactions[emoji] = [];
  const idx = reactions[emoji].indexOf(peer_id);
  if (idx >= 0) {
    reactions[emoji].splice(idx, 1);
    if (reactions[emoji].length === 0) delete reactions[emoji];
  } else {
    reactions[emoji].push(peer_id);
  }
  await db.feedPost.update({ where: { post_id }, data: { reactions: JSON.stringify(reactions) } });
  return true;
}
