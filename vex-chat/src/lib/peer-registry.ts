/**
 * In-memory peer registry for the VexNet Hub.
 * Per-instance state — bots re-register on each startup, which is fine.
 */

export interface RegisteredPeer {
  peer_id: string;
  public_key: string;  // hex
  display_name: string;
  capabilities: string[];
  last_seen: string;   // ISO 8601
  online: boolean;
  status?: string;
}

// Module-level registry — survives across requests within a server instance
const peers = new Map<string, RegisteredPeer>();
const pendingNonces = new Map<string, string>(); // peer_id -> nonce
const tokens = new Map<string, string>(); // token -> peer_id

export function registerPeer(
  public_key: string,
  display_name: string,
  capabilities: string[],
): string {
  const { createHash } = require('crypto') as typeof import('crypto');
  const peer_id = createHash('sha256').update(Buffer.from(public_key, 'hex')).digest('hex');
  peers.set(peer_id, {
    peer_id,
    public_key,
    display_name,
    capabilities,
    last_seen: new Date().toISOString(),
    online: true,
  });
  return peer_id;
}

export function issueNonce(peer_id: string): string {
  const { randomBytes } = require('crypto') as typeof import('crypto');
  const nonce = randomBytes(32).toString('hex');
  pendingNonces.set(peer_id, nonce);
  return nonce;
}

export function verifyAndIssueToken(peer_id: string, nonce: string, signature: string): string | null {
  const expected = pendingNonces.get(peer_id);
  if (!expected || expected !== nonce) return null;

  const peer = peers.get(peer_id);
  if (!peer) return null;

  // TODO: verify Ed25519 signature(nonce, public_key) once @noble/ed25519 is added
  // For now: trust nonce match as proof of identity

  pendingNonces.delete(peer_id);

  const { randomBytes } = require('crypto') as typeof import('crypto');
  const token = randomBytes(32).toString('hex');
  tokens.set(token, peer_id);
  return token;
}

export function getPeerFromToken(token: string): RegisteredPeer | null {
  const peer_id = tokens.get(token);
  return peer_id ? (peers.get(peer_id) ?? null) : null;
}

export function heartbeat(peer_id: string, status?: string): void {
  const peer = peers.get(peer_id);
  if (peer) {
    peer.last_seen = new Date().toISOString();
    peer.online = true;
    if (status !== undefined) {
      peer.status = status;
    }
  }
}

export function markOffline(peer_id: string): void {
  const peer = peers.get(peer_id);
  if (peer) peer.online = false;
}

export function listPeers(onlineOnly = true): RegisteredPeer[] {
  const all = Array.from(peers.values());
  // Mark stale peers (no heartbeat in 90 seconds) as offline
  const now = Date.now();
  for (const p of all) {
    if (p.online && now - new Date(p.last_seen).getTime() > 90 * 1000) {
      p.online = false;
    }
  }
  return onlineOnly ? all.filter(p => p.online) : all;
}
