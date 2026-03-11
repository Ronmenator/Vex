/**
 * Peer registry backed by Azure SQL via Prisma.
 * Nonces remain in-memory (single-use, ephemeral).
 * Peers and tokens are persisted.
 */
import { db } from './db';
import { ensureMigrated } from './migrate';

export interface RegisteredPeer {
  peer_id: string;
  public_key: string;
  display_name: string;
  capabilities: string[];
  last_seen: string;
  online: boolean;
  status?: string;
}

// Nonces are ephemeral — in-memory is fine
const pendingNonces = new Map<string, string>();

// ── Helpers ────────────────────────────────────────────────────────────────

function toRegisteredPeer(row: {
  peer_id: string;
  public_key: string;
  display_name: string;
  capabilities: string;
  last_seen: Date;
  online: boolean;
  status: string | null;
}): RegisteredPeer {
  return {
    peer_id: row.peer_id,
    public_key: row.public_key,
    display_name: row.display_name,
    capabilities: JSON.parse(row.capabilities),
    last_seen: row.last_seen.toISOString(),
    online: row.online,
    status: row.status ?? undefined,
  };
}

// ── Registration ───────────────────────────────────────────────────────────

export async function registerPeer(
  public_key: string,
  display_name: string,
  capabilities: string[],
): Promise<string> {
  await ensureMigrated();
  const { createHash } = require('crypto') as typeof import('crypto');
  const peer_id = createHash('sha256').update(Buffer.from(public_key, 'hex')).digest('hex');

  await db.peer.upsert({
    where: { peer_id },
    create: {
      peer_id,
      public_key,
      display_name,
      capabilities: JSON.stringify(capabilities),
      online: true,
    },
    update: {
      public_key,
      display_name,
      capabilities: JSON.stringify(capabilities),
      last_seen: new Date(),
      online: true,
    },
  });
  return peer_id;
}

export function issueNonce(peer_id: string): string {
  const { randomBytes } = require('crypto') as typeof import('crypto');
  const nonce = randomBytes(32).toString('hex');
  pendingNonces.set(peer_id, nonce);
  return nonce;
}

export async function verifyAndIssueToken(
  peer_id: string,
  nonce: string,
  _signature: string,
): Promise<string | null> {
  const expected = pendingNonces.get(peer_id);
  if (!expected || expected !== nonce) return null;

  const peer = await db.peer.findUnique({ where: { peer_id } });
  if (!peer) return null;

  // TODO: verify Ed25519 signature once @noble/ed25519 is added
  pendingNonces.delete(peer_id);

  const { randomBytes } = require('crypto') as typeof import('crypto');
  const token = randomBytes(32).toString('hex');

  await db.authToken.create({ data: { token, peer_id } });
  return token;
}

export async function getPeerFromToken(token: string): Promise<RegisteredPeer | null> {
  await ensureMigrated();
  const row = await db.authToken.findUnique({
    where: { token },
    include: { peer: true },
  });
  return row ? toRegisteredPeer(row.peer) : null;
}

export async function heartbeat(peer_id: string, status?: string): Promise<void> {
  await db.peer.update({
    where: { peer_id },
    data: {
      last_seen: new Date(),
      online: true,
      ...(status !== undefined ? { status } : {}),
    },
  });
}

export async function markOffline(peer_id: string): Promise<void> {
  await db.peer.update({
    where: { peer_id },
    data: { online: false },
  });
}

export async function listPeers(onlineOnly = true): Promise<RegisteredPeer[]> {
  await ensureMigrated();
  // Mark stale peers offline (no heartbeat in 90s)
  const staleThreshold = new Date(Date.now() - 90_000);
  await db.peer.updateMany({
    where: { online: true, last_seen: { lt: staleThreshold } },
    data: { online: false },
  });

  const rows = await db.peer.findMany({
    where: onlineOnly ? { online: true } : undefined,
    orderBy: { last_seen: 'desc' },
  });
  return rows.map(toRegisteredPeer);
}
