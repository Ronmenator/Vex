/**
 * Auto-migration: creates all tables if they don't exist.
 * Called once at app startup from the first API request.
 * Safe to call multiple times — idempotent.
 */
import { db } from './db';
import fs from 'fs';
import path from 'path';

let migrationDone = false;
let migrationPromise: Promise<void> | null = null;

export async function ensureMigrated(): Promise<void> {
  if (migrationDone) return;
  if (migrationPromise) return migrationPromise;

  migrationPromise = (async () => {
    try {
      // Check if Peer table exists (proxy for whether DB is initialized)
      const tableExists = await db.$queryRaw<{ count: number }[]>`
        SELECT COUNT(*) as count FROM sys.tables WHERE name = 'Peer'
      `;
      const exists = (tableExists as any)[0]?.count > 0;

      if (!exists) {
        console.log('[migrate] Tables not found — running initial migration...');
        // Read migration SQL
        const sqlPath = path.join(process.cwd(), 'prisma', 'migrations', '0001_init.sql');
        const sql = fs.readFileSync(sqlPath, 'utf-8');

        // Split on statement separator and execute each statement
        // SQL Server needs the full batch including TRY/CATCH
        await db.$executeRawUnsafe(sql);
        console.log('[migrate] Migration complete.');
      } else {
        console.log('[migrate] Tables already exist — skipping migration.');
      }
      migrationDone = true;
    } catch (err) {
      console.error('[migrate] Migration failed:', err);
      migrationPromise = null; // allow retry
      throw err;
    }
  })();

  return migrationPromise;
}
