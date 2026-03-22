import type { Request, Response } from 'express';
import type { JiraWebhookPayload, JiraDocumentNode } from './types.js';
import type { WorkItem } from '../types.js';
import { verifyHmacSignature } from '../../utils/webhook-security.js';
import { logger } from '../../utils/logger.js';
import type { GitHubClient } from '../../github/client.js';

export class JiraHandler {
  constructor(
    private readonly githubClient: GitHubClient,
    private readonly webhookSecret: string,
    private readonly triggerLabel: string,
  ) {}

  async handle(req: Request, res: Response): Promise<void> {
    const rawBody: string = (req as Request & { rawBody?: string }).rawBody ?? JSON.stringify(req.body);

    // Verify signature if secret is configured
    const signature = req.headers['x-hub-signature-256'] as string | undefined;
    if (this.webhookSecret && signature) {
      if (!verifyHmacSignature(rawBody, this.webhookSecret, signature)) {
        logger.warn('Jira webhook signature verification failed');
        res.status(401).json({ error: 'Invalid signature' });
        return;
      }
    }

    const payload = req.body as JiraWebhookPayload;
    const event = payload.webhookEvent;

    logger.debug('Jira webhook received', { event });

    // Only handle issue creation and update events
    if (event !== 'jira:issue_created' && event !== 'jira:issue_updated') {
      res.status(200).json({ message: 'Event ignored' });
      return;
    }

    const issue = payload.issue;
    if (!issue) {
      res.status(400).json({ error: 'Missing issue in payload' });
      return;
    }

    const labels = issue.fields.labels ?? [];
    if (!labels.some((l) => l.toLowerCase() === this.triggerLabel.toLowerCase())) {
      logger.debug('Jira issue does not have trigger label, ignoring', {
        key: issue.key,
        labels,
        triggerLabel: this.triggerLabel,
      });
      res.status(200).json({ message: 'Label not present, event ignored' });
      return;
    }

    const workItem = this.toWorkItem(issue);

    try {
      const created = await this.githubClient.delegateToCopilot(workItem);
      res.status(201).json({
        message: 'Issue created and assigned to Copilot',
        github_issue: created,
      });
    } catch (err) {
      logger.error('Failed to create GitHub issue from Jira webhook', {
        error: String(err),
      });
      res.status(500).json({ error: 'Failed to create GitHub issue' });
    }
  }

  private toWorkItem(issue: JiraWebhookPayload['issue'] & object): WorkItem {
    const fields = issue.fields;
    const description = this.extractDescription(fields.description);
    const jiraBaseUrl = new URL(issue.self).origin;

    return {
      sourceId: issue.key,
      title: `[Jira ${issue.key}] ${fields.summary}`,
      description,
      url: `${jiraBaseUrl}/browse/${issue.key}`,
      source: 'jira',
      labels: fields.labels,
    };
  }

  private extractDescription(
    description: JiraWebhookPayload['issue'] extends undefined
      ? never
      : NonNullable<JiraWebhookPayload['issue']>['fields']['description'],
  ): string {
    if (!description) return '';

    // Plain string (older Jira REST API v2)
    if (typeof description === 'string') {
      return description;
    }

    // Atlassian Document Format (ADF) - Jira REST API v3
    return this.adfToText(description as { type: string; content?: JiraDocumentNode[] });
  }

  private adfToText(node: { type: string; text?: string; content?: JiraDocumentNode[] }): string {
    if (node.text) return node.text;
    if (node.content) {
      return node.content.map((child) => this.adfToText(child)).join('');
    }
    return '';
  }
}
