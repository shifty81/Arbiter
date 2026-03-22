/** Linear webhook event payload (simplified) */
export interface LinearWebhookPayload {
  action: string;
  type: string;
  data?: LinearIssueData;
}

export interface LinearIssueData {
  id: string;
  title: string;
  description?: string | null;
  url: string;
  identifier: string;
  labels?: LinearLabel[];
  team?: {
    name: string;
  };
}

export interface LinearLabel {
  id: string;
  name: string;
  color?: string;
}
