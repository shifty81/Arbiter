import crypto from 'crypto';

/**
 * Verifies a SHA-256 HMAC signature for webhook payloads.
 * Performs a constant-time comparison to prevent timing attacks.
 */
export function verifyHmacSignature(
  payload: string,
  secret: string,
  signature: string,
  prefix = 'sha256=',
): boolean {
  if (!secret) {
    return true; // If no secret configured, skip verification
  }

  const expected = prefix + crypto.createHmac('sha256', secret).update(payload).digest('hex');

  try {
    return crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expected));
  } catch {
    return false;
  }
}

/**
 * Verifies a SHA-1 HMAC signature (used by some legacy webhooks).
 * Performs a constant-time comparison to prevent timing attacks.
 */
export function verifyHmacSha1Signature(
  payload: string,
  secret: string,
  signature: string,
  prefix = 'sha1=',
): boolean {
  if (!secret) {
    return true;
  }

  const expected = prefix + crypto.createHmac('sha1', secret).update(payload).digest('hex');

  try {
    return crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expected));
  } catch {
    return false;
  }
}
