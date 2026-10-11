# Production Launch State — 2026-10-05

What is live, what is verified, what is not, and what went wrong on the way.
Written the day of the cutover so the next person is not reconstructing it from
`git log`.

Companion to [2026-10-04-production-stack.md](2026-10-04-production-stack.md),
which holds the decisions and the task list.

---

## Live

**`https://auracles.space`** serves the product. `www` serves it too. The
waitlist is retired — no domain points at it.

| Layer | What | Where |
| --- | --- | --- |
| Frontend | Amplify `auracles-production` | eu-west-2, app `dwef7lar2xs07`, branch `main`, auto-build **off** |
| API | `https://api.auracles.space` | ECS Fargate, cluster `auracles-production`, service `api`, on-demand, 1 task |
| Worker | Celery + clamd sidecar | service `worker`, **Fargate Spot**, 1 task |
| Scheduler | Celery Beat | service `beat`, **on-demand**, 1 task |
| Database | PostgreSQL 16, `db.t4g.micro`, single-AZ in **eu-west-2b** | encrypted, 14-day PITR, deletion protection on, final snapshot on destroy |
| Cache/broker | ElastiCache Redis `cache.t4g.micro`, TLS-only | one node |
| Files | 4 S3 buckets, `force_destroy = false` | artifacts, avatars, reports, thumbnails |
| DNS | `api.auracles.space` delegated to Route 53; apex and `www` at Namecheap | ACM cert issued for the API, Amplify's own for the apex |
| Alerting | 7 CloudWatch alarms → shared SNS topic | all `OK` at launch |

Deploy path: `git tag v*` → `release.yml` re-points `:production` at that
commit's image, rolls all three services, waits for stable, **then** starts the
Amplify build pinned to the same commit. One tag moves both halves.

## Verified, not assumed

- `GET /v1/health` through the apex returns `{"api":"ok","database":"ok","redis":"ok"}`.
  This is also what proves the apex is on the new app: the waitlist build
  proxied `/api/*` to the retired Render service.
- Worker log shows `clamd started`, virus database test passed, `celery@… ready`.
- Beat log shows `Scheduler: Sending due task retry-partner-webhooks-minutely`
  firing on the minute — the scheduler is not merely running, it is scheduling.
- Paystack live webhook endpoint returns **400 to an unsigned POST**, so it is
  reachable from the internet and refuses spoofed payloads.
