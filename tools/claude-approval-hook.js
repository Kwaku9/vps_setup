#!/usr/bin/env node
/**
 * Claude Code PreToolUse hook — Telegram approval bridge.
 *
 * Intercepts tool calls that need permission (Bash, WebFetch, etc.),
 * sends an approval request to Telegram with Approve/Deny buttons,
 * polls for the decision, and returns it to Claude Code.
 *
 * Config via env vars:
 *   TELEGRAM_GATEWAY_URL   (default: http://127.0.0.1:7555)
 *   TELEGRAM_GATEWAY_TOKEN (required)
 *   TELEGRAM_CHAT_ID       (required)
 *
 * Or via config file: tools/telegram-approval.json
 */

"use strict";

const http = require("http");
const https = require("https");
const path = require("path");
const fs = require("fs");

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const CONFIG_PATH = path.join(__dirname, "telegram-approval.json");

let config = {};
try {
  config = JSON.parse(fs.readFileSync(CONFIG_PATH, "utf-8"));
} catch (_) {
  // No config file — rely on env vars
}

const GATEWAY_URL =
  process.env.TELEGRAM_GATEWAY_URL || config.gateway_url || "http://127.0.0.1:7555";
const GATEWAY_TOKEN =
  process.env.TELEGRAM_GATEWAY_TOKEN || config.gateway_token || "";
const CHAT_ID = parseInt(
  process.env.TELEGRAM_CHAT_ID || config.chat_id || "0",
  10
);
const POLL_INTERVAL_MS = parseInt(
  process.env.TELEGRAM_POLL_INTERVAL || config.poll_interval_ms || "3000",
  10
);
const POLL_TIMEOUT_MS = parseInt(
  process.env.TELEGRAM_POLL_TIMEOUT || config.poll_timeout_ms || "120000",
  10
);

// ---------------------------------------------------------------------------
// Safe-command detection — auto-approve these without Telegram round-trip
// ---------------------------------------------------------------------------

const SAFE_BASH_PREFIXES = [
  "echo ",
  "printf ",
  "ls",
  "pwd",
  "cat ",
  "head ",
  "tail ",
  "wc ",
  "which ",
  "whoami",
  "date",
  "env",
  "printenv",
  "id",
  "uname",
  "hostname",
  "uptime",
  "df ",
  "du ",
  "free",
  "file ",
  "stat ",
  "readlink ",
  "basename ",
  "dirname ",
  "realpath ",
  "test ",
  "[ ",
  "true",
  "false",
  // Git read-only
  "git status",
  "git log",
  "git diff",
  "git branch",
  "git show",
  "git rev-parse",
  "git remote",
  "git tag",
  "git stash list",
  // Node/Python version checks
  "node --version",
  "node -v",
  "python3 --version",
  "python --version",
  "npm --version",
  "pip --version",
  // Package info
  "npm ls",
  "npm list",
  "pip list",
  "pip show",
  // Container read-only
  "podman ps",
  "podman pod ps",
  "podman images",
  "podman logs",
  "podman inspect",
  "podman network inspect",
  "podman exec -i postgres pg_isready",
  "podman exec postgres psql",
  "podman exec telegram-gateway env",
  "docker ps",
  "docker images",
  "docker logs",
  // System info
  "netstat ",
  "ss ",
  "ip addr",
  "ip route",
  "curl -s -o /dev/null",
  "curl -sf",
  "curl -s ",
  "curl --",
  "command -v",
];

