"use client";

import React, { useEffect, useState } from "react";
import { 
  listAttestationAnnotations,
  createAttestationAnnotation,
  deleteAttestationAnnotation
} from "@/lib/generated/sdk.gen";
import type { AnnotationResponse, AnnotationCreateRequest } from "@/lib/generated/types.gen";
import { getAccessTokenHeaders } from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { TrashIcon } from "@radix-ui/react-icons";

export interface AnnotationsPanelProps {
  attestationId: string;
  canWrite: boolean;
}

const ANNOTATION_TYPES = [
  { value: "endorsement", label: "Endorsement" },
  { value: "concern", label: "Concern" },
  { value: "jurisdictional_caveat", label: "Jurisdictional Caveat" },
  { value: "revision_recommended", label: "Revision Recommended" }
];

export function AnnotationsPanel({ attestationId, canWrite }: AnnotationsPanelProps) {
  const [annotations, setAnnotations] = useState<AnnotationResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Form State
  const [isAdding, setIsAdding] = useState(false);
  const [newType, setNewType] = useState<AnnotationCreateRequest["annotation_type"]>("concern");
  const [newLocation, setNewLocation] = useState("");
  const [newExcerpt, setNewExcerpt] = useState("");
  const [newComment, setNewComment] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const fetchAnnotations = async () => {
    try {
      const res = await listAttestationAnnotations({
        path: { attestation_id: attestationId },
        headers: getAccessTokenHeaders()
      });
      if (res.error) throw new Error("Failed to load annotations");
      setAnnotations(res.data);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAnnotations();
  }, [attestationId]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newLocation || !newComment) return;

    setSubmitting(true);
    try {
      const res = await createAttestationAnnotation({
        path: { attestation_id: attestationId },
        body: {
          annotation_type: newType,
          location_label: newLocation,
          quoted_excerpt: newExcerpt || null,
          comment: newComment,
          artifact_id: null
        },
        headers: getAccessTokenHeaders()
      });
      if (res.error) throw new Error("Failed to add annotation");
      
      await fetchAnnotations();
      
      // Reset form
      setNewLocation("");
      setNewExcerpt("");
      setNewComment("");
      setIsAdding(false);
    } catch (err: any) {
      alert(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (annotationId: string) => {
    if (!confirm("Are you sure you want to delete this annotation?")) return;
    try {
      const res = await deleteAttestationAnnotation({
        path: {
          attestation_id: attestationId,
          annotation_id: annotationId
        },
        headers: getAccessTokenHeaders()
      });
      if (res.error) throw new Error("Failed to delete annotation");
      setAnnotations((prev) => prev.filter((a) => a.id !== annotationId));
    } catch (err: any) {
      alert(err.message);
    }
  };

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between border-b border-border-default pb-4">
        <div>
          <h2 className="text-xl font-semibold text-foreground">
            Annotations
          </h2>
          <p className="mt-1 text-sm text-foreground-muted">
            Clause-level notes and findings on the framework content.
          </p>
        </div>
        {canWrite && !isAdding && (
          <Button onClick={() => setIsAdding(true)}>
            Add Annotation
          </Button>
        )}
      </div>

      {loading ? (
        <div className="flex justify-center p-8"><Spinner className="h-6 w-6 text-accent" /></div>
      ) : error ? (
        <div className="p-4 text-sm text-error bg-error/5 rounded-xl border border-error/50">
          {error}
        </div>
      ) : (
        <div className="space-y-6">
          {isAdding && canWrite && (
            <div className="rounded-xl border border-border-default bg-surface-elevated p-6">
              <h3 className="text-sm font-semibold mb-4 text-foreground">New Annotation</h3>
              <form onSubmit={handleSubmit} className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-foreground mb-1">Type</label>
                    <Select value={newType} onChange={(e) => setNewType(e.target.value as any)}>
                      {ANNOTATION_TYPES.map((t) => (
                        <option key={t.value} value={t.value}>{t.label}</option>
                      ))}
                    </Select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-foreground mb-1">Location Label *</label>
                    <Input 
                      placeholder="e.g. Section 2.1, Article 4" 
                      value={newLocation} 
                      onChange={(e) => setNewLocation(e.target.value)} 
                      required 
                    />
                  </div>
                </div>
                
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">Quoted Excerpt (Optional)</label>
                  <Textarea 
                    placeholder="Text quoted from the framework..." 
                    value={newExcerpt} 
                    onChange={(e) => setNewExcerpt(e.target.value)}
                    className="min-h-[80px]"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">Comment *</label>
                  <Textarea 
                    placeholder="Your finding or suggestion..." 
                    value={newComment} 
                    onChange={(e) => setNewComment(e.target.value)}
                    required
                    className="min-h-[100px]"
                  />
                </div>

                <div className="flex justify-end gap-3 pt-2">
                  <Button type="button" variant="secondary" onClick={() => setIsAdding(false)}>
                    Cancel
                  </Button>
                  <Button type="submit" disabled={submitting || !newLocation || !newComment}>
                    {submitting ? "Saving..." : "Save Annotation"}
                  </Button>
                </div>
              </form>
            </div>
          )}

          {annotations.length === 0 && !isAdding ? (
            <div className="rounded-xl border border-dashed border-border-default p-8 text-center text-foreground-muted text-sm">
              No annotations added yet.
            </div>
          ) : (
            <div className="space-y-4">
              {annotations.map((ann) => (
                <div key={ann.id} className="rounded-xl border border-border-default bg-background p-6">
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="flex items-center gap-2 mb-2">
                        <span className="inline-flex items-center rounded-md bg-surface-elevated px-2 py-1 text-xs font-medium text-foreground uppercase border border-border-default">
                          {ann.annotation_type.replace("_", " ")}
                        </span>
                        <span className="text-sm font-semibold text-foreground">
                          {ann.location_label}
                        </span>
                      </div>
                      
                      {ann.quoted_excerpt && (
                        <blockquote className="mt-3 border-l-4 border-accent pl-4 text-sm italic text-foreground-muted mb-4 bg-surface-elevated/50 p-2 rounded-r-md">
                          "{ann.quoted_excerpt}"
                        </blockquote>
                      )}

                      <p className="text-sm text-foreground whitespace-pre-wrap mt-3">
                        {ann.comment}
                      </p>
                    </div>
                    {canWrite && (
                      <button 
                        onClick={() => handleDelete(ann.id)}
                        className="text-foreground-muted hover:text-error transition-colors p-2 rounded-md hover:bg-error/5"
                        aria-label="Delete annotation"
                      >
                        <TrashIcon className="h-4 w-4" />
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