- Paystack transfer OTP confirmed **off** (an OTP-held transfer is abandoned
  after ~1h with no webhook and strands the beneficiary's balance).
- Admin account created: `admin_user created user_id=00547cef…`.
- Amplify production build succeeded on its own URL **before** the domain moved,
  which was the design doc's named launch risk.

## NOT verified — read this before telling anyone the site is open

1. **No real money has moved.** Live Paystack keys are in place and the webhook
   is proven reachable, but no purchase, payout or escrow release has run in
   production. Everything was exercised on staging against test keys. Do one
   small real purchase yourself first: "buyer charged, licence never granted" is
   a failure this codebase has shipped before
   (`routing-a-payment-means-checking-the-webhook`).
2. **The backup has never been restored.** 14 days of PITR now covers real user
   data and nobody has checked it produces a working database. Open risk in the
   infra design doc since the Neon era.
3. ~~No alarm has been proven to arrive.~~ **Proven 2026-10-05**: a forced
   alarm reached `dev@auracles.space`. Note that this address is also
   `ADMIN_EMAIL`, so it is the password-reset path for the only admin account —
   losing access to that mailbox costs more than alerts.
4. **Stripe is dummied, deliberately.** Both Stripe secrets hold non-placeholder
   dummies to satisfy the boot validator. Stripe carries no pilot traffic, so a
   stray webhook would fail signature verification and be refused — correct for
   a provider not in use. Replace both and create the real endpoint if Stripe
   ever comes into scope.
5. **Google sign-in reuses staging's OAuth client** (decision 2026-10-05). One
   client holds several redirect URIs. The accepted cost: a misconfiguration on
   that client reaches real sign-ins.
6. **Google Drive is hidden**, pending Google's approval of the OAuth app.
   `NEXT_PUBLIC_GOOGLE_DRIVE_ENABLED` is unset, so the import button and the
   Settings connect entry are both absent.

## Rollback

**It is no longer a quick DNS edit.** A CloudFront alias belongs to exactly one
distribution, so freeing `auracles.space` meant deleting the waitlist app's
domain association. Going back means re-associating it and waiting out the same
verification and propagation — tens of minutes, not minutes.

The waitlist app (`Auracles`, eu-north-1, `d34ih8666gpdu1`) is **still there and
should stay there** for now. It costs nothing, it still builds the frozen
`waitlist-live` branch, and it is the only route back to a working holding page.
Delete it a week after launch, not on launch day.

For the backend, rollback is cheaper: tag the previous good commit again. The old
image is still in ECR, and the task definitions pin digests.

## What went wrong, and what it cost

Four failures, all during the apply rather than after it. Recording them because
each is a trap for the next environment build.

**RDS refused to create.** `db.t4g.micro` on gp3 had no capacity in `2a` or
`2b`, and the networking module takes the first `az_count` AZ names — so
`az_count = 2` never reached `2d`, the only AZ AWS said had room. Both
environments now span all four AZs. Placement latitude, not an HA posture.
Ironically the instance then landed in `2b`, so the shortage was momentary; the
widening is still correct, because a one-AZ-wide subnet group turns a transient
capacity blip into a failed apply.

**Worker and beat came up to nothing.** Both died with
`ResourceInitializationError` on a valueless `DATABASE_URL` and their circuit
breakers rolled them back. The task definitions reference the composed secrets
by **ARN**, which exists as soon as the empty shell does — so Terraform had no
reason to wait for the *versions*, which cannot be written until RDS exists. The
api happened to start late enough to win the race, which is exactly how the same
gap stayed invisible in staging since it was built. Fixed with an explicit
`depends_on` in both environments; it is graph ordering, so live production
showed no diff.

The circuit breakers deserve credit here. Instead of two services crash-looping
for days while ECS reported `ACTIVE` — the 44-hour failure of 2026-09-27 — they
failed the rollout loudly and stopped.

**Amplify could not create the app at all.** `CreateApp` failed with a GitHub
422: deploy keys are disabled by default for new GitHub organizations, and
Amplify's repository handshake needs one. Enabled at
org settings → Member privileges → Deploy keys. The repo is public, so a
read-only deploy key exposes nothing that was not already public.

**The domain flip took three attempts.** Two mistakes, both mine:

- I said both apps could hold `auracles.space` at once and so there would be no
  downtime window. Amplify *accepted* the second association, but a CloudFront
  alias belongs to one distribution, so the new one sat `PENDING` and then
  `FAILED` while the waitlist kept serving. The old association has to go first.
  There is an unavoidable window.
- Recreating the association minted a **new CloudFront target**, silently
  invalidating the apex and `www` records that had just been entered. Anyone
  replacing an `aws_amplify_domain_association` must re-read the records
  afterwards and expect to change DNS again.

Also worth knowing: a "direct test" that pins curl to a distribution's IP proves
nothing. CloudFront IPs are shared and the **Host header** selects the
distribution, so the request lands on whichever one claims the alias.

## Remaining work

From the stack plan's Task 10, in the order worth doing:

- [ ] One small **real purchase** end to end (not in the original plan; the most
      important item here).
- [x] **Alert path proven 2026-10-05.** `auracles-production-beat-crashing`
      forced to `ALARM`; the mail arrived at `dev@auracles.space` and the
      alarm was reset. This was worth doing precisely because SNS reports a
      successful publish whether or not the mail lands.
- [ ] Point-in-time **restore drill** into a throwaway instance, then delete it.
- [ ] Resend: confirm `auracles.space` is a verified sending domain for live
      traffic.
- [ ] `CLAUDE.md`'s tech-stack table and §8 of
      `2026-08-24-aws-hybrid-infra-design.md` still describe the Render cutover,
      which is history.
- [x] **Live-rail boot validator, shipped in `v1.0.0`.** The validator now
      demands whichever provider `select_provider` returns for
      `PLATFORM_CURRENCY` — Paystack here — by calling that function rather
      than restating its rule, so it cannot drift. The idle provider may be
      absent (a payer routed to it fails at checkout; no money moves) but may
      not hold the placeholder string. `PAYSTACK_WEBHOOK_SECRET` is
      deliberately *not* required: Paystack signs with the integration secret
      key and that value only overrides it, so demanding it would have refused
      to boot the live configuration, which does not set it.
- [ ] Apply for AWS Activate Founders credits if still unapplied — roughly eight
      months of runway at this burn.
- [ ] Delete the waitlist Amplify app, **a week after launch at the earliest**.

## First tagged release — v1.0.0, 2026-10-05

Production launched on a manually promoted image (`make prod-promote-image`),
so `release.yml` had never run. `v1.0.0` is the first tag to travel it, and it
is now proven end to end: `:production` re-pointed at the tagged commit's
image, all three services rolled and stable, then the Amplify frontend built
pinned to the same commit. Run `37335767143`, green.

Carried two changes:

- The live-rail boot validator above. This release was the test of it: if
  `PAYSTACK_SECRET_KEY` had been absent, the api would have refused to start
  here rather than failing at the first charge. `/api/v1/health` through the
  apex returned `api/database/redis` all `ok` afterwards.
- The api **deployment circuit breaker**, applied to infrastructure just
  before the tag. Worker and beat had one since the 44-hour crash-loop of
  2026-09-27; the api did not, though §5 of the infra design says it should.
  It is safe next to migration-on-boot because of the existing 120s health
  check grace period — failures are not counted until it elapses, so a
  migration that outruns that becomes a rollback rather than an unreachable
  api with no signal. Live values confirmed on the service: `enable: true`,
  `rollback: true`.

Note that the task definitions stay at revision `:1`. `release.yml` re-points
a tag and forces a new deployment rather than registering a new revision, so
"revision unchanged" is not evidence that a release did not land.

## Third release — 2026-10-11, the team's first real publishing run

Three findings, all from the team publishing Frameworks for the first time at
volume. Worth reading together, because two of them were invisible precisely
because the third forced slow, serial work.

- **Artifact upload took one file at a time.** The input carried no `multiple`
  and both the picker and drop handlers read `files[0]`, while the control
  said "Upload files" and "Drop files here". The team pushed **56 files
  through production individually, every 6-12 seconds**, before mentioning it.
  Uploads now cover the whole selection, sequentially — each file needs its
  own presigned target and the 500MB cap must be checked against the running
  batch total, which a parallel batch cannot do without over-admitting. A
  failed file no longer abandons the ones after it, and every skipped file is
  named with its reason.
- **An abandoned upload froze its Framework permanently.**
  `request_artifact_upload_url` commits the Artifact row *before* the browser
  uploads anything, so a run that dies between the presigned POST and the
  confirm call leaves a row at `pending` with a null `processing_started_at`.
  The reaper matched only `processing` rows with a non-null start time, so
  nothing touched it — while `pipeline_gate` counts `pending` as in flight and
  held the Framework at `processing`. The reaper's docstring already claimed to
  recover a scan that was "never dispatched"; that was false for exactly that
  case. "Startup Strategy & Planning Framework" sat frozen from 2026-10-08.
  The reaper now also covers never-started rows, aged from `created_at`
  because that is the only clock such a row has.

  **That fix was only half the recovery, and production said so.** Within
  minutes of `v1.0.3` the reaper moved the stranded row to `failed` and the
  Framework stayed at `processing`, because `pipeline_gate` derives Framework
  status from its Artifacts and nothing else re-derives it — the gate runs at
  the end of an Artifact's pipeline or on submit with `force`, neither of
  which a reap triggers. The reaper now re-evaluates each reaped row's parent
  Framework, once per Framework rather than per row and with `force=True`, so
  the Framework self-heals to `pipeline_failed` naming the failed file. The
  lesson worth keeping: freeing the row a gate is waiting on is not the same
  as releasing the gate.
- **`robots.txt` and `sitemap.xml` did not exist**, so both returned the app's
  404 page. An external verification scan (Spendbase, for AWS credits) flagged
  it. Policy decision 2026-10-11: public pages crawlable, since `/explore` and
  the Framework detail pages are SSR specifically to be indexed; auth-gated
  areas disallowed; and token-bearing routes (`/org-invitations`,
  `/reset-password`, `/verify-email`) disallowed for a different reason — one
  of those URLs in a search index is a leaked credential, not a wasted fetch.
  `/favicon.ico` still 404s, deliberately: the icons declared in the root
  layout both serve, and shipping a PNG misnamed `.ico` would be worse.

Two notes for whoever touches this next:

- The sitemap's Framework list is fetched at build time and **degrades rather
  than throws**, because a sitemap that throws fails the Amplify build and
  takes the frontend release down over a file no visitor reads. The first
  version of it asked for `page_size=200` against an endpoint capped at 100,
  and that guard turned the 422 into a silently Framework-less sitemap. It now
  warns on stderr when it degrades. Verify the built output by curling it, not
  by reading the build log.
- **The framework pipeline gate is not racy, though it looks it.** The gate
  call is the last step of each Artifact's pipeline and the step before it
  commits `processed`, so every evaluation happens strictly after its own
  Artifact's commit. For two Artifacts committing at `tA < tB`, B's gate runs
  after `tB > tA` and therefore sees both finished. Whichever commits last
  always evaluates a complete picture; an earlier, stale evaluation can only
  write `processing`, which is what the Framework already says. A row lock was
  proposed here and is not needed.

## Incident — GPTBot vs the shared rate-limit bucket, 2026-10-10/11

The `auracles-production-alb-5xx` alarm fired three times on 2026-10-10
morning and recovered each time, so it read as noise. It was not.
`HTTPCode_Target_5XX_Count` was **zero** throughout — the api never erred. The
5xx were ALB-generated, and the real signal was beside them: `RequestCount` at
2,300-6,700 per five minutes, roughly 8-22 requests a second, against a
platform with four users.

**What it was.** GPTBot/1.4 enumerating `/explore`'s faceted query space.
36,396 requests in 2.5 hours from two IPs; 36,361 of 36,396 were CloudFront
**misses**, because every filter combination is a distinct URL. Each miss cost
a server render and a `/v1/explore/catalog` query. Found in the Amplify access
logs (`aws amplify generate-access-logs`), after the ALB logs narrowed it to
`/v1/explore/catalog` with user agent `node` — i.e. our own renderer, not the
crawler, talking to the api.

**Why it hurt.** `/v1/explore/catalog` is rate-limited at 60 requests a minute
**per IP**. Every SSR render fetches from the frontend host, so the api sees one
address for every visitor's page load and per-IP limiting cannot separate them.
GPTBot drained the bucket that every render depends on, `loadExploreCatalog`
turned the 429 into `unavailable`, and the marketplace page told real visitors
the catalog was unavailable — on roughly three of four loads, for over a day,
before anyone connected it to the alarm.

**Fixed in v1.0.4**, two parts, because either alone would recur:

- `robots.txt` disallows `/explore?*`. The facet space is unbounded;
  `/explore` and `/explore/<id>` stay crawlable because they are finite and are
  the pages rendered SSR to be indexed. Note the `Allow: /` that invited this
  shipped in `v1.0.3` a few hours earlier — adding a `robots.txt` where there
  was none is not automatically an improvement.
- The renderer presents a Terraform-generated `INTERNAL_API_SECRET` and gets
  its own 1200/minute bucket. Finite on purpose: our own code looping is the
  other thing that has happened here (2026-09-29), and an unlimited internal
  caller turns that into unbounded load on one api task. A wrong or absent
  secret falls back to the public bucket, so an unconfigured deployment trusts
  nobody rather than everybody.

**Three traps found while fixing it**, each worth more than the fix:

1. **A `data "aws_secretsmanager_secret_version"` cannot read a shell created
   in the same apply.** The first version of the Terraform would have failed on
   its first run. Terraform now generates the value, which also removes the
   chance of the api and Amplify being given different strings — a mismatch
   fails silently by falling back to the public bucket, i.e. straight back into
   the incident.
2. **The execution-role policy and the task definitions both derive from
   `var.secret_arns` but did not depend on each other**, so Terraform could
   roll the services onto a revision naming a secret the role could not yet
   read. Same shape as the valueless-`DATABASE_URL` race on the first
   production apply, same fix: explicit `depends_on`.
3. **The generated API client is a module-level singleton and `setConfig`
   replaces the whole config.** Putting the header there meant `getHealth`
   blanked it on every call — 113 times in seven minutes — and Next serves
   concurrent SSR renders from one process, so renders in flight lost the
   header and fell back to the public bucket. 17% of catalog reads were still
   429 after `v1.0.4`. The header now travels per call.

**What to take from it.** The alarm was correct and the dashboard reading was
wrong: an ALB 5xx with zero target 5xx means the load balancer could not get a
healthy answer, so look at load and targets, not application errors. And
`RequestCount` is worth a glance whenever anything looks odd — 4.5 requests a
second holding to within 0.5% for an hour is a machine, and that constancy was
visible long before the cause was.

### Releases

- **v1.0.1** (2026-10-08) — preview eligibility and KYC admin notices.
- **v1.0.2** — *failed, nothing deployed.* The tag was cut while the working
  tree sat on a docs branch, so it pointed at a commit with no image.
  `release.yml` refused at the promote step rather than deploying anything,
  which is the guard working. The tag was deleted and `v1.0.3` cut from
  `main`. Worth knowing: `git rev-parse <tag>` on an annotated tag returns the
  *tag object*, so check `<tag>^{commit}` against `main` before trusting it.
- **v1.0.3** (2026-10-11) — the three fixes above. Verified live: `robots.txt`
  and `sitemap.xml` both 200, 7 static pages and 6 Frameworks in the sitemap,
  health `api/database/redis` all `ok`.
- **v1.0.4** (2026-10-11) — the crawl limit and the SSR rate-limit bucket, plus
  the reaper finally releasing the Framework it reaped for. `/explore` went
  from roughly one load in four serving the catalog to eight out of eight.
  Needed a `terraform apply` on both `infra/shared` and
  `infra/envs/production` before the tag; the applies were run from the feature
  branch, so `main` carried drift until the merge closed it. Plan from `main`
  afterwards: "No changes" on both stacks.

## Cost

Roughly **$105–135/month** at pilot scale, by the stack plan's table. Staging
adds ~$2–3/day only while it is up for a QA cycle; it is currently down.
