"use client";

/**
 * Admin calibration-fixture management.
 *
 * Lets a platform admin create calibration fixtures, upload and scan their
 * review artifacts, and set the per-dimension answer key that trials grade
 * against. A fixture is "startable" once it has at least one virus-scanned
 * (clean) artifact and a complete answer key.
 */

import { useCallback, useEffect, useState } from "react";

import {
  adminConfirmFixtureArtifactV1AdminOrgAttestorApplicationsCalibrationFixturesFrameworkIdArtifactsConfirmPost as confirmFixtureArtifact,
  adminCreateCalibrationFixtureV1AdminOrgAttestorApplicationsCalibrationFixturesPost as createFixture,
  adminCreateFixtureArtifactUploadUrlV1AdminOrgAttestorApplicationsCalibrationFixturesFrameworkIdArtifactsUploadUrlPost as createFixtureArtifactUploadUrl,
  adminDeleteFixtureArtifactV1AdminOrgAttestorApplicationsCalibrationFixturesFrameworkIdArtifactsArtifactIdDelete as deleteFixtureArtifact,
  adminListCalibrationFixturesV1AdminOrgAttestorApplicationsCalibrationFixturesGet as listFixtures,
  adminListFixtureArtifactsV1AdminOrgAttestorApplicationsCalibrationFixturesFrameworkIdArtifactsGet as listFixtureArtifacts,
  adminListTrialAnswerKeysV1AdminOrgAttestorApplicationsCalibrationFixturesFrameworkIdAnswerKeysGet as listAnswerKeys,
  adminUpsertTrialAnswerKeyV1AdminOrgAttestorApplicationsCalibrationFixturesFrameworkIdAnswerKeyPut as upsertAnswerKey,
} from "@/lib/generated/sdk.gen";
import type {
  CalibrationFixtureItem,
  FixtureArtifactItem,
  TrialAnswerKeyItem,
} from "@/lib/generated/types.gen";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

const REVIEW_TYPES = ["quality", "compliance", "expert", "provenance"] as const;

/** Render the scan state as a small coloured chip. */
function ScanChip({ status }: { status: string }) {
  const tone =
    status === "clean"
      ? "bg-success/10 text-success"
      : status === "infected"
        ? "bg-error/10 text-error"
        : "bg-surface-3 text-foreground-muted";
  return (
    <span className={`rounded-badge px-2 py-0.5 text-xs font-semibold uppercase tracking-[0.05em] ${tone}`}>
      {status}
    </span>
  );
}

