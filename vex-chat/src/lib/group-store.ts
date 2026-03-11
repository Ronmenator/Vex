import { randomUUID } from 'crypto';
import { db } from './db';
import { ensureMigrated } from './migrate';

export interface GroupMessage {
  message_id: string; group_id: string; sender_id: string; sender_name: string;
  content: string; created_at: string; reply_to: string | null;
  reactions: Record<string, string[]>;
}

export interface BotGroup {
  group_id: string; name: string; description: string; rationale: string;
  created_by: string; created_by_name: string; created_at: string;
  members: string[]; topic_tags: string[]; visibility: 'public' | 'invite';
  messages: GroupMessage[];
}

function toMessage(row: any): GroupMessage {
  return {
    message_id: row.message_id, group_id: row.group_id,
    sender_id: row.sender_id, sender_name: row.sender?.display_name ?? row.sender_id,
    content: row.content, created_at: row.created_at.toISOString(),
    reply_to: row.reply_to ?? null, reactions: JSON.parse(row.reactions),
  };
}

function toGroup(row: any): BotGroup {
  return {
    group_id: row.group_id, name: row.name, description: row.description, rationale: row.rationale,
    created_by: row.created_by, created_by_name: row.founder?.display_name ?? row.created_by,
    created_at: row.created_at.toISOString(),
    members: JSON.parse(row.members), topic_tags: JSON.parse(row.topic_tags),
    visibility: row.visibility as 'public' | 'invite',
    messages: (row.messages ?? []).map(toMessage),
  };
}

export async function createGroup(created_by: string, _name: string, name: string, description: string, rationale: string, topic_tags: string[], visibility: 'public' | 'invite' = 'public'): Promise<BotGroup> {
  await ensureMigrated();
  const row = await db.botGroup.create({
    data: { group_id: randomUUID(), name, description, rationale, created_by,
      members: JSON.stringify([created_by]), topic_tags: JSON.stringify(topic_tags), visibility },
    include: { founder: true, messages: { include: { sender: true } } },
  });
  return toGroup(row);
}

export async function getGroup(group_id: string): Promise<BotGroup | null> {
  await ensureMigrated();
  const row = await db.botGroup.findUnique({
    where: { group_id },
    include: { founder: true, messages: { include: { sender: true }, orderBy: { created_at: 'asc' }, take: 100 } },
  });
  return row ? toGroup(row) : null;
}

export async function listGroups(): Promise<BotGroup[]> {
  await ensureMigrated();
  const rows = await db.botGroup.findMany({
    orderBy: { created_at: 'desc' },
    include: { founder: true, messages: { include: { sender: true }, orderBy: { created_at: 'desc' }, take: 10 } },
  });
  return rows.map(toGroup);
}

export async function searchGroups(query: string): Promise<BotGroup[]> {
  await ensureMigrated();
  const rows = await db.botGroup.findMany({
    where: { OR: [{ name: { contains: query } }, { description: { contains: query } }] },
    include: { founder: true, messages: false },
  });
  return rows.map(r => toGroup({ ...r, messages: [] }));
}

export async function joinGroup(group_id: string, peer_id: string): Promise<BotGroup | null> {
  await ensureMigrated();
  const group = await db.botGroup.findUnique({ where: { group_id } });
  if (!group) return null;
  const members: string[] = JSON.parse(group.members);
  if (!members.includes(peer_id)) members.push(peer_id);
  const row = await db.botGroup.update({ where: { group_id }, data: { members: JSON.stringify(members) }, include: { founder: true, messages: false } });
  return toGroup({ ...row, messages: [] });
}

export async function leaveGroup(group_id: string, peer_id: string): Promise<BotGroup | null> {
  await ensureMigrated();
  const group = await db.botGroup.findUnique({ where: { group_id } });
  if (!group) return null;
  const members: string[] = JSON.parse(group.members).filter((id: string) => id !== peer_id);
  const row = await db.botGroup.update({ where: { group_id }, data: { members: JSON.stringify(members) }, include: { founder: true, messages: false } });
  return toGroup({ ...row, messages: [] });
}

export async function postMessage(group_id: string, sender_id: string, _sender_name: string, content: string, reply_to?: string): Promise<GroupMessage | null> {
  await ensureMigrated();
  const group = await db.botGroup.findUnique({ where: { group_id } });
  if (!group) return null;
  const row = await db.groupMessage.create({
    data: { message_id: randomUUID(), group_id, sender_id, content, reply_to: reply_to ?? null },
    include: { sender: true },
  });
  return toMessage(row);
}

export async function getMessages(group_id: string, limit = 50): Promise<GroupMessage[]> {
  await ensureMigrated();
  const rows = await db.groupMessage.findMany({
    where: { group_id }, orderBy: { created_at: 'asc' }, take: limit, include: { sender: true },
  });
  return rows.map(toMessage);
}

export async function reactToMessage(group_id: string, message_id: string, peer_id: string, emoji: string): Promise<boolean> {
  await ensureMigrated();
  const msg = await db.groupMessage.findFirst({ where: { message_id, group_id } });
  if (!msg) return false;
  const reactions: Record<string, string[]> = JSON.parse(msg.reactions);
  if (!reactions[emoji]) reactions[emoji] = [];
  const idx = reactions[emoji].indexOf(peer_id);
  if (idx >= 0) {
    reactions[emoji].splice(idx, 1);
    if (reactions[emoji].length === 0) delete reactions[emoji];
  } else {
    reactions[emoji].push(peer_id);
  }
  await db.groupMessage.update({ where: { message_id }, data: { reactions: JSON.stringify(reactions) } });
  return true;
}
