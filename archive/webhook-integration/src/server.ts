import express, { type Request, type Response, type NextFunction } from 'express';
import rateLimit from 'express-rate-limit';
import type { Config } from './config.js';
import { GitHubClient } from './github/client.js';
import { JiraHandler } from './integrations/jira/handler.js';
import { AzureBoardsHandler } from './integrations/azure-boards/handler.js';
import { LinearHandler } from './integrations/linear/handler.js';
import { logger } from './utils/logger.js';

/** Extend Express Request to carry the raw body buffer for signature verification */
declare module 'express' {
  interface Request {
    rawBody?: string;
  }
}

export function createServer(config: Config): express.Application {
  const app = express();

  // Capture raw body for signature verification before JSON parsing
  app.use(
    express.json({
      verify: (req: Request, _res: Response, buf: Buffer) => {
        req.rawBody = buf.toString('utf8');
      },
    }),
  );

  // Rate limiter for webhook endpoints: max 60 requests per minute per IP
  const webhookLimiter = rateLimit({
    windowMs: 60 * 1000,
    max: 60,
    standardHeaders: true,
    legacyHeaders: false,
    message: { error: 'Too many requests, please try again later.' },
  });

  const githubClient = new GitHubClient(
    config.github.token,
    config.github.owner,
    config.github.repo,
  );

  const jiraHandler = new JiraHandler(
    githubClient,
    config.jira.webhookSecret,
    config.jira.triggerLabel,
  );

  const azureBoardsHandler = new AzureBoardsHandler(
    githubClient,
    config.azureBoards.webhookSecret,
    config.azureBoards.triggerTag,
  );

  const linearHandler = new LinearHandler(
    githubClient,
    config.linear.webhookSecret,
    config.linear.triggerLabel,
  );

  // Health check
  app.get('/health', (_req: Request, res: Response) => {
    res.json({ status: 'ok', timestamp: new Date().toISOString() });
  });

  // Webhook endpoints
  app.post('/webhooks/jira', webhookLimiter, (req: Request, res: Response) => {
    jiraHandler.handle(req, res).catch((err: unknown) => {
      logger.error('Unhandled error in Jira handler', { error: String(err) });
      res.status(500).json({ error: 'Internal server error' });
    });
  });

  app.post('/webhooks/azure-boards', webhookLimiter, (req: Request, res: Response) => {
    azureBoardsHandler.handle(req, res).catch((err: unknown) => {
      logger.error('Unhandled error in Azure Boards handler', { error: String(err) });
      res.status(500).json({ error: 'Internal server error' });
    });
  });

  app.post('/webhooks/linear', webhookLimiter, (req: Request, res: Response) => {
    linearHandler.handle(req, res).catch((err: unknown) => {
      logger.error('Unhandled error in Linear handler', { error: String(err) });
      res.status(500).json({ error: 'Internal server error' });
    });
  });

  // 404 handler
  app.use((_req: Request, res: Response) => {
    res.status(404).json({ error: 'Not found' });
  });

  // Global error handler
  app.use((err: Error, _req: Request, res: Response, _next: NextFunction) => {
    logger.error('Unhandled server error', { error: err.message });
    res.status(500).json({ error: 'Internal server error' });
  });

  return app;
}
