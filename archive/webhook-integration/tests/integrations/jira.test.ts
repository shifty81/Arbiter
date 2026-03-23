import type { Request, Response } from 'express';
import { JiraHandler } from '../../src/integrations/jira/handler';
import type { GitHubClient } from '../../src/github/client';
import type { JiraWebhookPayload } from '../../src/integrations/jira/types';

const mockDelegateToCopilot = jest.fn();
const mockGithubClient = {
  delegateToCopilot: mockDelegateToCopilot,
} as unknown as GitHubClient;

function makeReq(body: unknown, headers: Record<string, string> = {}): Request {
  return {
    body,
    headers,
    rawBody: JSON.stringify(body),
  } as unknown as Request;
}

function makeRes(): { res: Response; json: jest.Mock; status: jest.Mock } {
  const json = jest.fn();
  const status = jest.fn().mockReturnValue({ json });
  const res = { json, status } as unknown as Response;
  // Ensure status().json() chain works
  (res as unknown as { json: jest.Mock }).json = json;
  return { res, json, status };
}

describe('JiraHandler', () => {
  let handler: JiraHandler;

  beforeEach(() => {
    jest.clearAllMocks();
    handler = new JiraHandler(mockGithubClient, '', 'copilot');
  });

  const issueCreatedPayload: JiraWebhookPayload = {
    webhookEvent: 'jira:issue_created',
    issue: {
      id: '10001',
      key: 'PROJ-1',
      self: 'https://example.atlassian.net/rest/api/2/issue/10001',
      fields: {
        summary: 'Fix login bug',
        description: 'Users cannot login.',
        labels: ['copilot'],
      },
    },
  };

  it('ignores non-issue events', async () => {
    const req = makeReq({ webhookEvent: 'jira:issue_deleted' });
    const { res, json } = makeRes();

    await handler.handle(req, res);

    expect(json).toHaveBeenCalledWith({ message: 'Event ignored' });
    expect(mockDelegateToCopilot).not.toHaveBeenCalled();
  });

  it('ignores issues without trigger label', async () => {
    const payload: JiraWebhookPayload = {
      ...issueCreatedPayload,
      issue: {
        ...issueCreatedPayload.issue!,
        fields: {
          ...issueCreatedPayload.issue!.fields,
          labels: ['bug'],
        },
      },
    };
    const req = makeReq(payload);
    const { res, json } = makeRes();

    await handler.handle(req, res);

    expect(json).toHaveBeenCalledWith({ message: 'Label not present, event ignored' });
    expect(mockDelegateToCopilot).not.toHaveBeenCalled();
  });

  it('delegates to Copilot when trigger label is present', async () => {
    mockDelegateToCopilot.mockResolvedValueOnce({
      number: 10,
      html_url: 'https://github.com/owner/repo/issues/10',
      title: '[Jira PROJ-1] Fix login bug',
    });

    const req = makeReq(issueCreatedPayload);
    const { res, status } = makeRes();

    await handler.handle(req, res);

    expect(mockDelegateToCopilot).toHaveBeenCalledWith(
      expect.objectContaining({
        sourceId: 'PROJ-1',
        source: 'jira',
        title: '[Jira PROJ-1] Fix login bug',
      }),
    );
    expect(status).toHaveBeenCalledWith(201);
  });

  it('returns 400 when issue is missing from payload', async () => {
    const req = makeReq({ webhookEvent: 'jira:issue_created' });
    const { res, status } = makeRes();

    await handler.handle(req, res);

    expect(status).toHaveBeenCalledWith(400);
  });

  it('returns 500 when GitHub API call fails', async () => {
    mockDelegateToCopilot.mockRejectedValueOnce(new Error('API error'));

    const req = makeReq(issueCreatedPayload);
    const { res, status } = makeRes();

    await handler.handle(req, res);

    expect(status).toHaveBeenCalledWith(500);
  });

  it('handles ADF description format', async () => {
    const payload: JiraWebhookPayload = {
      webhookEvent: 'jira:issue_created',
      issue: {
        id: '10002',
        key: 'PROJ-2',
        self: 'https://example.atlassian.net/rest/api/2/issue/10002',
        fields: {
          summary: 'ADF issue',
          description: {
            type: 'doc',
            content: [
              {
                type: 'paragraph',
                content: [{ type: 'text', text: 'Hello from ADF' }],
              },
            ],
          },
          labels: ['copilot'],
        },
      },
    };

    mockDelegateToCopilot.mockResolvedValueOnce({
      number: 11,
      html_url: 'https://github.com/owner/repo/issues/11',
      title: '[Jira PROJ-2] ADF issue',
    });

    const req = makeReq(payload);
    const { res } = makeRes();

    await handler.handle(req, res);

    expect(mockDelegateToCopilot).toHaveBeenCalledWith(
      expect.objectContaining({
        description: 'Hello from ADF',
      }),
    );
  });

  it('label matching is case-insensitive', async () => {
    const payload: JiraWebhookPayload = {
      ...issueCreatedPayload,
      issue: {
        ...issueCreatedPayload.issue!,
        fields: {
          ...issueCreatedPayload.issue!.fields,
          labels: ['Copilot'],
        },
      },
    };
    mockDelegateToCopilot.mockResolvedValueOnce({
      number: 12,
      html_url: 'https://github.com/owner/repo/issues/12',
      title: '[Jira PROJ-1] Fix login bug',
    });

    const req = makeReq(payload);
    const { res, status } = makeRes();

    await handler.handle(req, res);

    expect(status).toHaveBeenCalledWith(201);
  });
});
