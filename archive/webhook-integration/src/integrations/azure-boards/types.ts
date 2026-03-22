/** Azure Boards service hook event payload (simplified) */
export interface AzureBoardsWebhookPayload {
  eventType: string;
  resource?: AzureBoardsResource;
}

export interface AzureBoardsResource {
  id?: number;
  workItemId?: number;
  fields?: AzureBoardsFields;
  url?: string;
  _links?: {
    html?: { href: string };
  };
  revision?: {
    id: number;
    fields?: AzureBoardsFields;
    url?: string;
    _links?: {
      html?: { href: string };
    };
  };
}

export interface AzureBoardsFields {
  'System.Id'?: number;
  'System.Title'?: string;
  'System.Description'?: string;
  'System.Tags'?: string;
  'System.WorkItemType'?: string;
  'System.State'?: string;
  'System.TeamProject'?: string;
}
