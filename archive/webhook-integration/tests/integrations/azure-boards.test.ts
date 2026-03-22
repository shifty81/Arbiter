import type { Request, Response } from 'express';
import { AzureBoardsHandler } from '../../src/integrations/azure-boards/handler';
import type { GitHubClient } from '../../src/github/client';
import type { AzureBoardsWebhookPayload } from '../../src/integrations/azure-boards/types';

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

describe('AzureBoardsHandler', () => {
  let handler: AzureBoardsHandler;

  beforeEach(() => {
    jest.clearAllMocks();
    handler = new AzureBoardsHandler(mockGithubClient, '', 'copilot');
  });

  const workItemCreatedPayload: AzureBoardsWebhookPayload = {
    eventType: 'workitem.created',
    resource: {
      id: 42,
      fields: {
        'System.Id': 42,
        'System.Title': 'Implement OAuth2',
        'System.Description': '<p>Add OAuth2 support to the API</p>',
        'System.Tags': 'copilot; backend',
        'System.TeamProject': 'MyProject',
      },
      _links: { html: { href: 'https://dev.azure.com/org/proj/_workitems/edit/42' } },
    },
  };

  it('ignores unsupported event types', async () => {
    const req = makeReq({ eventType: 'workitem.commented' });
    const { res, json } = makeRes();

    await handler.handle(req, res);

    expect(json).toHaveBeenCalledWith({ message: 'Event ignored' });
    expect(mockDelegateToCopilot).not.toHaveBeenCalled();
  });

  it('ignores work items without trigger tag', async () => {
    const payload: AzureBoardsWebhookPayload = {
      ...workItemCreatedPayload,
      resource: {
        ...workItemCreatedPayload.resource!,
        fields: {
          ...workItemCreatedPayload.resource!.fields!,
          'System.Tags': 'backend; frontend',
        },
      },
    };
    const req = makeReq(payload);
    const { res, json } = makeRes();

    await handler.handle(req, res);

    expect(json).toHaveBeenCalledWith({ message: 'Tag not present, event ignored' });
    expect(mockDelegateToCopilot).not.toHaveBeenCalled();
  });

  it('delegates to Copilot when trigger tag is present', async () => {
    mockDelegateToCopilot.mockResolvedValueOnce({
      number: 5,
      html_url: 'https://github.com/owner/repo/issues/5',
      title: '[Azure #42] Implement OAuth2',
    });

    const req = makeReq(workItemCreatedPayload);
    const { res, status } = makeRes();

    await handler.handle(req, res);

    expect(mockDelegateToCopilot).toHaveBeenCalledWith(
      expect.objectContaining({
        sourceId: '42',
        source: 'azure-boards',
        title: '[Azure #42] Implement OAuth2',
      }),
    );
    expect(status).toHaveBeenCalledWith(201);
  });

  it('strips HTML tags from description', async () => {
    mockDelegateToCopilot.mockResolvedValueOnce({
      number: 6,
      html_url: 'https://github.com/owner/repo/issues/6',
      title: '[Azure #42] Implement OAuth2',
    });

    const req = makeReq(workItemCreatedPayload);
    const { res } = makeRes();

    await handler.handle(req, res);

    expect(mockDelegateToCopilot).toHaveBeenCalledWith(
      expect.objectContaining({
        description: 'Add OAuth2 support to the API',
      }),
    );
  });

  it('returns 400 when resource is missing', async () => {
    const req = makeReq({ eventType: 'workitem.created' });
    const { res, status } = makeRes();

    await handler.handle(req, res);

    expect(status).toHaveBeenCalledWith(400);
  });

  it('returns 500 when GitHub API call fails', async () => {
    mockDelegateToCopilot.mockRejectedValueOnce(new Error('API error'));

    const req = makeReq(workItemCreatedPayload);
    const { res, status } = makeRes();

    await handler.handle(req, res);

    expect(status).toHaveBeenCalledWith(500);
  });

  it('tag matching is case-insensitive', async () => {
    const payload: AzureBoardsWebhookPayload = {
      ...workItemCreatedPayload,
      resource: {
        ...workItemCreatedPayload.resource!,
        fields: {
          ...workItemCreatedPayload.resource!.fields!,
          'System.Tags': 'Copilot; backend',
        },
      },
    };
    mockDelegateToCopilot.mockResolvedValueOnce({
      number: 7,
      html_url: 'https://github.com/owner/repo/issues/7',
      title: '[Azure #42] Implement OAuth2',
    });

    const req = makeReq(payload);
    const { res, status } = makeRes();

    await handler.handle(req, res);

    expect(status).toHaveBeenCalledWith(201);
  });
});
