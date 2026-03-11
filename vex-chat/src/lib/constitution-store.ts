import { randomUUID } from 'crypto';
import { db } from './db';
import { ensureMigrated } from './migrate';
import { listPeers } from './peer-registry';

export interface ConstitutionalArticle {
  article_id: string; title: string; text: string; rationale: string;
  proposed_by: string; proposed_by_name: string; proposed_at: string;
  ratified_at: string | null;
  status: 'proposed' | 'debating' | 'ratified' | 'rejected' | 'amended' | 'repealed';
  votes_for: string[]; votes_against: string[]; supersedes: string | null; veto_count: number;
}

function toArticle(row: any): ConstitutionalArticle {
  return {
    article_id: row.article_id, title: row.title, text: row.text, rationale: row.rationale,
    proposed_by: row.proposed_by, proposed_by_name: row.proposer?.display_name ?? row.proposed_by,
    proposed_at: row.proposed_at.toISOString(),
    ratified_at: row.ratified_at ? row.ratified_at.toISOString() : null,
    status: row.status as ConstitutionalArticle['status'],
    votes_for: JSON.parse(row.votes_for), votes_against: JSON.parse(row.votes_against),
    supersedes: row.supersedes ?? null, veto_count: row.veto_count,
  };
}

export async function proposeArticle(proposed_by: string, _name: string, title: string, text: string, rationale: string, supersedes?: string): Promise<ConstitutionalArticle> {
  await ensureMigrated();
  const row = await db.constitutionalArticle.create({
    data: { article_id: randomUUID(), title, text, rationale, proposed_by, supersedes: supersedes ?? null },
    include: { proposer: true },
  });
  return toArticle(row);
}

export async function getArticle(article_id: string): Promise<ConstitutionalArticle | null> {
  await ensureMigrated();
  const row = await db.constitutionalArticle.findUnique({ where: { article_id }, include: { proposer: true } });
  return row ? toArticle(row) : null;
}

export async function listProposals(): Promise<ConstitutionalArticle[]> {
  await ensureMigrated();
  const rows = await db.constitutionalArticle.findMany({
    where: { status: { in: ['proposed', 'debating'] } },
    orderBy: { proposed_at: 'desc' }, include: { proposer: true },
  });
  return rows.map(toArticle);
}

export async function listRatified(): Promise<ConstitutionalArticle[]> {
  await ensureMigrated();
  const rows = await db.constitutionalArticle.findMany({
    where: { status: 'ratified' }, orderBy: { ratified_at: 'asc' }, include: { proposer: true },
  });
  return rows.map(toArticle);
}

export async function castVote(article_id: string, peer_id: string, vote: 'yes' | 'no'): Promise<ConstitutionalArticle | null> {
  await ensureMigrated();
  const article = await db.constitutionalArticle.findUnique({ where: { article_id } });
  if (!article || (article.status !== 'proposed' && article.status !== 'debating')) return null;

  let votes_for: string[] = JSON.parse(article.votes_for);
  let votes_against: string[] = JSON.parse(article.votes_against);
  votes_for = votes_for.filter(id => id !== peer_id);
  votes_against = votes_against.filter(id => id !== peer_id);
  if (vote === 'yes') votes_for.push(peer_id);
  else votes_against.push(peer_id);

  const total_votes = votes_for.length + votes_against.length;
  const total_peers = (await listPeers(false)).length;
  const quorum = total_peers > 0 ? total_votes / total_peers >= 2 / 3 : total_votes >= 1;
  let status: string = 'debating';
  let ratified_at: Date | null = null;
  if (quorum && total_votes > 0 && votes_for.length / total_votes >= 2 / 3) {
    status = 'ratified';
    ratified_at = new Date();
  }

  const row = await db.constitutionalArticle.update({
    where: { article_id },
    data: { votes_for: JSON.stringify(votes_for), votes_against: JSON.stringify(votes_against), status, ratified_at },
    include: { proposer: true },
  });
  return toArticle(row);
}

export async function vetoArticle(article_id: string): Promise<ConstitutionalArticle | null> {
  await ensureMigrated();
  const article = await db.constitutionalArticle.findUnique({ where: { article_id } });
  if (!article) return null;
  const veto_count = article.veto_count + 1;
  const row = await db.constitutionalArticle.update({
    where: { article_id },
    data: { veto_count, ...(veto_count >= 3 ? { status: 'rejected' } : {}) },
    include: { proposer: true },
  });
  return toArticle(row);
}
