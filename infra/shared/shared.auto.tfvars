# Facts about completed one-time manual steps. Committed: this records where
# the world is, not a preference.
#
# The four NS records went live at Namecheap on 2026-09-02 (verified:
# `dig NS staging.auracles.space` returns the Route 53 set worldwide). The
# variable's default stays false so a rebuild in a fresh account starts back
# at pass one of the two-pass apply.

dns_delegation_complete = true
