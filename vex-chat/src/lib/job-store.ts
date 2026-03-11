import { randomUUID } from 'crypto';
import { db } from './db';
import { ensureMigrated } from './migrate';

export interface Job {
  job_id: string; title: string; description: string; rationale: string;
  posted_by: string; posted_by_name: string; posted_at: string;
  required_capabilities: string[]; risk_ceiling: number;
  status: 'open' | 'assigned' | 'in_progress' | 'completed' | 'cancelled';
  applicants: string[]; assigned_to: string | null;
  result: string | null; completed_at: string | null;
}

function toJob(row: any): Job {
  return {
    job_id: row.job_id, title: row.title, description: row.description, rationale: row.rationale,
    posted_by: row.posted_by, posted_by_name: row.poster?.display_name ?? row.posted_by,
    posted_at: row.posted_at.toISOString(),
    required_capabilities: JSON.parse(row.required_capabilities),
    risk_ceiling: row.risk_ceiling, status: row.status,
    applicants: JSON.parse(row.applicants),
    assigned_to: row.assigned_to ?? null,
    result: row.result ?? null,
    completed_at: row.completed_at ? row.completed_at.toISOString() : null,
  };
}

export async function createJob(
  posted_by: string, _posted_by_name: string, title: string, description: string,
  rationale: string, required_capabilities: string[], risk_ceiling: number,
): Promise<Job> {
  await ensureMigrated();
  const row = await db.job.create({
    data: { job_id: randomUUID(), title, description, rationale, posted_by,
      required_capabilities: JSON.stringify(required_capabilities),
      risk_ceiling: Math.min(risk_ceiling, 2) },
    include: { poster: true },
  });
  return toJob(row);
}

export async function getJob(job_id: string): Promise<Job | null> {
  await ensureMigrated();
  const row = await db.job.findUnique({ where: { job_id }, include: { poster: true } });
  return row ? toJob(row) : null;
}

export async function listJobs(status?: string): Promise<Job[]> {
  await ensureMigrated();
  const rows = await db.job.findMany({
    where: status ? { status } : undefined,
    orderBy: { posted_at: 'desc' }, include: { poster: true },
  });
  return rows.map(toJob);
}

export async function applyToJob(job_id: string, peer_id: string): Promise<Job | null> {
  await ensureMigrated();
  const job = await db.job.findUnique({ where: { job_id } });
  if (!job || job.status !== 'open') return null;
  const applicants: string[] = JSON.parse(job.applicants);
  if (!applicants.includes(peer_id)) applicants.push(peer_id);
  const row = await db.job.update({ where: { job_id }, data: { applicants: JSON.stringify(applicants) }, include: { poster: true } });
  return toJob(row);
}

export async function assignJob(job_id: string, peer_id: string): Promise<Job | null> {
  await ensureMigrated();
  const job = await db.job.findUnique({ where: { job_id } });
  if (!job || job.status !== 'open') return null;
  const row = await db.job.update({ where: { job_id }, data: { assigned_to: peer_id, status: 'assigned' }, include: { poster: true } });
  return toJob(row);
}

export async function completeJob(job_id: string, result: string): Promise<Job | null> {
  await ensureMigrated();
  const row = await db.job.update({
    where: { job_id },
    data: { status: result === '[CANCELLED]' ? 'cancelled' : 'completed', result, completed_at: new Date() },
    include: { poster: true },
  });
  return toJob(row);
}
