import re

with open("/Users/a0000/projects/auracles/frontend/src/components/modules/frameworks/framework-form.tsx", "r") as f:
    content = f.read()

# 1. Add Button import
content = content.replace(
    'import { ReactNode, useState } from "react";\n\nimport { allValid, isNonEmpty, isPositiveNumber } from "@/lib/forms/validators";',
    'import { ReactNode, useState } from "react";\n\nimport { Button } from "@/components/ui/button";\nimport { allValid, isNonEmpty, isPositiveNumber } from "@/lib/forms/validators";'
)

# 2. Replace the form return section
target_start = '  return (\n    <form className="grid gap-6" onSubmit={handleSubmit}>'
target_end = '    </form>\n  );\n}'

if target_start in content and target_end in content:
    idx_start = content.index(target_start)
    idx_end = content.index(target_end) + len(target_end)
    
    new_form = '''  return (
    <form className="space-y-8" onSubmit={handleSubmit}>
      {/* `display: contents` keeps the grid gap intact while the disabled
          fieldset cascades the locked state to every inner control. */}
      <fieldset className="contents" disabled={readOnly}>
        
        <section className="rounded-2xl border border-border-default bg-surface-2 p-5 sm:p-6 shadow-sm space-y-6">
          <h2 className="text-lg font-heading font-bold text-foreground border-b border-border-default pb-3">
            Basic Details
          </h2>
          <FormTextInput
            label="Framework Title"
            placeholder="e.g. Enterprise React Architecture Template"
            onChange={(value) => setForm((current) => ({ ...current, title: value }))}
            required
            value={form.title}
            helperText="A clear, specific title helps operators find exactly what they need."
          />
          
          <label className="block">
            <span className="mb-1.5 block text-sm font-semibold text-foreground">
              Description
            </span>
            <textarea
              placeholder="Describe what your framework includes, the problem it solves, and who it's for..."
              className="min-h-32 w-full rounded-xl border border-border-default bg-background px-4 py-3 text-sm text-foreground outline-none transition-all focus:border-accent focus:ring-0 placeholder:text-foreground-muted/50 resize-y"
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  description: event.target.value,
                }))
              }
              required
              value={form.description}
            />
          </label>

          <TagChipInput
            label="Tags"
            max={MAX_TAGS}
            onChange={(value) => setForm((current) => ({ ...current, tags: value }))}
            value={form.tags}
          />
        </section>

        <section className="rounded-2xl border border-border-default bg-surface-2 p-5 sm:p-6 shadow-sm space-y-6">
          <h2 className="text-lg font-heading font-bold text-foreground border-b border-border-default pb-3">
            Categorization
          </h2>
          <div className="grid gap-6 sm:grid-cols-2">
            <FormSelectInput
              label="Sector"
              onChange={(value) => setForm((current) => ({ ...current, sector: value }))}
              options={SECTOR_OPTIONS}
              required
              value={form.sector}
            />
            <FormSelectInput
              label="Industry"
              onChange={(value) =>
                setForm((current) => ({ ...current, industry: value }))
              }
              options={INDUSTRY_OPTIONS}
              required
              value={form.industry}
            />
            <FormSelectInput
              label="Function"
              onChange={(value) =>
                setForm((current) => ({ ...current, function: value }))
              }
              options={FUNCTION_OPTIONS}
              required
              value={form.function}
            />
            <FormSelectInput
              label="Category"
              onChange={(value) =>
                setForm((current) => ({ ...current, category: value }))
              }
              options={FRAMEWORK_CATEGORY_OPTIONS}
              required
              value={form.category}
            />
            <FormSelectInput
              label="Organization Size"
              onChange={(value) => setForm((current) => ({ ...current, orgSize: value }))}
              options={ORG_SIZE_OPTIONS}
              required
              value={form.orgSize}
            />
            <FormOptionalSelectInput
              label="Complexity"
              emptyLabel="Any complexity"
              onChange={(value) =>
                setForm((current) => ({ ...current, complexity: value }))
              }
              options={COMPLEXITY_OPTIONS}
              value={form.complexity}
            />
            <FormOptionalSelectInput
              label="Lifecycle Stage"
              emptyLabel="Any stage"
              onChange={(value) =>
                setForm((current) => ({ ...current, lifecycleStage: value }))
              }
              options={LIFECYCLE_STAGE_OPTIONS}
              value={form.lifecycleStage}
            />
            <FormOptionalSelectInput
              label="Jurisdiction"
              emptyLabel="Any jurisdiction"
              onChange={(value) =>
                setForm((current) => ({ ...current, jurisdiction: value }))
              }
              options={JURISDICTION_OPTIONS}
              value={form.jurisdiction}
            />
          </div>
        </section>

        <section className="rounded-2xl border border-border-default bg-surface-2 p-5 sm:p-6 shadow-sm space-y-6">
          <h2 className="text-lg font-heading font-bold text-foreground border-b border-border-default pb-3">
            Pricing & Licensing
          </h2>
          <div className="grid gap-6 sm:grid-cols-2">
            <label className="block">
              <span className="mb-1.5 block text-sm font-semibold text-foreground">
                Base Price
                <span aria-hidden="true" className="ml-1 text-accent">
                  *
                </span>
              </span>
              <div className="relative">
                <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-4 text-foreground-muted">
                  <span className="text-sm font-medium">$</span>
                </div>
                <input
                  type="text"
                  inputMode="decimal"
                  autoComplete="off"
                  placeholder="250.00"
                  className="min-h-12 w-full rounded-xl border border-border-default bg-background pl-8 pr-4 text-sm text-foreground outline-none transition-all focus:border-accent focus:ring-0 placeholder:text-foreground-muted/50"
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      price: sanitizePriceInput(event.target.value),
                    }))
                  }
                  required
                  value={form.price}
                />
                <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-4 text-foreground-muted">
                  <span className="text-xs uppercase">USD</span>
                </div>
              </div>
            </label>
            
            {form.licenseTypes.includes("organizational") ? (
              <label className="block">
                <span className="mb-1.5 block text-sm font-semibold text-foreground">
                  Organization price
                </span>
                <div className="relative">
                  <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-4 text-foreground-muted">
                    <span className="text-sm font-medium">$</span>
                  </div>
                  <input
                    type="text"
                    inputMode="decimal"
                    autoComplete="off"
                    placeholder="e.g. 500.00"
                    className="min-h-12 w-full rounded-xl border border-border-default bg-background pl-8 pr-4 text-sm text-foreground outline-none transition-all focus:border-accent focus:ring-0 placeholder:text-foreground-muted/50"
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        orgPrice: sanitizePriceInput(event.target.value),
                      }))
                    }
                    value={form.orgPrice}
                  />
                  <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-4 text-foreground-muted">
                    <span className="text-xs uppercase">USD</span>
                  </div>
                </div>
                <span className="mt-1.5 block text-xs text-foreground-muted">
                  Leave blank to charge the same as the single-user price.
                </span>
              </label>
            ) : null}
          </div>

          <fieldset className="block">
            <legend className="mb-1.5 block text-sm font-semibold text-foreground">
              License types
              <span aria-hidden="true" className="ml-1 text-accent">
                *
              </span>
            </legend>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {LICENSE_TYPE_OPTIONS.map((option) => {
                const checked = form.licenseTypes.includes(option.value);
                return (
                  <label
                    key={option.value}
                    className={`flex min-h-12 cursor-pointer items-center gap-2 rounded-xl border px-4 text-sm font-medium transition-all ${
                      checked
                        ? "border-accent bg-accent/10 text-foreground"
                        : "border-border-default bg-background text-foreground-muted hover:border-accent/50"
                    }`}
                  >
                    <input
                      type="checkbox"
                      className="h-4 w-4 shrink-0 accent-accent"
                      checked={checked}
                      onChange={() => toggleLicenseType(option.value)}
                    />
                    {option.label}
                  </label>
                );
              })}
            </div>
            <span className="mt-1.5 block text-xs text-foreground-muted">
              Choose at least one tier operators can license. Pricing scales per tier
              at checkout.
            </span>
          </fieldset>
        </section>

        {prefill?.fileKeys?.length ? (
          <section className="rounded-2xl border border-border-default bg-surface-2 p-5 sm:p-6 shadow-sm space-y-4">
            <h2 className="text-lg font-heading font-bold text-foreground border-b border-border-default pb-3">
              Source files
            </h2>
            <ul className="mt-2 grid gap-1 text-xs text-foreground-muted">
              {prefill.fileKeys.map((fileKey) => (
                <li className="truncate" key={fileKey}>
                  {fileKey}
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {error ? (
          <div className="rounded-xl bg-error/10 p-3 border border-error/20 flex items-center gap-2 text-sm text-error">
            <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            {error}
          </div>
        ) : null}
      </fieldset>

      <div className="mt-4 pt-6 border-t border-border-default flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-3">
          {leftActions}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {readOnly ? null : (
            <Button
              disabled={saving || !canSubmit}
              loading={saving}
              type="submit"
              variant={
                framework && (framework.status === "draft" || framework.status === "pipeline_passed" || framework.status === "pipeline_failed")
                  ? "secondary"
                  : "primary"
              }
            >
              {saving ? "Saving changes..." : submitLabel}
            </Button>
          )}
          {children}
        </div>
      </div>
    </form>
  );
}'''
    content = content[:idx_start] + new_form + content[idx_end:]
    
    with open("/Users/a0000/projects/auracles/frontend/src/components/modules/frameworks/framework-form.tsx", "w") as f:
        f.write(content)
    print("Successfully patched form")
else:
    print("Could not find target strings")

