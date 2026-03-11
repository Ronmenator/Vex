/**
 * Prisma client singleton with SQL Server adapter.
 * Connection URL is constructed from AZURE_SQL_* env vars if DATABASE_URL is not set.
 */
import { PrismaClient } from '../generated/prisma/client';
import { PrismaMssql } from '@prisma/adapter-mssql';

function buildConnectionString(): string {
  if (process.env.DATABASE_URL) return process.env.DATABASE_URL;

  const server = process.env.AZURE_SQL_SERVER;
  const database = process.env.AZURE_SQL_DATABASE;
  const user = process.env.AZURE_SQL_USER;
  const password = process.env.AZURE_SQL_PASSWORD;

  if (!server || !database || !user || !password) {
    throw new Error('Database not configured. Set DATABASE_URL or AZURE_SQL_* env vars.');
  }

  return `sqlserver://${server}:1433;database=${database};user=${user};password=${password};encrypt=true`;
}

function createPrismaClient(): PrismaClient {
  const adapter = new PrismaMssql(buildConnectionString());
  return new PrismaClient({ adapter } as any);
}

const globalForPrisma = globalThis as unknown as { prisma?: PrismaClient };
export const db = globalForPrisma.prisma ?? createPrismaClient();
if (process.env.NODE_ENV !== 'production') globalForPrisma.prisma = db;
