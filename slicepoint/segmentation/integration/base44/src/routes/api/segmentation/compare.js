import { createFileRoute } from '@tanstack/react-router';
import { env } from 'cloudflare:workers';
import { compareProxy } from '@/server/slicepoint/compare-proxy.server';

// Matches the server route and request middleware observed in this Base44 app.
export const Route = createFileRoute('/api/segmentation/compare')({
  server: { handlers: {
    POST: ({ request, context }) => compareProxy({ request, context, secrets: env }),
  } },
});
