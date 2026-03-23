import type { Request, Response } from 'express';
import { LinearHandler } from '../../src/integrations/linear/handler';
import type { GitHubClient } from '../../src/github/client';
import type { LinearWebhookPayload } from '../../src/integrations/linear/types';

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
  (res as unknown as { json: jest.Mock }).json = json;
  return { res, json, status };
}

describe('LinearHandler', () => {
  let handler: LinearHandler;

  beforeEach(() => {
    jest.clearAllMocks();
    handler = new LinearHandler(mockGithubClient, '', 'copilot');
  });

  const issueCreatedPayload: LinearWebhookPayload = {
    action: 'create',
    type: 'Issue',
    data: {
      id: 'abc-123',
      identifier: 'ENG-42',
      title: 'Add dark mode support',
      description: 'Users have requested a dark mode option.',
      url: 'https://linear.app/myteam/issue/ENG-42',
      labels: [{ id: 'lbl-1', name: 'copilot' }],
      team: { name: 'Engineering' },
    },
  };

  it('ignores non-Issue types', async () => {
    const req = makeReq({ action: 'create', type: 'Comment' });
    const { res, json } = makeRes();

    await handler.handle(req, res);

    expect(json).toHaveBeenCalledWith({ message: 'Event ignored' });
    expect(mockDelegateToCopilot).not.toHaveBeenCalled();
  });

  it('ignores unsupported actions', async () => {
    const req = makeReq({ action: 'remove', type: 'Issue', data: issueCreatedPayload.data });
    const { res, json } = makeRes();

    await handler.handle(req, res);

    expect(json).toHaveBeenCalledWith({ message: 'Action ignored' });
    expect(mockDelegateToCopilot).not.toHaveBeenCalled();
  });

  it('ignores issues without trigger label', async () => {
    const payload: LinearWebhookPayload = {
      ...issueCreatedPayload,
      data: {
        ...issueCreatedPayload.data!,
        labels: [{ id: 'lbl-2', name: 'bug' }],
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
      number: 20,
      html_url: 'https://github.com/owner/repo/issues/20',
      title: '[Linear ENG-42] Add dark mode support',
    });

    const req = makeReq(issueCreatedPayload);
    const { res, status } = makeRes();

    await handler.handle(req, res);

    expect(mockDelegateToCopilot).toHaveBeenCalledWith(
      expect.objectContaining({
        sourceId: 'ENG-42',
        source: 'linear',
        title: '[Linear ENG-42] Add dark mode support',
        description: 'Users have requested a dark mode option.',
        url: 'https://linear.app/myteam/issue/ENG-42',
      }),
    );
    expect(status).toHaveBeenCalledWith(201);
  });

  it('returns 400 when data is missing', async () => {
    const req = makeReq({ action: 'create', type: 'Issue' });
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

  it('label matching is case-insensitive', async () => {
    const payload: LinearWebhookPayload = {
      ...issueCreatedPayload,
      data: {
        ...issueCreatedPayload.data!,
        labels: [{ id: 'lbl-3', name: 'Copilot' }],
      },
    };
    mockDelegateToCopilot.mockResolvedValueOnce({
      number: 21,
      html_url: 'https://github.com/owner/repo/issues/21',
      title: '[Linear ENG-42] Add dark mode support',
    });

    const req = makeReq(payload);
    const { res, status } = makeRes();

    await handler.handle(req, res);

    expect(status).toHaveBeenCalledWith(201);
  });
});
