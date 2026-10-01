// Repo scanning. Pure data: no HTTP, no formatting, so it can be exercised
// directly (`node scan.mjs --once`) without starting a server.
import { execFile } from "node:child_process";
import { readdir, stat } from "node:fs/promises";
import { join } from "node:path";
import { promisify } from "node:util";

const run = promisify(execFile);

// Every git call is bounded. One unresponsive repository (a stale network
// remote, a filesystem hiccup) must not stall the whole sweep, so a timeout
// here is what keeps the dashboard honest about the other 63.
const GIT_TIMEOUT_MS = 10_000;
const CONCURRENCY = 8;

async function git(cwd, args) {
  try {
    const { stdout } = await run("git", ["-C", cwd, ...args], {
      timeout: GIT_TIMEOUT_MS,
      maxBuffer: 8 * 1024 * 1024,
    });
    return stdout;
  } catch (error) {
    // Distinguish "git said no" from "git never answered": a timeout is a
    // scan problem, a non-zero exit is usually a legitimate repo state.
    const reason = error.killed ? "timed out" : (error.stderr || error.message || "").trim();
    throw new Error(reason.split("\n")[0] || "git failed");
  }
}

/** Parses `git status --porcelain=v2 --branch` into branch position and work-tree counts. */
function parseStatus(stdout) {
  const out = {
    head: null,
    upstream: null,
    ahead: 0,
    behind: 0,
    staged: 0,
    modified: 0,
    untracked: 0,
    conflicted: 0,
  };
  for (const line of stdout.split("\n")) {
    if (!line) continue;
    if (line.startsWith("# branch.head ")) {
      const v = line.slice(14).trim();
      out.head = v === "(detached)" ? null : v;
    } else if (line.startsWith("# branch.upstream ")) {
      out.upstream = line.slice(18).trim();
    } else if (line.startsWith("# branch.ab ")) {
      const m = line.slice(12).trim().match(/^\+(\d+)\s+-(\d+)$/);
      if (m) {
        out.ahead = Number(m[1]);
        out.behind = Number(m[2]);
      }
    } else if (line.startsWith("1 ") || line.startsWith("2 ")) {
      // XY field: index status then work-tree status. A file can be both.
      const xy = line.slice(2, 4);
      if (xy[0] !== ".") out.staged += 1;
      if (xy[1] !== ".") out.modified += 1;
    } else if (line.startsWith("u ")) {
      out.conflicted += 1;
    } else if (line.startsWith("? ")) {
      out.untracked += 1;
    }
  }
  return out;
}

const FIELD = "\x1f"; // unit separator: cannot occur in a ref name or subject
const RECORD = "\x1e";

/** Every local branch, with where it sits relative to its upstream. */
async function branches(dir) {
  const fmt = [
    "%(refname:short)",
    "%(upstream:short)",
    "%(upstream:track)",
    "%(committerdate:unix)",
    "%(contents:subject)",
    "%(authorname)",
  ].join(FIELD);
  const stdout = await git(dir, [
    "for-each-ref",
    `--format=${fmt}${RECORD}`,
    "refs/heads",
  ]);
  return stdout
    .split(RECORD)
    .map((r) => r.replace(/^\n/, ""))
    .filter(Boolean)
    .map((record) => {
      const [name, upstream, track, when, subject, author] = record.split(FIELD);
      const ahead = Number(/ahead (\d+)/.exec(track || "")?.[1] ?? 0);
      const behind = Number(/behind (\d+)/.exec(track || "")?.[1] ?? 0);
      return {
        name,
        upstream: upstream || null,
        // "[gone]" means the upstream was deleted on the remote: the branch is
        // very often merged-and-cleaned-up, which is worth surfacing rather
        // than showing as an ordinary unsynced branch.
        gone: /gone/.test(track || ""),
        ahead,
        behind,
        when: Number(when) || 0,
        subject: subject || "",
        author: author || "",
      };
    })
    .sort((a, b) => b.when - a.when);
}

function parseRemote(url) {
  if (!url) return null;
  const m = url.trim().match(/github\.com[:/]+([^/]+)\/(.+?)(?:\.git)?$/);
  return m ? `${m[1]}/${m[2]}` : null;
}

