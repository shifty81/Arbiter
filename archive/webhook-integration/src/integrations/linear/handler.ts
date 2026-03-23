import type { Request, Response } from 'express';
import type { LinearWebhookPayload } from './types.js';
import type { WorkItem } from '../types.js';
import { verifyHmacSignature } from '../../utils/webhook-security.js';
import { logger } from '../../utils/logger.js';
import type { GitHubClient } from '../../github/client.js';

/** Supported Linear issue event actions */
const SUPPORTED_ACTIONS = new Set(['create', 'update']);

export class LinearHandler {
  constructor(
    private readonly githubClient: GitHubClient,
    private readonly webhookSecret: string,
    private readonly triggerLabel: string,
  ) {}

  async handle(req: Request, res: Response): Promise<void> {
    const rawBody: string = (req as Request & { rawBody?: string }).rawBody ?? JSON.stringify(req.body);

    // Linear sends the signature in the `linear-signature` header
    const signature = req.headers['linear-signature'] as string | undefined;
    if (this.webhookSecret && signature) {
      if (!verifyHmacSignature(rawBody, this.webhookSecret, signature, '')) {
        logger.warn('Linear webhook signature verification failed');
        res.status(401).json({ error: 'Invalid signature' });
        return;
      }
    }

    const payload = req.body as LinearWebhookPayload;
    const { action, type } = payload;

    logger.debug('Linear webhook received', { action, type });

    // Only handle Issue events
    if (type !== 'Issue') {
      res.status(200).json({ message: 'Event ignored' });
      return;
    }

    if (!SUPPORTED_ACTIONS.has(action)) {
      res.status(200).json({ message: 'Action ignored' });
      return;
    }

    const data = payload.data;
    if (!data) {
      res.status(400).json({ error: 'Missing data in payload' });
      return;
    }

    const labelNames = (data.labels ?? []).map((l) => l.name);
    if (!labelNames.some((n) => n.toLowerCase() === this.triggerLabel.toLowerCase())) {
      logger.debug('Linear issue does not have trigger label, ignoring', {
        identifier: data.identifier,
        labels: labelNames,
        triggerLabel: this.triggerLabel,
      });
      res.status(200).json({ message: 'Label not present, event ignored' });
      return;
    }

    const workItem = this.toWorkItem(payload);

    try {
      const created = await this.githubClient.delegateToCopilot(workItem);
      res.status(201).json({
        message: 'Issue created and assigned to Copilot',
        github_issue: created,
      });
    } catch (err) {
      logger.error('Failed to create GitHub issue from Linear webhook', {
        error: String(err),
      });
      res.status(500).json({ error: 'Failed to create GitHub issue' });
    }
  }

  private toWorkItem(payload: LinearWebhookPayload): WorkItem {
    const data = payload.data!;
    return {
      sourceId: data.identifier,
      title: `[Linear ${data.identifier}] ${data.title}`,
      description: data.description ?? '',
      url: data.url,
      source: 'linear',
      labels: data.labels?.map((l) => l.name) ?? [],
    };
  }
}
