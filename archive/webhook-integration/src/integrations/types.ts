/** A normalized work item extracted from any project management source. */
export interface WorkItem {
  /** Unique identifier for the work item in the source system */
  sourceId: string;
  /** Title / summary of the work item */
  title: string;
  /** Full description / body text */
  description: string;
  /** URL to the work item in the source system */
  url: string;
  /** Source system name (jira | azure-boards | linear) */
  source: 'jira' | 'azure-boards' | 'linear';
  /** Optional additional context labels/tags to include in the GitHub issue */
  labels?: string[];
}
