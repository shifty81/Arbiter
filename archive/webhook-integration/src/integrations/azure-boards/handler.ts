import type { Request, Response } from 'express';
import type {
  AzureBoardsWebhookPayload,
  AzureBoardsFields,
} from './types.js';
import type { WorkItem } from '../types.js';
import { verifyHmacSignature } from '../../utils/webhook-security.js';
import { logger } from '../../utils/logger.js';
import type { GitHubClient } from '../../github/client.js';

/** Supported Azure Boards work item event types */
const SUPPORTED_EVENTS = new Set([
  'workitem.created',
  'workitem.updated',
]);

export class AzureBoardsHandler {
  constructor(
    private readonly githubClient: GitHubClient,
    private readonly webhookSecret: string,
    private readonly triggerTag: string,
  ) {}

  async handle(req: Request, res: Response): Promise<void> {
    const rawBody: string = (req as Request & { rawBody?: string }).rawBody ?? JSON.stringify(req.body);

    // Azure DevOps service hooks use Basic auth or a shared secret in a custom header
    const signature = req.headers['x-hub-signature-256'] as string | undefined;
    if (this.webhookSecret && signature) {
      if (!verifyHmacSignature(rawBody, this.webhookSecret, signature)) {
        logger.warn('Azure Boards webhook signature verification failed');
        res.status(401).json({ error: 'Invalid signature' });
        return;
      }
    }

    const payload = req.body as AzureBoardsWebhookPayload;
    const eventType = payload.eventType;

    logger.debug('Azure Boards webhook received', { eventType });

    if (!SUPPORTED_EVENTS.has(eventType)) {
      res.status(200).json({ message: 'Event ignored' });
      return;
    }

    // Fields may be under resource directly (created) or under resource.revision (updated)
    const resource = payload.resource;
    if (!resource) {
      res.status(400).json({ error: 'Missing resource in payload' });
      return;
    }

    const fields: AzureBoardsFields = resource.fields ?? resource.revision?.fields ?? {};
    const workItemId = resource.workItemId ?? resource.id ?? resource.revision?.id;

    if (!workItemId || !fields['System.Title']) {
      res.status(400).json({ error: 'Missing required work item fields' });
      return;
    }

    const tags = (fields['System.Tags'] ?? '')
      .split(';')
      .map((t) => t.trim())
      .filter(Boolean);

    if (!tags.some((t) => t.toLowerCase() === this.triggerTag.toLowerCase())) {
      logger.debug('Azure Boards work item does not have trigger tag, ignoring', {
        workItemId,
        tags,
        triggerTag: this.triggerTag,
      });
      res.status(200).json({ message: 'Tag not present, event ignored' });
      return;
    }

    const htmlUrl =
      resource._links?.html?.href ??
      resource.revision?._links?.html?.href ??
      resource.url ??
      '';

    const workItem = this.toWorkItem(workItemId, fields, htmlUrl);

    try {
      const created = await this.githubClient.delegateToCopilot(workItem);
      res.status(201).json({
        message: 'Issue created and assigned to Copilot',
        github_issue: created,
      });
    } catch (err) {
      logger.error('Failed to create GitHub issue from Azure Boards webhook', {
        error: String(err),
      });
      res.status(500).json({ error: 'Failed to create GitHub issue' });
    }
  }

  private toWorkItem(
    workItemId: number,
    fields: AzureBoardsFields,
    htmlUrl: string,
  ): WorkItem {
    const title = fields['System.Title'] ?? `Work Item ${workItemId}`;
    const description = this.stripHtml(fields['System.Description'] ?? '');
    const project = fields['System.TeamProject'] ?? '';

    return {
      sourceId: String(workItemId),
      title: `[Azure #${workItemId}] ${title}`,
      description,
      url: htmlUrl,
      source: 'azure-boards',
      labels: project ? [project] : [],
    };
  }

  /** Remove HTML tags and decode basic HTML entities from Azure Boards rich-text description fields. */
  private stripHtml(html: string): string {
    return html
      .replace(/<[^>]*>/g, ' ')
      .replace(/&(amp|lt|gt|quot|#39|#x27);/gi, (_, entity: string) => {
        const entities: Record<string, string> = {
          amp: '&',
          lt: '<',
          gt: '>',
          quot: '"',
          '#39': "'",
          '#x27': "'",
        };
        return entities[entity.toLowerCase()] ?? `&${entity};`;
      })
      .replace(/\s{2,}/g, ' ')
      .trim();
  }
}
