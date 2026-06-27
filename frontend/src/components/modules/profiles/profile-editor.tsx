"use client";

/**
 * Owner profile editor.
 *
 * Loads the authenticated user's own profile and edits the public-facing
 * fields: avatar, headline, bio, location, website, specializations, and
 * portfolio links. Specializations and links use replace-all semantics — the
 * whole list is sent on save.
 *
 * Maps to: FR-SET-001/002.
 */
import { useEffect, useState } from "react";

import { AvatarUploader } from "@/components/modules/profiles/avatar-uploader";
import { Button } from "@/components/ui/button";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  getMyProfileV1ProfilesMeGet,
  updateMyProfileV1ProfilesMePatch,
} from "@/lib/generated/sdk.gen";
import type {
  ProfileLink,
  PublicProfileResponse,
} from "@/lib/generated/types.gen";

const FIELD_CLASS =
  "w-full rounded-xl border border-border-default bg-surface-1 px-3 py-3 text-sm text-foreground outline-none transition-colors focus:border-accent focus:ring-2 focus:ring-accent/20";
const LABEL_CLASS =
  "block text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted";

type ProfileEditorProps = {
  /** Seed data; when provided the editor skips its own load. */
  initialProfile?: PublicProfileResponse;
  /** Called with the saved profile after a successful update. */
  onSaved?: (profile: PublicProfileResponse) => void;
  /** When provided, renders a Cancel control. */
  onCancel?: () => void;
};

/**
 * Render the authenticated owner's profile editor.
 *
 * @param props - Optional seed profile and save/cancel callbacks. Without a
 *   seed the editor loads the owner's profile itself.
 */
