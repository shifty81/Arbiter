import dotenv from 'dotenv';

dotenv.config();

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

export interface Config {
  github: {
    token: string;
    owner: string;
    repo: string;
  };
  server: {
    port: number;
  };
  jira: {
    webhookSecret: string;
    triggerLabel: string;
  };
  azureBoards: {
    webhookSecret: string;
    triggerTag: string;
  };
  linear: {
    webhookSecret: string;
    triggerLabel: string;
  };
}

export function loadConfig(): Config {
  return {
    github: {
      token: requireEnv('GITHUB_TOKEN'),
      owner: requireEnv('GITHUB_OWNER'),
      repo: requireEnv('GITHUB_REPO'),
    },
    server: {
      port: parseInt(process.env['PORT'] ?? '3000', 10),
    },
    jira: {
      webhookSecret: process.env['JIRA_WEBHOOK_SECRET'] ?? '',
      triggerLabel: process.env['JIRA_TRIGGER_LABEL'] ?? 'copilot',
    },
    azureBoards: {
      webhookSecret: process.env['AZURE_BOARDS_WEBHOOK_SECRET'] ?? '',
      triggerTag: process.env['AZURE_BOARDS_TRIGGER_TAG'] ?? 'copilot',
    },
    linear: {
      webhookSecret: process.env['LINEAR_WEBHOOK_SECRET'] ?? '',
      triggerLabel: process.env['LINEAR_TRIGGER_LABEL'] ?? 'copilot',
    },
  };
}
