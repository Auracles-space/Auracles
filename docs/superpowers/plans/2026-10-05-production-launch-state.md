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
3. **No alarm has been proven to arrive.** The SNS topic's subscription was
   confirmed for staging and production publishes to the same topic, but a green
   apply is not evidence of delivery.
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
- [ ] Force one alarm into `ALARM` with `aws cloudwatch set-alarm-state` and
      confirm the mail arrives.
- [ ] Point-in-time **restore drill** into a throwaway instance, then delete it.
- [ ] Resend: confirm `auracles.space` is a verified sending domain for live
      traffic.
- [ ] `CLAUDE.md`'s tech-stack table and §8 of
      `2026-08-24-aws-hybrid-infra-design.md` still describe the Render cutover,
      which is history.
- [ ] `config.py`'s `production_provider_secrets_are_not_placeholders` demands
      the two **Stripe** secrets and ignores **Paystack**, the only live rail.
      Production could boot with no Paystack key and fail at the first charge
      rather than at startup. Needs a decision: it is a boot-blocking validator.
- [ ] Apply for AWS Activate Founders credits if still unapplied — roughly eight
      months of runway at this burn.
- [ ] Delete the waitlist Amplify app, **a week after launch at the earliest**.

## Cost

Roughly **$105–135/month** at pilot scale, by the stack plan's table. Staging
adds ~$2–3/day only while it is up for a QA cycle; it is currently down.
