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
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AvatarUploader } from "@/components/modules/profiles/avatar-uploader";
import { BannerUploader } from "@/components/modules/profiles/banner-uploader";
import {
  EducationEditor,
  ExperienceEditor,
} from "@/components/modules/profiles/cv-sections-editor";
import { FeaturedEditor } from "@/components/modules/profiles/featured-editor";
import { SocialLinksEditor } from "@/components/modules/profiles/social-links-editor";
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
  ProfileEducation,
  ProfileExperience,
  ProfileFeatured,
  ProfileLink,
  PublicProfileResponse,
  SocialLink,
} from "@/lib/generated/types.gen";

const FIELD_CLASS =
  "w-full rounded-xl border border-border-default bg-surface-1 px-3 py-3 text-sm text-foreground outline-none transition-colors focus:border-accent focus:ring-0";
const LABEL_CLASS =
  "block text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted";

type ProfileEditorProps = {
  /** Seed data; when provided the editor skips its own load. */
  initialProfile?: PublicProfileResponse;
  /** Called with the saved profile after a successful update. */
  onSaved?: (profile: PublicProfileResponse) => void;
  /** When provided, renders a Cancel control. */
  onCancel?: () => void;
  /** The owner's published Frameworks, offered in the Featured pin picker. */
  frameworkOptions?: { id: string; title: string }[];
};

/**
 * Render the authenticated owner's profile editor.
 *
 * @param props - Optional seed profile, save/cancel callbacks, and the owner's
 *   Frameworks for the Featured picker. Without a seed the editor loads itself.
 */