export function ProfileEditor({
  initialProfile,
  onSaved,
  onCancel,
}: ProfileEditorProps = {}) {
  const [profile, setProfile] = useState<PublicProfileResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const [headline, setHeadline] = useState("");
  const [bio, setBio] = useState("");
  const [location, setLocation] = useState("");
  const [website, setWebsite] = useState("");
  const [specializations, setSpecializations] = useState<string[]>([]);
  const [specInput, setSpecInput] = useState("");
  const [links, setLinks] = useState<ProfileLink[]>([]);

  /**
   * Populate the form state from a loaded profile payload.
   *
   * @param data - The profile to seed the editor with.
   */
  function hydrate(data: PublicProfileResponse): void {
    setProfile(data);
    setHeadline(data.headline ?? "");
    setBio(data.bio ?? "");
    setLocation(data.location ?? "");
    setWebsite(data.website ?? "");
    setSpecializations(data.specializations ?? []);
    setLinks(data.links ?? []);
  }

  useEffect(() => {
    if (initialProfile) {
      hydrate(initialProfile);
      setLoading(false);
      return;
    }
    let mounted = true;
    async function load(): Promise<void> {
      configureBrowserClient();
      const result = await getMyProfileV1ProfilesMeGet({
        headers: getAccessTokenHeaders(),
      });
      if (!mounted) {
        return;
      }
      if (result.data) {
        hydrate(result.data);
      } else {
        setError(describeGeneratedError(result.error));
      }
      setLoading(false);
    }
    void load();
    return () => {
      mounted = false;
    };
  }, [initialProfile]);

  /**
   * Add the pending specialization chip, ignoring blanks and duplicates.
   */
  function addSpecialization(): void {
    const label = specInput.trim();
    if (!label) {
      return;
    }
    if (!specializations.some((item) => item.toLowerCase() === label.toLowerCase())) {
      setSpecializations([...specializations, label]);
    }
    setSpecInput("");
  }

  /**
   * Persist the edited profile.
   */
  async function save(): Promise<void> {
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      configureBrowserClient();
      const result = await updateMyProfileV1ProfilesMePatch({
        body: {
          headline: headline.trim() || null,
          bio: bio.trim() || null,
          location: location.trim() || null,
          website: website.trim() || null,
          specializations,
          links: links.filter((link) => link.label.trim() && link.url.trim()),
        },
        headers: getAccessTokenHeaders(),
      });
      if (result.data) {
        hydrate(result.data);
        setMessage("Profile saved.");
        onSaved?.(result.data);
      } else {
        setError(describeGeneratedError(result.error));
      }
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <p className="text-sm text-foreground-muted">Loading your profile…</p>;
  }

  if (!profile) {
    return (
      <p className="text-sm text-error">
        {error ?? "Your profile could not be loaded."}
      </p>
    );
  }

  return (
    <div className="space-y-6">
      <AvatarUploader
        avatarUrl={profile.avatar_url ?? null}
        displayName={profile.display_name}
        onUploaded={(url) =>
          setProfile((prev) => (prev ? { ...prev, avatar_url: url } : prev))
        }
      />

      <div className="space-y-2">
        <label className={LABEL_CLASS} htmlFor="headline">
          Headline
        </label>
        <input
          className={FIELD_CLASS}
          id="headline"
          maxLength={160}
          onChange={(event) => setHeadline(event.target.value)}
          placeholder="Compliance frameworks for fintech"
          value={headline}
        />
      </div>

      <div className="space-y-2">
        <label className={LABEL_CLASS} htmlFor="bio">
          Bio
        </label>
        <textarea
          className={FIELD_CLASS}
          id="bio"
          maxLength={2000}
          onChange={(event) => setBio(event.target.value)}
          placeholder="Tell people what you do and how you help."
          rows={4}
          value={bio}
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <label className={LABEL_CLASS} htmlFor="location">
            Location
          </label>
          <input
            className={FIELD_CLASS}
            id="location"
            maxLength={100}
            onChange={(event) => setLocation(event.target.value)}
            placeholder="Lagos, NG"
            value={location}
          />
        </div>
        <div className="space-y-2">
          <label className={LABEL_CLASS} htmlFor="website">
            Website
          </label>
          <input
            className={FIELD_CLASS}
            id="website"
            onChange={(event) => setWebsite(event.target.value)}
            placeholder="https://your-site.com"
            value={website}
          />
        </div>
      </div>

      <div className="space-y-2">
        <span className={LABEL_CLASS}>Specializations</span>
        <div className="flex flex-wrap gap-2">
          {specializations.map((item) => (
            <span
              className="inline-flex items-center gap-1.5 rounded-full border border-border-strong bg-surface-2 px-3 py-1.5 text-xs font-semibold text-foreground"
              key={item}
            >
              {item}
              <button
                aria-label={`Remove ${item}`}
                className="text-foreground-subtle hover:text-error"
                onClick={() =>
                  setSpecializations(specializations.filter((s) => s !== item))
                }
                type="button"
              >
                ×
              </button>
            </span>
          ))}
        </div>
        <div className="flex gap-2">
          <input
            className={FIELD_CLASS}
            maxLength={80}
            onChange={(event) => setSpecInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                addSpecialization();
              }
            }}
            placeholder="Add a specialization and press Enter"
            value={specInput}
          />
          <Button onClick={addSpecialization} variant="secondary">
            Add
          </Button>
        </div>
      </div>

      <div className="space-y-3">
        <span className={LABEL_CLASS}>Portfolio links</span>
        {links.map((link, index) => (
          <div className="flex flex-col gap-2 sm:flex-row" key={index}>
            <input
              className={`${FIELD_CLASS} sm:w-1/3`}
              maxLength={80}
              onChange={(event) =>
                setLinks(
                  links.map((l, i) =>
                    i === index ? { ...l, label: event.target.value } : l,
                  ),
                )
              }
              placeholder="Label"
              value={link.label}
            />
            <input
              className={FIELD_CLASS}
              onChange={(event) =>
                setLinks(
                  links.map((l, i) =>
                    i === index ? { ...l, url: event.target.value } : l,
                  ),
                )
              }
              placeholder="https://…"
              value={link.url}
            />
            <Button
              onClick={() => setLinks(links.filter((_, i) => i !== index))}
              variant="secondary"
            >
              Remove
            </Button>
          </div>
        ))}
        {links.length < 10 ? (
          <Button
            onClick={() => setLinks([...links, { label: "", url: "" }])}
            variant="secondary"
          >
            Add link
          </Button>
        ) : null}
      </div>

      <div className="flex items-center gap-4 border-t border-border-default pt-5">
        <Button loading={saving} onClick={save}>
          Save changes
        </Button>
        {onCancel ? (
          <Button onClick={onCancel} variant="secondary">
            Cancel
          </Button>
        ) : null}
        {message ? <p className="text-sm text-success">{message}</p> : null}
        {error ? <p className="text-sm text-error">{error}</p> : null}
      </div>
    </div>
  );
}
