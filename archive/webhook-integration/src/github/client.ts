import { Octokit } from '@octokit/rest';
import type { WorkItem } from '../integrations/types.js';
import { logger } from '../utils/logger.js';

/** The GitHub user login for the Copilot coding agent */
export const COPILOT_AGENT_LOGIN = 'copilot-swe-agent';

export interface CreatedIssue {
  number: number;
  html_url: string;
  title: string;
}

export class GitHubClient {
  private readonly octokit: Octokit;
  private readonly owner: string;
  private readonly repo: string;

  constructor(token: string, owner: string, repo: string) {
    this.octokit = new Octokit({ auth: token });
    this.owner = owner;
    this.repo = repo;
  }

  /**
   * Creates a GitHub issue from a work item and assigns it to the
   * Copilot coding agent to trigger autonomous work.
   */
  async delegateToCopilot(workItem: WorkItem): Promise<CreatedIssue> {
    const body = this.buildIssueBody(workItem);

    logger.info('Creating GitHub issue', {
      source: workItem.source,
      sourceId: workItem.sourceId,
      title: workItem.title,
    });

    const { data: issue } = await this.octokit.issues.create({
      owner: this.owner,
      repo: this.repo,
      title: workItem.title,
      body,
      assignees: [COPILOT_AGENT_LOGIN],
    });

    logger.info('GitHub issue created and assigned to Copilot', {
      issueNumber: issue.number,
      url: issue.html_url,
    });

    return {
      number: issue.number,
      html_url: issue.html_url,
      title: issue.title,
    };
  }

  private buildIssueBody(workItem: WorkItem): string {
    const lines: string[] = [];

    lines.push(`> **Source**: ${workItem.source} — [${workItem.sourceId}](${workItem.url})`);
    lines.push('');
    lines.push('---');
    lines.push('');

    if (workItem.description.trim()) {
      lines.push(workItem.description.trim());
    } else {
      lines.push('_No description provided._');
    }

    lines.push('');
    lines.push('---');
    lines.push('');
    lines.push(
      '_This issue was automatically created by [ArbiterAI](https://github.com/shifty81/ArbiterAI) and assigned to the Copilot coding agent._',
    );

    return lines.join('\n');
  }
}