export function ProfileEditor({
  initialProfile,
  onSaved,
  onCancel,
  frameworkOptions = [],
}: ProfileEditorProps = {}) {
  const router = useRouter();
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
  const [socialLinks, setSocialLinks] = useState<SocialLink[]>([]);
  const [experience, setExperience] = useState<ProfileExperience[]>([]);
  const [education, setEducation] = useState<ProfileEducation[]>([]);
  const [featured, setFeatured] = useState<ProfileFeatured[]>([]);

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
    setSocialLinks(data.social_links ?? []);
    setExperience(data.experience ?? []);
    setEducation(data.education ?? []);
    setFeatured(data.featured ?? []);
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

  const currentBody = {
    headline: headline.trim() || null,
    bio: bio.trim() || null,
    location: location.trim() || null,
    website: website.trim()
      ? /^https?:\/\//i.test(website.trim())
        ? website.trim()
        : "https://" + website.trim()
      : null,
    specializations: [...specializations].sort(),
    links: links
      .filter((link) => link.label.trim() && link.url.trim())
      .map((link) => {
        let url = link.url.trim();
        if (url && !/^https?:\/\//i.test(url)) url = "https://" + url;
        return { label: link.label.trim(), url };
      }),
    social_links: socialLinks
      .filter((link) => link.url.trim())
      .map((link) => {
        let url = link.url.trim();
        if (url && !/^https?:\/\//i.test(url)) url = "https://" + url;
        return { platform: link.platform, url };
      }),
    featured: featured
      .filter((item) => item.framework_id || item.title?.trim())
      .map((item) => ({
        framework_id: item.framework_id ?? null,
        title: item.framework_id ? null : item.title?.trim() || null,
        description: item.description?.trim() || null,
        url: item.framework_id ? null : item.url?.trim() || null,
      })),
    experience: experience
      .filter((item) => item.title.trim() && item.company.trim())
      .map((item) => ({
        title: item.title.trim(),
        company: item.company.trim(),
        start: item.start?.trim() || null,
        end: item.end?.trim() || null,
        current: item.current ?? false,
        description: item.description?.trim() || null,
      })),
    education: education
      .filter((item) => item.school.trim())
      .map((item) => ({
        school: item.school.trim(),
        degree: item.degree?.trim() || null,
        field: item.field?.trim() || null,
        start_year: item.start_year || null,
        end_year: item.end_year || null,
      })),
  };

  const initialBody = profile
    ? {
        headline: profile.headline?.trim() || null,
        bio: profile.bio?.trim() || null,
        location: profile.location?.trim() || null,
        website: profile.website?.trim() || null,
        specializations: [...(profile.specializations ?? [])].sort(),
        links: (profile.links ?? []).map((l) => ({
          label: l.label.trim(),
          url: l.url.trim(),
        })),
        social_links: (profile.social_links ?? []).map((l) => ({
          platform: l.platform,
          url: l.url.trim(),
        })),
        featured: (profile.featured ?? []).map((item) => ({
          framework_id: item.framework_id ?? null,
          title: item.framework_id ? null : item.title?.trim() || null,
          description: item.description?.trim() || null,
          url: item.framework_id ? null : item.url?.trim() || null,
        })),
        experience: (profile.experience ?? []).map((item) => ({
          title: item.title.trim(),
          company: item.company.trim(),
          start: item.start?.trim() || null,
          end: item.end?.trim() || null,
          current: item.current ?? false,
          description: item.description?.trim() || null,
        })),
        education: (profile.education ?? []).map((item) => ({
          school: item.school.trim(),
          degree: item.degree?.trim() || null,
          field: item.field?.trim() || null,
          start_year: item.start_year || null,
          end_year: item.end_year || null,
        })),
      }
    : null;

  const hasChanges = initialBody
    ? JSON.stringify(currentBody) !== JSON.stringify(initialBody)
    : false;

  const isValidUrl = (url: string) => {
    if (!url.trim()) return true;
    let testUrl = url.trim();
    if (!/^https?:\/\//i.test(testUrl)) testUrl = "https://" + testUrl;
    try {
      const parsed = new URL(testUrl);
      return /\.[a-z]{2,}/i.test(parsed.hostname);
    } catch {
      return false;
    }
  };

  const hasInvalidWebsite = website.trim() ? !isValidUrl(website) : false;

  const hasInvalidLinks = links.some(
    (link) => (link.label.trim() && !link.url.trim()) || (!link.label.trim() && link.url.trim()) || (link.url.trim() && !isValidUrl(link.url))
  );
  
  const hasInvalidSocialLinks = socialLinks.some(
    (link) => link.url.trim() && !isValidUrl(link.url)
  );

  const hasInvalidExperience = experience.some(
    (item) => (item.title.trim() && !item.company.trim()) || (!item.title.trim() && item.company.trim())
  );
  
  const hasValidationErrors = hasInvalidWebsite || hasInvalidLinks || hasInvalidSocialLinks || hasInvalidExperience;
  const canSave = hasChanges && !hasValidationErrors;

  /**
   * Persist the edited profile.
   */
  async function save(): Promise<void> {
    if (!canSave) return;
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      configureBrowserClient();
      const result = await updateMyProfileV1ProfilesMePatch({
        body: currentBody,
        headers: getAccessTokenHeaders(),
      });
      if (result.data) {
        router.push("/profile/me");
      } else {
        setError(describeGeneratedError(result.error));
      }
    } catch (err) {
      setError("An unexpected error occurred.");
    }
    setSaving(false);
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
    <div className="space-y-8">
      {/* Visual Identity Section */}
      <section className="rounded-2xl border border-border-default bg-surface-1 p-6 space-y-6 shadow-sm">
        <h2 className="font-heading text-lg font-bold text-foreground border-b border-border-default pb-3">
          Visual Branding
        </h2>
        <div className="space-y-6">
          <div className="space-y-2">
            <span className={LABEL_CLASS}>Cover Banner</span>
            <BannerUploader
              bannerUrl={profile.banner_url ?? null}
              onUploaded={(url) =>
                setProfile((prev) => (prev ? { ...prev, banner_url: url } : prev))
              }
            />
          </div>
          <div className="space-y-2">
            <span className={LABEL_CLASS}>Avatar Photo</span>
            <AvatarUploader
              avatarUrl={profile.avatar_url ?? null}
              displayName={profile.display_name}
              onUploaded={(url) => {
                setProfile((prev) => (prev ? { ...prev, avatar_url: url } : prev));
                window.dispatchEvent(new CustomEvent("auracles-avatar-updated", { detail: url }));
              }}
            />
          </div>
        </div>
      </section>

      {/* About Section */}
      <section className="rounded-2xl border border-border-default bg-surface-1 p-6 space-y-6 shadow-sm">
        <h2 className="font-heading text-lg font-bold text-foreground border-b border-border-default pb-3">
          About You
        </h2>
        <div className="space-y-4">
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
        </div>
      </section>

      {/* Location & Website Section */}
      <section className="rounded-2xl border border-border-default bg-surface-1 p-6 space-y-6 shadow-sm">
        <h2 className="font-heading text-lg font-bold text-foreground border-b border-border-default pb-3">
          Location & Contact
        </h2>
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
      </section>

      {/* Expertise & Links Section */}
      <section className="rounded-2xl border border-border-default bg-surface-1 p-6 space-y-6 shadow-sm">
        <h2 className="font-heading text-lg font-bold text-foreground border-b border-border-default pb-3">
          Expertise & Portfolio
        </h2>
        <div className="space-y-6">
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
              <Button onClick={addSpecialization} variant="secondary" className="flex items-center gap-1.5 px-4 shrink-0">
                <svg className="h-4 w-4 text-foreground-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
                </svg>
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
                <button
                  aria-label="Remove link"
                  onClick={() => setLinks(links.filter((_, i) => i !== index))}
                  type="button"
                  className="flex h-12 w-full sm:w-12 shrink-0 items-center justify-center rounded-xl border border-border-default bg-surface-1 text-foreground-muted hover:border-error/30 hover:bg-error/5 hover:text-error transition-all cursor-pointer"
                >
                  <svg className="h-5 w-5 sm:mr-0 mr-1.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                  <span className="sm:hidden text-sm font-semibold">Remove</span>
                </button>
              </div>
            ))}
            {links.length < 10 ? (
              <Button
                onClick={() => setLinks([...links, { label: "", url: "" }])}
                variant="secondary"
                className="w-full flex items-center justify-center gap-2"
              >
                <svg className="h-4 w-4 text-foreground-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
                </svg>
                Add link
              </Button>
            ) : null}
          </div>
        </div>
      </section>

      {/* Social Profiles Section */}
      <section className="rounded-2xl border border-border-default bg-surface-1 p-6 space-y-4 shadow-sm">
        <div className="border-b border-border-default pb-3">
          <h2 className="font-heading text-lg font-bold text-foreground">
            Social profiles
          </h2>
          <p className="mt-1 text-sm text-foreground-muted">
            Add your handles. Leave a field blank to hide that platform.
          </p>
        </div>
        <SocialLinksEditor onChange={setSocialLinks} value={socialLinks} />
      </section>

      {/* Featured Section */}
      <section className="rounded-2xl border border-border-default bg-surface-1 p-6 space-y-4 shadow-sm">
        <h2 className="font-heading text-lg font-bold text-foreground border-b border-border-default pb-3">
          Featured
        </h2>
        <FeaturedEditor
          frameworks={frameworkOptions}
          onChange={setFeatured}
          value={featured}
        />
      </section>

      {/* Experience History Section */}
      <section className="rounded-2xl border border-border-default bg-surface-1 p-6 space-y-4 shadow-sm">
        <h2 className="font-heading text-lg font-bold text-foreground border-b border-border-default pb-3">
          Experience History
        </h2>
        <ExperienceEditor onChange={setExperience} value={experience} />
      </section>

      {/* Academic History Section */}
      <section className="rounded-2xl border border-border-default bg-surface-1 p-6 space-y-4 shadow-sm">
        <h2 className="font-heading text-lg font-bold text-foreground border-b border-border-default pb-3">
          Academic History
        </h2>
        <EducationEditor onChange={setEducation} value={education} />
      </section>

      {/* Form Action Controls */}
      <div className="flex items-center gap-4 border-t border-border-default pt-5">
        <Button loading={saving} onClick={save} disabled={!canSave}>
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
