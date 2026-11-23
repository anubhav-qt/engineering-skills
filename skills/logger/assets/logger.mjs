// JSON logs for Node with no package: one line per event on stdout.
//
// Copy this file into the project (for example src/logger.mjs) when the
// project has no logger yet and the human did not want a package.
//
//   import { createLogger } from './logger.mjs';
//
//   const log = createLogger({ service: 'shop' });
//   log.info('order.paid', { orderId: order.id, cents: total });
//
//   const event = log.startEvent('http.request', { method, route });
//   try {
//     event.add({ userId });         // add fields as the work goes on
//     event.end();                   // logs once, with duration_ms
//   } catch (error) {
//     event.fail(error);             // logs once, at error level
//     throw error;
//   }
//
// Each line is one JSON object: time (UTC), level, event, the base fields
// and the call's fields. Field names that look secret are replaced with
// "[redacted]". JSON escapes line breaks, so user input cannot forge a
// new line.

const LEVELS = { debug: 10, info: 20, warn: 30, error: 40 };
const REDACTED = '[redacted]';
const SECRET_KEYS = new Set([
  'password', 'passwd', 'pwd', 'passphrase', 'secret', 'token',
  'access_token', 'refresh_token', 'id_token', 'api_key', 'apikey',
  'authorization', 'cookie', 'set_cookie', 'session', 'session_id',
  'private_key', 'card_number', 'cvv', 'ssn',
]);

function normalizeKey(key) {
  // accessToken -> access_token, Set-Cookie -> set_cookie
  const snake = String(key).replace(/([a-z0-9])([A-Z])/g, '$1_$2');
  return snake.toLowerCase().replace(/-/g, '_');
}

function isSecretKey(key) {
  return SECRET_KEYS.has(normalizeKey(key));
}

function describeError(error) {
  if (!(error instanceof Error)) {
    return { type: typeof error, message: String(error) };
  }
  return {
    type: error.name,
    code: error.code,
    message: error.message,
    stack: error.stack,
  };
}

function redact(value, seen) {
  if (value instanceof Error) {
    return describeError(value);
  }
  if (value === null || typeof value !== 'object') {
    return value;
  }
  if (seen.has(value)) {
    return '[circular]';
  }
  // seen holds only the objects on the path from the top, so the same
  // object used twice side by side is not taken for a loop.
  seen.add(value);
  let cleaned;
  if (Array.isArray(value)) {
    cleaned = value.map((inner) => redact(inner, seen));
  } else {
    cleaned = {};
    for (const [key, inner] of Object.entries(value)) {
      if (isSecretKey(key)) {
        cleaned[key] = REDACTED;
      } else {
        cleaned[key] = redact(inner, seen);
      }
    }
  }
  seen.delete(value);
  return cleaned;
}

function toLine(level, event, base, fields) {
  const line = {
    time: new Date().toISOString(),
    level,
    event,
    ...redact(base, new Set()),
    ...redact(fields, new Set()),
  };
  return JSON.stringify(line, (key, value) => {
    if (typeof value === 'bigint') {
      return value.toString();
    }
    return value;
  });
}

function fallbackLine(level, error) {
  return JSON.stringify({
    time: new Date().toISOString(),
    level,
    event: 'log.format_failed',
    'error.type': error && error.name,
  });
}

export function createLogger(base = {}, options = {}) {
  const minimum = LEVELS[options.level || process.env.LOG_LEVEL || 'info'] ?? LEVELS.info;
  const write = options.write || ((text) => process.stdout.write(text + '\n'));

  function log(level, event, fields = {}) {
    if (LEVELS[level] < minimum) {
      return;
    }
    let text;
    try {
      text = toLine(level, event, base, fields);
    } catch (error) {
      // A log line must never break the app.
      text = fallbackLine(level, error);
    }
    write(text);
  }

  function startEvent(event, fields = {}) {
    const started = process.hrtime.bigint();
    const collected = { ...fields };
    let done = false;

    function durationMs() {
      const nanoseconds = process.hrtime.bigint() - started;
      return Math.round(Number(nanoseconds) / 1e5) / 10;
    }

    return {
      add(more) {
        Object.assign(collected, more);
      },
      end() {
        if (done) {
          return;
        }
        done = true;
        log('info', event, { ...collected, outcome: 'ok', duration_ms: durationMs() });
      },
      fail(error) {
        if (done) {
          return;
        }
        done = true;
        log('error', event, {
          ...collected,
          outcome: 'error',
          duration_ms: durationMs(),
          error: describeError(error),
        });
      },
    };
  }

  return {
    debug: (event, fields) => log('debug', event, fields),
    info: (event, fields) => log('info', event, fields),
    warn: (event, fields) => log('warn', event, fields),
    error: (event, fields) => log('error', event, fields),
    child: (more) => createLogger({ ...base, ...more }, options),
    startEvent,
  };
}
