# Facts about completed one-time manual steps. Committed: this records where
# the world is, not a preference.
#
# The four NS records went live at Namecheap on 2026-09-02 (verified:
# `dig NS staging.auracles.space` returns the Route 53 set worldwide). The
# variable's default stays false so a rebuild in a fresh account starts back
# at pass one of the two-pass apply.

dns_delegation_complete = true

# Stripe's publishable key is public by definition — `next build` inlines it
# into the JavaScript every visitor downloads, so committing it reveals
# nothing. The secret key it pairs with lives in Secrets Manager and appears
# nowhere in this repository.
stripe_publishable_key = "pk_test_51TiLS9Pob42GNkA63DVRkXejrFaLN2uc4tMOESFBVPOxioIJDJ1RYzkgEiISGFFba0VezcxUOcqXQvnwxtLFmAMa00HVvAwFQw"

# The staging frontend starts on its amplifyapp.com URL. Flip to true and
# re-apply once it builds cleanly, to serve it at staging.auracles.space.
staging_frontend_custom_domain = false