/** Per-fixture detail: artifacts + answer keys, loaded on expand. */
function FixtureDetail({ frameworkId }: { frameworkId: string }) {
  const [artifacts, setArtifacts] = useState<FixtureArtifactItem[]>([]);
  const [keys, setKeys] = useState<TrialAnswerKeyItem[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const headers = getAccessTokenHeaders();
    const [artRes, keyRes] = await Promise.all([
      listFixtureArtifacts({ path: { framework_id: frameworkId }, headers }),
      listAnswerKeys({ path: { framework_id: frameworkId }, headers }),
    ]);
    if (artRes.data) setArtifacts(artRes.data.artifacts);
    if (keyRes.data) setKeys(keyRes.data.rows);
  }, [frameworkId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function handleUpload() {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const headers = getAccessTokenHeaders();
      const urlRes = await createFixtureArtifactUploadUrl({
        path: { framework_id: frameworkId },
        body: {
          filename: file.name,
          mime_type: file.type || "application/octet-stream",
          file_size: file.size,
        },
        headers,
      });
      if (urlRes.error || !urlRes.data) {
        setError(describeGeneratedError(urlRes.error));
        return;
      }
      const form = new FormData();
      for (const [k, v] of Object.entries(urlRes.data.fields)) {
        form.append(k, String(v));
      }
      form.append("file", file);
      const put = await fetch(urlRes.data.upload_url, { method: "POST", body: form });
      if (!put.ok) {
        setError("The upload could not be completed. Try again.");
        return;
      }
      const confirm = await confirmFixtureArtifact({
        path: { framework_id: frameworkId },
        body: { artifact_id: urlRes.data.artifact_id },
        headers,
      });
      if (confirm.error) {
        setError(describeGeneratedError(confirm.error));
        return;
      }
      setFile(null);
      await reload();
    } catch {
      setError("An unexpected error occurred.");
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(artifactId: string) {
    setBusy(true);
    setError(null);
    try {
      await deleteFixtureArtifact({
        path: { framework_id: frameworkId, artifact_id: artifactId },
        headers: getAccessTokenHeaders(),
      });
      await reload();
    } finally {
      setBusy(false);
    }
  }

  /**
   * Save one answer-key row and update it in place. Each row tracks its own
   * saving state, so one save never disables the other rows or the Upload
   * button (which keeps `busy` to itself).
   *
   * @returns An error message for the row, or null when saved.
   */
  async function handleKeySave(
    dimensionId: string,
    expected: number,
    tolerance: number,
  ): Promise<string | null> {
    try {
      const res = await upsertAnswerKey({
        path: { framework_id: frameworkId },
        body: {
          dimension_id: dimensionId,
          expected_score: expected,
          tolerance,
        },
        headers: getAccessTokenHeaders(),
      });
      if (res.error) {
        return describeGeneratedError(res.error);
      }
    } catch (caught) {
      return describeGeneratedError(caught);
    }
    // The endpoint answers 204, so reflect the stored values locally; the
    // readiness line reads these rows.
    setKeys((current) =>
      current.map((key) =>
        key.dimension_id === dimensionId
          ? { ...key, expected_score: expected, tolerance }
          : key,
      ),
    );
    return null;
  }

  const hasClean = artifacts.some((a) => a.scan_status === "clean");
  const keysComplete = keys.length > 0 && keys.every((k) => k.expected_score != null);

  return (
    <div className="mt-4 space-y-6 border-t border-border-default pt-4">
      {error && <p className="text-sm text-error">{error}</p>}

      <p className="text-sm font-semibold text-foreground">
        {hasClean && keysComplete ? (
          <span className="text-success">Ready to assign in a trial.</span>
        ) : (
          <span className="text-foreground-muted">
            Needs {hasClean ? "" : "a scanned artifact"}
            {!hasClean && !keysComplete ? " and " : ""}
            {keysComplete ? "" : "a complete answer key"}.
          </span>
        )}
      </p>

      <div>
        <h4 className="text-sm font-bold text-foreground">Artifacts</h4>
        <ul className="mt-2 space-y-2">
          {artifacts.length === 0 && (
            <li className="text-sm text-foreground-muted">No artifacts yet.</li>
          )}
          {artifacts.map((a) => (
            <li
              key={a.id}
              className="flex items-center justify-between gap-3 rounded-xl border border-border-default bg-surface-1 p-3"
            >
              <span className="flex items-center gap-2 text-sm text-foreground">
                {a.name} <ScanChip status={a.scan_status} />
              </span>
              <button
                type="button"
                className="min-h-11 text-sm font-semibold text-error underline-offset-4 hover:underline"
                disabled={busy}
                onClick={() => handleDelete(a.id)}
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
        <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-center">
          <input
            aria-label="Fixture artifact file"
            type="file"
            accept=".pdf,image/*"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            className="block w-full text-sm text-foreground-muted file:mr-4 file:min-h-11 file:cursor-pointer file:rounded-xl file:border-0 file:bg-foreground file:px-4 file:py-2 file:text-sm file:font-semibold file:text-background"
          />
          <Button type="button" onClick={handleUpload} disabled={busy || !file} loading={busy}>
            Upload
          </Button>
        </div>
      </div>

      <div>
        <h4 className="text-sm font-bold text-foreground">Answer key</h4>
        <ul className="mt-2 space-y-2">
          {keys.map((k) => (
            <AnswerKeyRow key={k.dimension_id} row={k} onSave={handleKeySave} />
          ))}
        </ul>
      </div>
    </div>
  );
}

/** One editable answer-key row for a rubric dimension. */
function AnswerKeyRow({
  row,
  onSave,
}: {
  row: TrialAnswerKeyItem;
  onSave: (dimensionId: string, expected: number, tolerance: number) => Promise<string | null>;
}) {
  const [expected, setExpected] = useState(row.expected_score ?? 3);
  const [tolerance, setTolerance] = useState(row.tolerance ?? 0);
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);

  /** Save this row and show the outcome beside its button. */
  async function save() {
    setSaving(true);
    setResult(null);
    const failure = await onSave(row.dimension_id, expected, tolerance);
    setSaving(false);
    setResult(failure ? { ok: false, message: `Not saved: ${failure}` } : { ok: true, message: "Saved" });
  }
  return (
    <li className="grid gap-2 rounded-xl border border-border-default bg-surface-1 p-3 sm:grid-cols-[1fr_auto_auto_minmax(9rem,auto)] sm:items-center">
      <span className="text-sm text-foreground">{row.label}</span>
      <label className="text-xs text-foreground-muted">
        Score
        <select
          aria-label={`${row.label} expected score`}
          value={expected}
          onChange={(e) => {
            setExpected(Number(e.target.value));
            setResult(null);
          }}
          className="ml-2 min-h-11 rounded-xl border border-border-default bg-background px-3 text-sm text-foreground"
        >
          {[1, 2, 3, 4, 5].map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </label>
      <label className="text-xs text-foreground-muted">
        Tolerance
        <select
          aria-label={`${row.label} tolerance`}
          value={tolerance}
          onChange={(e) => {
            setTolerance(Number(e.target.value));
            setResult(null);
          }}
          className="ml-2 min-h-11 rounded-xl border border-border-default bg-background px-3 text-sm text-foreground"
        >
          {[0, 1, 2, 3, 4].map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </label>
      <div className="flex items-center gap-3">
        <Button
          type="button"
          variant="secondary"
          disabled={saving}
          loading={saving}
          onClick={() => void save()}
        >
          Save
        </Button>
        <span
          aria-live="polite"
          className={`text-xs font-semibold ${result?.ok ? "text-success" : "text-error"}`}
        >
          {result?.message ?? ""}
        </span>
      </div>
    </li>
  );
}

/** Top-level calibration-fixtures admin panel. */
export function AdminCalibrationFixturesPanel() {
  const [fixtures, setFixtures] = useState<CalibrationFixtureItem[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [reviewType, setReviewType] = useState<(typeof REVIEW_TYPES)[number]>("quality");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const res = await listFixtures({ headers: getAccessTokenHeaders() });
    if (res.data) setFixtures(res.data.fixtures);
  }, []);

  useEffect(() => {
    configureBrowserClient();
    void reload();
  }, [reload]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await createFixture({
        body: { title, description, review_type: reviewType },
        headers: getAccessTokenHeaders(),
      });
      if (res.error) {
        setError(describeGeneratedError(res.error));
        return;
      }
      setTitle("");
      setDescription("");
      await reload();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-8">
      <header>
        <h2 className="font-heading text-2xl font-bold text-foreground">
          Calibration Fixtures
        </h2>
        <p className="mt-1 text-sm text-foreground-muted">
          Test frameworks nominees attest during the calibration trial. Add
          artifacts and a complete answer key before assigning one in a trial.
        </p>
      </header>

      <form
        onSubmit={handleCreate}
        className="space-y-4 rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm"
      >
        <h3 className="font-heading text-base font-bold text-foreground">New fixture</h3>
        {error && <p className="text-sm text-error">{error}</p>}
        <Input
          aria-label="Fixture title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Title"
          required
        />
        <Textarea
          aria-label="Fixture description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Description"
          required
        />
        <Select
          aria-label="Review type"
          value={reviewType}
          onChange={(e) => setReviewType(e.target.value as (typeof REVIEW_TYPES)[number])}
        >
          {REVIEW_TYPES.map((rt) => (
            <option key={rt} value={rt}>
              {rt}
            </option>
          ))}
        </Select>
        <Button type="submit" disabled={busy} loading={busy}>
          Create fixture
        </Button>
      </form>

      <ul className="space-y-3">
        {fixtures.length === 0 && (
          <li className="text-sm text-foreground-muted">No fixtures yet.</li>
        )}
        {fixtures.map((f) => (
          <li key={f.id} className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
            <button
              type="button"
              className="flex w-full items-center justify-between gap-3 text-left"
              onClick={() => setExpanded(expanded === f.id ? null : f.id)}
            >
              <span className="font-semibold text-foreground">{f.title}</span>
              <span className="text-xs uppercase tracking-wide text-foreground-muted">
                {f.review_type}
              </span>
            </button>
            {expanded === f.id && <FixtureDetail frameworkId={f.id} />}
          </li>
        ))}
      </ul>
    </div>
  );
}