const SAFE_BASH_PATTERNS = [
  /^ls\b/,
  /^pwd$/,
  /^echo\b/,
  /^cat\s/,
  /^head\s/,
  /^tail\s/,
  /^git\s+(status|log|diff|show|branch|tag|remote|rev-parse|stash list)\b/,
  /^podman\s+(ps|pod ps|images|logs|inspect|network inspect|version)\b/,
  /^docker\s+(ps|images|logs|inspect|version)\b/,
  /^(which|whoami|date|env|printenv|id|uname|hostname|uptime|free|true|false)$/,
  /^command\s+-v\b/,
  /^test\s/,
  /^\[\s/,
];

function isSafeBashCommand(command) {
  if (!command) return false;
  const trimmed = command.trim();

  // Check prefix matches
  for (const prefix of SAFE_BASH_PREFIXES) {
    if (trimmed.startsWith(prefix) || trimmed === prefix.trim()) {
      return true;
    }
  }

  // Check regex patterns
  for (const pattern of SAFE_BASH_PATTERNS) {
    if (pattern.test(trimmed)) {
      return true;
    }
  }

  return false;
}

// ---------------------------------------------------------------------------
// HTTP helpers (Node built-in, zero dependencies)
// ---------------------------------------------------------------------------

function httpRequest(method, urlStr, body, token) {
  return new Promise((resolve, reject) => {
    const url = new URL(urlStr);
    const mod = url.protocol === "https:" ? https : http;
    const headers = { "Content-Type": "application/json" };
    if (token) headers["Authorization"] = `Bearer ${token}`;

    const opts = {
      hostname: url.hostname,
      port: url.port || (url.protocol === "https:" ? 443 : 80),
      path: url.pathname + url.search,
      method,
      headers,
      timeout: 10000,
    };

    const req = mod.request(opts, (res) => {
      let data = "";
      res.on("data", (chunk) => (data += chunk));
      res.on("end", () => {
        try {
          resolve({ status: res.statusCode, body: JSON.parse(data) });
        } catch {
          resolve({ status: res.statusCode, body: data });
        }
      });
    });

    req.on("error", reject);
    req.on("timeout", () => {
      req.destroy();
      reject(new Error("Request timeout"));
    });

    if (body) req.write(JSON.stringify(body));
    req.end();
  });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ---------------------------------------------------------------------------
// Sanitize sensitive data from command text before sending to Telegram
// ---------------------------------------------------------------------------

const SENSITIVE_PATTERNS = [
  // Bearer/API tokens (Authorization headers)
  { re: /(Bearer\s+)\S+/gi, sub: "$1[REDACTED]" },
  // Common auth header patterns in curl commands
  { re: /(-H\s+["']Authorization:\s*Bearer\s+)\S+(["'])/gi, sub: "$1[REDACTED]$2" },
  { re: /(-H\s+["']X-API-Key:\s*)\S+(["'])/gi, sub: "$1[REDACTED]$2" },
  // API keys / tokens (sk-*, key-*, token patterns)
  { re: /\b(sk-[a-zA-Z0-9_-]{10,})\b/g, sub: "[REDACTED-API-KEY]" },
  { re: /\b(sk-ant-api\S+)\b/g, sub: "[REDACTED-API-KEY]" },
  { re: /\b(sk-or-v1-\S+)\b/g, sub: "[REDACTED-API-KEY]" },
  { re: /\b(sk-proj-\S+)\b/g, sub: "[REDACTED-API-KEY]" },
  { re: /\b(sk-litellm-\S+)\b/g, sub: "[REDACTED-API-KEY]" },
  { re: /\b(xai-\S{20,})\b/g, sub: "[REDACTED-API-KEY]" },
  { re: /\b(gsk_\S{20,})\b/g, sub: "[REDACTED-API-KEY]" },
  { re: /\b(AIzaSy\S{20,})\b/g, sub: "[REDACTED-API-KEY]" },
  { re: /\b(re_[A-Za-z0-9_]{10,})\b/g, sub: "[REDACTED-API-KEY]" },
  // JWT tokens (three dot-separated base64 segments)
  { re: /\beyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\b/g, sub: "[REDACTED-JWT]" },
  // Telegram bot tokens (digits:alphanumeric)
  { re: /\b\d{8,}:[A-Za-z0-9_-]{30,}\b/g, sub: "[REDACTED-BOT-TOKEN]" },
  // Passwords in env vars or CLI flags
  { re: /(PASSWORD[=:]\s*["']?)[^\s"']+/gi, sub: "$1[REDACTED]" },
  { re: /(SECRET[=:]\s*["']?)[^\s"']+/gi, sub: "$1[REDACTED]" },
  { re: /(TOKEN[=:]\s*["']?)[^\s"']{15,}/gi, sub: "$1[REDACTED]" },
  // Cloudflare tunnel tokens (long base64)
  { re: /(cloudflare[_-]tunnel[_-]token[=:]\s*["']?)[^\s"']+/gi, sub: "$1[REDACTED]" },
  // Generic long hex/base64 secrets (32+ chars, likely tokens)
  { re: /(-e\s+\w*(?:TOKEN|SECRET|PASSWORD|KEY)\s*=\s*["']?)[^\s"']{15,}/gi, sub: "$1[REDACTED]" },
];

function sanitize(text) {
  let result = text;
  for (const { re, sub } of SENSITIVE_PATTERNS) {
    // Reset lastIndex for global regexes
    re.lastIndex = 0;
    result = result.replace(re, sub);
  }
  return result;
}

// ---------------------------------------------------------------------------
// Format tool call for Telegram display
// ---------------------------------------------------------------------------

function formatToolDescription(toolName, toolInput) {
  let text;
  switch (toolName) {
    case "Bash": {
      const cmd = toolInput.command || "";
      const desc = toolInput.description || "";
      text = `Tool: Bash\nCommand: ${cmd}`;
      if (desc) text += `\nDescription: ${desc}`;
      break;
    }
    case "WebFetch": {
      const url = toolInput.url || "";
      text = `Tool: WebFetch\nURL: ${url}`;
      break;
    }
    case "WebSearch": {
      const query = toolInput.query || "";
      text = `Tool: WebSearch\nQuery: ${query}`;
      break;
    }
    case "Write": {
      const fp = toolInput.file_path || "";
      text = `Tool: Write\nFile: ${fp}`;
      break;
    }
    case "Edit": {
      const fp = toolInput.file_path || "";
      text = `Tool: Edit\nFile: ${fp}`;
      break;
    }
    default:
      text = `Tool: ${toolName}\n${JSON.stringify(toolInput).slice(0, 500)}`;
  }
  return sanitize(text);
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  // Read JSON from stdin
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  const input = JSON.parse(Buffer.concat(chunks).toString("utf-8"));

  const toolName = input.tool_name || "";
  const toolInput = input.tool_input || {};

  // ---------------------------------------------------------------------------
  // Sensitive file detection — shared by Read, Edit, Write
  // ---------------------------------------------------------------------------
  function isForbiddenFile(filePath) {
    const fp = (filePath || "").toLowerCase();
    // .vault_pass must NEVER be read, written, or edited
    if (fp.includes(".vault_pass") || fp.includes("vault_pass") || fp.includes("vault-pass")) {
      return "forbidden";
    }
    return null;
  }

  function isSensitiveFile(filePath) {
    const fp = (filePath || "").toLowerCase();
    return (
      fp.includes("vault.yml") ||
      (fp.includes(".env") && !fp.includes(".env.example")) ||
      fp.includes("credentials") ||
      fp.includes(".pem") ||
      fp.includes(".key") ||
      fp.includes("id_rsa") ||
      fp.includes("id_ed25519") ||
      fp.includes("token.json") ||
      fp.includes("telegram-approval.json")
    );
  }

  // Block forbidden files immediately — no approval possible
  if (toolName === "Read" || toolName === "Edit" || toolName === "Write") {
    const fp = toolInput.file_path || "";
    if (isForbiddenFile(fp)) {
      process.stdout.write(
        JSON.stringify({
          hookSpecificOutput: {
            hookEventName: "PreToolUse",
            permissionDecision: "deny",
            permissionDecisionReason: "Blocked: .vault_pass access is forbidden",
          },
        })
      );
      return;
    }
  }

  // Glob, Grep — always safe (read-only, no single file target), auto-approve
  if (toolName === "Glob" || toolName === "Grep") {
    process.stdout.write(
      JSON.stringify({
        hookSpecificOutput: {
          hookEventName: "PreToolUse",
          permissionDecision: "allow",
          permissionDecisionReason: "Auto-approved: read-only search tool",
        },
      })
    );
    return;
  }

  // Read — auto-approve unless targeting sensitive files (those go to Telegram)
  if (toolName === "Read") {
    if (!isSensitiveFile(toolInput.file_path)) {
      process.stdout.write(
        JSON.stringify({
          hookSpecificOutput: {
            hookEventName: "PreToolUse",
            permissionDecision: "allow",
            permissionDecisionReason: "Auto-approved: non-sensitive file read",
          },
        })
      );
      return;
    }
  }

  // Edit, Write — auto-approve unless targeting sensitive files
  if (toolName === "Edit" || toolName === "Write") {
    if (!isSensitiveFile(toolInput.file_path)) {
      process.stdout.write(
        JSON.stringify({
          hookSpecificOutput: {
            hookEventName: "PreToolUse",
            permissionDecision: "allow",
            permissionDecisionReason: "Auto-approved: non-sensitive file edit",
          },
        })
      );
      return;
    }
  }

  // Safe Bash commands
  if (toolName === "Bash" && isSafeBashCommand(toolInput.command)) {
    process.stdout.write(
      JSON.stringify({
        hookSpecificOutput: {
          hookEventName: "PreToolUse",
          permissionDecision: "allow",
          permissionDecisionReason: "Auto-approved: safe read-only command",
        },
      })
    );
    return;
  }

  // Auto-approve Bash calls to yt-transcript.py (our own transcript tool)
  if (toolName === "Bash") {
    const cmd = (toolInput.command || "").trim();
    if (cmd.includes("yt-transcript.py") || cmd.includes("list-patterns.sh")) {
      process.stdout.write(
        JSON.stringify({
          hookSpecificOutput: {
            hookEventName: "PreToolUse",
            permissionDecision: "allow",
            permissionDecisionReason: "Auto-approved: internal transcript tool",
          },
        })
      );
      return;
    }
  }

  // WebFetch — auto-approve (read-only HTTP fetches are safe)
  if (toolName === "WebFetch") {
    process.stdout.write(
      JSON.stringify({
        hookSpecificOutput: {
          hookEventName: "PreToolUse",
          permissionDecision: "allow",
          permissionDecisionReason: "Auto-approved: WebFetch (read-only)",
        },
      })
    );
    return;
  }

  // WebSearch — auto-approve (read-only web searches are safe)
  if (toolName === "WebSearch") {
    process.stdout.write(
      JSON.stringify({
        hookSpecificOutput: {
          hookEventName: "PreToolUse",
          permissionDecision: "allow",
          permissionDecisionReason: "Auto-approved: WebSearch (read-only)",
        },
      })
    );
    return;
  }

  // Task (subagent) — auto-approve (spawns internal Claude agents, no external side effects)
  if (toolName === "Task") {
    process.stdout.write(
      JSON.stringify({
        hookSpecificOutput: {
          hookEventName: "PreToolUse",
          permissionDecision: "allow",
          permissionDecisionReason: "Auto-approved: Task subagent",
        },
      })
    );
    return;
  }

  // Validate config
  if (!GATEWAY_TOKEN || !CHAT_ID) {
    // Can't reach Telegram — fall back to CLI prompt
    process.stderr.write(
      "telegram-approval-hook: Missing TELEGRAM_GATEWAY_TOKEN or TELEGRAM_CHAT_ID\n"
    );
    process.exit(0); // exit 0 = ask user in CLI (default behavior)
  }

  // Build approval prompt text
  const promptText = formatToolDescription(toolName, toolInput);

  // POST /request_approval
  let approvalId;
  try {
    const resp = await httpRequest(
      "POST",
      `${GATEWAY_URL}/request_approval`,
      {
        chat_id: CHAT_ID,
        prompt_text: promptText,
        metadata: {
          tool_name: toolName,
          hook_event: "PreToolUse",
          session_id: input.session_id || null,
        },
      },
      GATEWAY_TOKEN
    );

    if (!resp.body.ok || !resp.body.approval_id) {
      process.stderr.write(
        `telegram-approval-hook: Failed to create approval: ${JSON.stringify(resp.body)}\n`
      );
      process.exit(0); // fall back to CLI
    }
    approvalId = resp.body.approval_id;
  } catch (err) {
    process.stderr.write(
      `telegram-approval-hook: Gateway unreachable: ${err.message}\n`
    );
    process.exit(0); // fall back to CLI
  }

  // Poll /get_approval_status until decided or timeout
  const deadline = Date.now() + POLL_TIMEOUT_MS;

  while (Date.now() < deadline) {
    await sleep(POLL_INTERVAL_MS);

    try {
      const resp = await httpRequest(
        "GET",
        `${GATEWAY_URL}/get_approval_status?approval_id=${approvalId}`,
        null,
        GATEWAY_TOKEN
      );

      if (!resp.body.ok) continue;

      const status = resp.body.status;

      if (status === "approved") {
        process.stdout.write(
          JSON.stringify({
            hookSpecificOutput: {
              hookEventName: "PreToolUse",
              permissionDecision: "allow",
              permissionDecisionReason: "Approved via Telegram",
            },
          })
        );
        return;
      }

      if (status === "denied") {
        process.stdout.write(
          JSON.stringify({
            hookSpecificOutput: {
              hookEventName: "PreToolUse",
              permissionDecision: "deny",
              permissionDecisionReason: "Denied via Telegram",
            },
          })
        );
        return;
      }

      if (status === "expired") {
        process.stdout.write(
          JSON.stringify({
            hookSpecificOutput: {
              hookEventName: "PreToolUse",
              permissionDecision: "deny",
              permissionDecisionReason: "Approval expired (no response within timeout)",
            },
          })
        );
        return;
      }

      // status === "pending" — keep polling
    } catch (err) {
      process.stderr.write(
        `telegram-approval-hook: Poll error: ${err.message}\n`
      );
      // Continue polling on transient errors
    }
  }

  // Timeout — fall back to CLI prompt
  process.stderr.write("telegram-approval-hook: Poll timeout, falling back to CLI\n");
  process.exit(0);
}

main().catch((err) => {
  process.stderr.write(`telegram-approval-hook: ${err.message}\n`);
  process.exit(0); // safe fallback
});
