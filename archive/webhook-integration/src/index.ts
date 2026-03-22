import { loadConfig } from './config.js';
import { createServer } from './server.js';
import { logger } from './utils/logger.js';

const config = loadConfig();
const app = createServer(config);
const { port } = config.server;

app.listen(port, () => {
  logger.info(`ArbiterAI server listening`, { port });
  logger.info('Webhook endpoints ready', {
    jira: `POST /webhooks/jira`,
    azureBoards: `POST /webhooks/azure-boards`,
    linear: `POST /webhooks/linear`,
  });
});
