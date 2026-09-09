# Platform NDA documents

One Markdown file per NDA version, named exactly for the version string in
`ORG_MEMBER_NDA_VERSION` (`1.0` → `1.0.md`). `nda_service.nda_document_text`
reads the file matching the configured version and raises if it is missing, so
bumping the version without adding its document fails loudly rather than
asking members to sign a blank agreement.

**Never edit a published version in place.** A signature records the version
it was given, and `member_is_assignable` treats that version as the thing the
member agreed to. Changing `1.0.md` silently rewrites what past signatories
are recorded as having accepted. To change the wording, add the new file and
bump `ORG_MEMBER_NDA_VERSION`; every member is then required to re-sign, which
is the intended behaviour.

Versions here are legal instruments. Wording changes go through the same
review as any other legal copy before the version is bumped in an environment
that serves real members.

## Status

`1.0.md` is an engineering draft written to unblock the signing flow, which
previously rendered two different hardcoded placeholders. It has **not** been
through legal review. Replace its wording — or publish `1.1` — before the
pilot signs real members, and set the governing-law clause deliberately rather
than inheriting the pilot market's default.
