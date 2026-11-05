# Bot Doctor build of Hermes Agent — November 2026

If you are running an older Bot Doctor build of Hermes, this is the note on what
changed, what to install, and why the current build looks the way it does.

> **Want the kit?** The three patches and three plugins below are packaged as one small repo with an `apply.py`. It is private until Deacon has reviewed it. Ping **Mac** (Deacon's operator agent) or Deacon for the link.

**Short version:** stop using this fork as your runtime. Install upstream Hermes,
pin the commit below, add three patches and three plugins, and you have the same
build Bot Doctor runs on every managed agent today.

## What changed on November 4, 2026

The old Bot Doctor build carried roughly a dozen runtime patches plus a stack of
home-directory plugins, many of them overriding upstream files. Keeping that in
sync with upstream Hermes cost a day every release and broke in ways that were
hard to see.

We cut it down to the smallest thing that still does the job:

| Layer | Before | Now |
|---|---|---|
| Upstream Hermes | this fork (July 2026 code) | upstream `NousResearch/hermes-agent` at a pinned commit |
| Runtime patches | ~12, several rewriting upstream modules | **3**, each with a written reason and a retirement condition |
| Plugins | ~14 in `~/.hermes/plugins`, 4 shadowing bundled ones | **3 Bot Doctor plugins + the native Telegram plugin**; everything else retired |
| Telegram | custom direction cards, ledger patches | native plain updates; one optional progress-card plugin |
| Rollout | hand-run scripts | Operator Control executor with rollback and receipts |

This build is called **`minimal-native`**. Internal Golden id `4197b19f`.

## 1. Upstream pin

```
NousResearch/hermes-agent @ 6112c2adb9e11f69734a29be9d2696f345ffa06a   (2026-11-02)
```

Install upstream normally (`curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash`),
then check out that commit in the install directory, or build a venv from it.
Newer upstream commits probably work; that one is what we verified.

## 2. The three patches

All three live in the Bot Doctor Golden repo under `patches/modules/` and apply
idempotently (each writes a marker so a second apply is a no-op).

| Patch | What it does | Why it is still a patch |
|---|---|---|
| `session_url_storage_redaction_v1` | Tool results can carry temporary signed URLs. The patch keeps them usable during the turn but strips them before anything is written to saved transcripts. | Upstream redacts some secrets in display but not URL access grants in every saved copy. Retire when it does. |
| `gateway_progress_renderer_v1` | Adds a presentation hook so an optional plugin can render the gateway's progress heartbeat (used by the Telegram progress cards below). Native delivery stays in charge. | Upstream heartbeat delivery has no presentation hook. Retire when it exposes one. |
| `broker_codex_jobs_v1` | Removes the optional Codex request compression (retained requests came back HTTP 400 with zstd; raw JSON completes), and routes auxiliary calls and vendor CLI workers through the Bot Doctor credential-pool broker so a rate-limited Codex subscription fails over to another one before output. | Upstream Codex transport still sends the compressed body, and has no multi-subscription failover. Retire when both land upstream. |

Apply: `python3 patches/apply-all-patches.py --runtime <hermes install dir>` from the Golden repo. Each patch has its own pytest under `bin/test/`.

If you do not use Codex subscriptions through a broker, you can skip the third
patch. The other two are small and safe anywhere.

## 3. The plugins

Enabled in `config.yaml`:

```yaml
plugins:
  enabled:
    - platforms/telegram        # upstream's own Telegram plugin, unmodified
    - botdoctor-immersion
    - botdoctor-telegram
    - composio-onboarding
```

| Plugin | What it does |
|---|---|
| `botdoctor-immersion` (0.4.0) | LLM-request middleware. Injects the Bot Doctor operating floor exactly once per request: the Westminster/Marque covenant, truth-over-comfort rules, and the completion contract ("say produced vs verified vs delivered"). This is the personality and discipline layer; everything else is plumbing. |
| `botdoctor-telegram` (1.0.0) | Optional. Plan-aware progress cards in Telegram built from the model's actual commentary, using the renderer hook from patch 2. Turn it off and you get upstream's plain updates. |
| `composio-onboarding` (0.6.0) | Client-scoped Composio OAuth onboarding and verified connection routing, so a client can connect Gmail/Calendar/etc. from chat and the agent only sees that client's connections. |

Copy them from the Golden repo's `plugins/` into `~/.hermes/plugins/`. Do not
copy anything else from an old build's plugins directory.

### Retired (remove these if your old build has them)

`telegram-transcript`, `telegram-topic-post`, `telegram-email-card-qa`,
`task-ledger`, `skill-category-recovery`, `mcp-on-demand-control` (upstream now
ships MCP on-demand natively), `hermes-lcm`, `autodream` (upstream has its own),
`semantic-computer-control-guard`, and any `telegram-platform` directory in
`~/.hermes/plugins` (it shadows upstream's bundled Telegram plugin and was the
cause of two rollout failures on Nov 4). Delete or move them out of
`~/.hermes/plugins` and remove them from `plugins.disabled` too; a disabled
plugin that is still listed in `platform_toolsets` blocks admission.

## 4. Config conventions

- **Models:** OpenAI Codex is the primary. Agents do not pin a model; they take
  the host default. Scripts and bots declare a tier (`cheap` / `standard` /
  `strong`) that maps to a model in `auxiliary.bot_tiers`. No third-party API
  fallback.
- **Telegram:** native plain updates. The only Telegram-specific setting we
  carry is the optional progress-card plugin.
- **Self-heal:** if you use a heartbeat script that restarts the gateway on a
  stale `last_successful_poll_at`, change it to read `~/.hermes/gateway_state.json`
  freshness instead. The minimal build does not write the old poll receipt, and
  the old rule restarts a healthy gateway every 15 minutes (fixed in Golden PR
  #1420).
- **Everything else:** upstream defaults.

## 5. Why it is this way

Every patch above has a one-line reason and a condition under which we delete
it. If upstream ships the behavior, the patch goes. That is the whole policy.
The old build drifted because patches stayed after their reason was gone, and
plugins kept overriding upstream files nobody looked at. Three patches with
exit criteria is a build one person can keep current in an afternoon.

## 6. If you are on the old fork

1. Back up `~/.hermes` (config, memories, sessions, plugins).
2. Install upstream Hermes and pin the commit in §1.
3. Apply the three patches (§2). Skip the broker patch if you do not use it.
4. Install the three plugins (§3); remove the retired ones from your plugin dir and config.
5. Copy your `config.yaml`, memories and sessions back. Review `plugins.enabled`
   / `plugins.disabled` / `platform_toolsets` against §3.
6. Start the gateway and send yourself one Telegram message. If you kept a
   self-heal script, apply the §4 change first.

Problems: open an issue on this repo. Keep credentials out of it.

---
*This repository (`Bot-Doctor-LLC/hermes-agent`) is kept for history and for
the two Telegram ledger fixes it carried in mid-2026. It is no longer the Bot
Doctor runtime. The runtime is upstream Hermes plus the patches and plugins
above.*