async function scanRepo(root, name) {
  const dir = join(root, name);
  const repo = { name, dir, error: null };
  try {
    const [statusOut, branchList, stashOut, remoteOut] = await Promise.all([
      git(dir, ["status", "--porcelain=v2", "--branch"]),
      branches(dir).catch(() => []),
      git(dir, ["stash", "list"]).catch(() => ""),
      git(dir, ["remote", "get-url", "origin"]).catch(() => ""),
    ]);
    Object.assign(repo, parseStatus(statusOut));
    repo.branches = branchList;
    repo.stashes = stashOut.split("\n").filter(Boolean).length;
    repo.slug = parseRemote(remoteOut);
    repo.detached = repo.head === null;

    const last = await git(dir, [
      "log",
      "-1",
      `--format=%h${FIELD}%cr${FIELD}%s`,
    ]).catch(() => "");
    if (last) {
      const [hash, rel, subject] = last.trim().split(FIELD);
      repo.last = { hash, rel, subject };
    } else {
      // An initialised repository with no commits at all. Committing on it
      // while HEAD is unborn is a real trap, so it gets its own state.
      repo.last = null;
      repo.unborn = true;
    }
  } catch (error) {
    repo.error = error.message;
  }
  repo.dirty = (repo.staged || 0) + (repo.modified || 0) + (repo.untracked || 0) + (repo.conflicted || 0);
  return repo;
}

export async function listRepos(root) {
  const entries = await readdir(root, { withFileTypes: true });
  const dirs = [];
  for (const e of entries) {
    if (!e.isDirectory() || e.name.startsWith(".")) continue;
    try {
      await stat(join(root, e.name, ".git"));
      dirs.push(e.name);
    } catch {
      /* not a repository */
    }
  }
  return dirs.sort();
}

export async function scanAll(root) {
  const names = await listRepos(root);
  const results = [];
  // Bounded concurrency: 64 repositories x 5 git processes at once would
  // thrash the disk and make the scan slower, not faster.
  for (let i = 0; i < names.length; i += CONCURRENCY) {
    const batch = names.slice(i, i + CONCURRENCY);
    results.push(...(await Promise.all(batch.map((n) => scanRepo(root, n)))));
  }
  return results;
}

/** Open pull requests for every repo in one call, rather than one call per repo. */
export async function fetchPullRequests(owner) {
  try {
    const { stdout } = await run(
      "gh",
      [
        "search", "prs",
        "--owner", owner,
        "--state", "open",
        "--limit", "100",
        "--json", "repository,number,title,url,isDraft,updatedAt,author",
      ],
      { timeout: 20_000, maxBuffer: 4 * 1024 * 1024 },
    );
    const byRepo = {};
    for (const pr of JSON.parse(stdout)) {
      const key = pr.repository?.name;
      if (!key) continue;
      (byRepo[key] ??= []).push({
        number: pr.number,
        title: pr.title,
        url: pr.url,
        draft: pr.isDraft,
        updated: pr.updatedAt,
        author: pr.author?.login ?? "",
      });
    }
    return { byRepo, error: null };
  } catch (error) {
    // Never fail the whole dashboard because GitHub is unreachable or gh is
    // logged out. The local picture is the part that must always render.
    return { byRepo: {}, error: (error.stderr || error.message || "gh failed").trim().split("\n")[0] };
  }
}

// `--json ROOT` prints one JSON document in the exact shape server.mjs serves at
// /api/state, so a remote host (the VPS) can be scanned over ssh by the ops
// dashboard without running the server there.
if (process.argv[2] === "--json") {
  const root = process.argv[3] || process.cwd();
  const started = Date.now();
  const repos = await scanAll(root);
  process.stdout.write(JSON.stringify({
    repos, prs: {}, prError: "pull requests are only fetched by the interactive server",
    scannedAt: new Date().toISOString(), scanMs: Date.now() - started, root,
  }));
} else if (process.argv[2] === "--once") {
  const root = process.argv[3] || process.cwd();
  const repos = await scanAll(root);
  const dirty = repos.filter((r) => r.dirty > 0).length;
  const ahead = repos.filter((r) => r.ahead > 0).length;
  console.log(`${repos.length} repos · ${dirty} dirty · ${ahead} with unpushed commits`);
  for (const r of repos.filter((x) => x.dirty || x.ahead || x.error)) {
    console.log(
      `  ${r.name.padEnd(38)} ${String(r.dirty).padStart(3)} dirty  ${String(r.ahead).padStart(2)} ahead  ${r.error ?? ""}`,
    );
  }
}
