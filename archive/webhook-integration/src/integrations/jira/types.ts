/** Jira webhook event payload (simplified) */
export interface JiraWebhookPayload {
  webhookEvent: string;
  issue?: JiraIssue;
  changelog?: {
    items?: Array<{
      field: string;
      toString?: string;
      fromString?: string;
    }>;
  };
}

export interface JiraIssue {
  id: string;
  key: string;
  self: string;
  fields: JiraIssueFields;
}

export interface JiraIssueFields {
  summary: string;
  description?: string | JiraDocument | null;
  labels?: string[];
  status?: { name: string };
  issuetype?: { name: string };
  priority?: { name: string };
}

/** Jira Atlassian Document Format (ADF) node */
export interface JiraDocument {
  type: string;
  content?: JiraDocumentNode[];
  text?: string;
}

export interface JiraDocumentNode {
  type: string;
  text?: string;
  content?: JiraDocumentNode[];
}
