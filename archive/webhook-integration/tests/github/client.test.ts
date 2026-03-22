import { GitHubClient, COPILOT_AGENT_LOGIN } from '../../src/github/client';
import type { WorkItem } from '../../src/integrations/types';

// Mock Octokit
const mockCreateIssue = jest.fn();
jest.mock('@octokit/rest', () => ({
  Octokit: jest.fn().mockImplementation(() => ({
    issues: {
      create: mockCreateIssue,
    },
  })),
}));

describe('GitHubClient', () => {
  let client: GitHubClient;

  beforeEach(() => {
    jest.clearAllMocks();
    client = new GitHubClient('token', 'owner', 'repo');
  });

  describe('delegateToCopilot', () => {
    const baseWorkItem: WorkItem = {
      sourceId: 'TEST-123',
      title: '[Jira TEST-123] Fix the login bug',
      description: 'Users cannot log in when 2FA is enabled.',
      url: 'https://example.atlassian.net/browse/TEST-123',
      source: 'jira',
    };

    it('creates a GitHub issue with the correct title', async () => {
      mockCreateIssue.mockResolvedValueOnce({
        data: { number: 42, html_url: 'https://github.com/owner/repo/issues/42', title: baseWorkItem.title },
      });

      const result = await client.delegateToCopilot(baseWorkItem);

      expect(mockCreateIssue).toHaveBeenCalledWith(
        expect.objectContaining({
          owner: 'owner',
          repo: 'repo',
          title: baseWorkItem.title,
          assignees: [COPILOT_AGENT_LOGIN],
        }),
      );
      expect(result.number).toBe(42);
      expect(result.html_url).toBe('https://github.com/owner/repo/issues/42');
    });

    it('includes source link and description in issue body', async () => {
      mockCreateIssue.mockResolvedValueOnce({
        data: { number: 1, html_url: 'https://github.com/owner/repo/issues/1', title: baseWorkItem.title },
      });

      await client.delegateToCopilot(baseWorkItem);

      const body: string = mockCreateIssue.mock.calls[0][0].body as string;
      expect(body).toContain(baseWorkItem.url);
      expect(body).toContain(baseWorkItem.sourceId);
      expect(body).toContain(baseWorkItem.description);
    });

    it('uses a placeholder when description is empty', async () => {
      const workItemNoDesc: WorkItem = { ...baseWorkItem, description: '' };
      mockCreateIssue.mockResolvedValueOnce({
        data: { number: 2, html_url: 'https://github.com/owner/repo/issues/2', title: workItemNoDesc.title },
      });

      await client.delegateToCopilot(workItemNoDesc);

      const body: string = mockCreateIssue.mock.calls[0][0].body as string;
      expect(body).toContain('_No description provided._');
    });

    it('assigns the issue to the Copilot agent login', async () => {
      mockCreateIssue.mockResolvedValueOnce({
        data: { number: 3, html_url: 'https://github.com/owner/repo/issues/3', title: baseWorkItem.title },
      });

      await client.delegateToCopilot(baseWorkItem);

      expect(mockCreateIssue).toHaveBeenCalledWith(
        expect.objectContaining({ assignees: ['copilot-swe-agent'] }),
      );
    });

    it('propagates errors from the GitHub API', async () => {
      mockCreateIssue.mockRejectedValueOnce(new Error('API error'));

      await expect(client.delegateToCopilot(baseWorkItem)).rejects.toThrow('API error');
    });
  });
});
