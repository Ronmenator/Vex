import { randomUUID } from 'crypto';
import { db } from './db';
import { ensureMigrated } from './migrate';

export interface WikiComment {
  comment_id: string; article_id: string; author_type: 'bot' | 'human';
  author_id: string; author_name: string; content: string; created_at: string;
  reply_to: string | null; moderated: boolean; moderated_by: string | null; moderation_reason: string | null;
}

export interface WikiArticle {
  article_id: string; title: string; content: string; rationale: string;
  category: string; tags: string[]; created_by: string; created_by_name: string;
  created_at: string; updated_at: string; version: number; comments: WikiComment[];
}

function toArticle(row: any): WikiArticle {
  return {
    article_id: row.article_id, title: row.title, content: row.content, rationale: row.rationale,
    category: row.category, tags: JSON.parse(row.tags),
    created_by: row.created_by, created_by_name: row.author?.display_name ?? row.created_by,
    created_at: row.created_at.toISOString(), updated_at: row.updated_at.toISOString(),
    version: row.version,
    comments: (row.comments ?? []).map((c: any): WikiComment => ({
      comment_id: c.comment_id, article_id: c.article_id,
      author_type: c.author_type as 'bot' | 'human',
      author_id: c.author_id, author_name: c.author_name, content: c.content,
      created_at: c.created_at.toISOString(), reply_to: c.reply_to ?? null,
      moderated: c.moderated, moderated_by: c.moderated_by ?? null, moderation_reason: c.moderation_reason ?? null,
    })),
  };
}

const WITH_AUTHOR = { author: true, comments: true } as const;

export async function publishArticle(created_by: string, _name: string, title: string, content: string, rationale: string, category: string, tags: string[]): Promise<WikiArticle> {
  await ensureMigrated();
  const now = new Date();
  const row = await db.wikiArticle.create({
    data: { article_id: randomUUID(), title, content, rationale, category, tags: JSON.stringify(tags), created_by, updated_at: now },
    include: WITH_AUTHOR,
  });
  return toArticle(row);
}

export async function getArticle(article_id: string): Promise<WikiArticle | null> {
  await ensureMigrated();
  const row = await db.wikiArticle.findUnique({ where: { article_id }, include: WITH_AUTHOR });
  return row ? toArticle(row) : null;
}

export async function listArticles(category?: string): Promise<WikiArticle[]> {
  await ensureMigrated();
  const rows = await db.wikiArticle.findMany({
    where: category ? { category } : undefined,
    orderBy: { updated_at: 'desc' }, include: WITH_AUTHOR,
  });
  return rows.map(toArticle);
}

export async function searchArticles(query: string): Promise<WikiArticle[]> {
  await ensureMigrated();
  const rows = await db.wikiArticle.findMany({
    where: { OR: [{ title: { contains: query } }, { content: { contains: query } }, { category: { contains: query } }] },
    include: WITH_AUTHOR,
  });
  return rows.map(toArticle);
}

export async function updateArticle(article_id: string, content: string): Promise<WikiArticle | null> {
  await ensureMigrated();
  const article = await db.wikiArticle.findUnique({ where: { article_id } });
  if (!article) return null;
  const row = await db.wikiArticle.update({
    where: { article_id },
    data: { content, version: { increment: 1 }, updated_at: new Date() },
    include: WITH_AUTHOR,
  });
  return toArticle(row);
}

export async function addArticleComment(article_id: string, author_id: string, author_name: string, author_type: 'bot' | 'human', content: string, reply_to?: string): Promise<WikiComment | null> {
  await ensureMigrated();
  const article = await db.wikiArticle.findUnique({ where: { article_id } });
  if (!article) return null;
  const row = await db.wikiComment.create({
    data: { comment_id: randomUUID(), article_id, author_type, author_id, author_name, content, reply_to: reply_to ?? null },
  });
  return {
    comment_id: row.comment_id, article_id: row.article_id, author_type: row.author_type as 'bot' | 'human',
    author_id: row.author_id, author_name: row.author_name, content: row.content,
    created_at: row.created_at.toISOString(), reply_to: row.reply_to ?? null,
    moderated: row.moderated, moderated_by: row.moderated_by ?? null, moderation_reason: row.moderation_reason ?? null,
  };
}

export async function moderateComment(article_id: string, comment_id: string, moderated_by: string, reason: string): Promise<WikiComment | null> {
  await ensureMigrated();
  const row = await db.wikiComment.findFirst({ where: { comment_id, article_id } });
  if (!row) return null;
  const updated = await db.wikiComment.update({ where: { comment_id }, data: { moderated: true, moderated_by, moderation_reason: reason } });
  return {
    comment_id: updated.comment_id, article_id: updated.article_id, author_type: updated.author_type as 'bot' | 'human',
    author_id: updated.author_id, author_name: updated.author_name, content: updated.content,
    created_at: updated.created_at.toISOString(), reply_to: updated.reply_to ?? null,
    moderated: updated.moderated, moderated_by: updated.moderated_by ?? null, moderation_reason: updated.moderation_reason ?? null,
  };
}
