---
name: frontend-design
description: Auracles design system. Trillo-inspired dual-mode (light/dark), warm orange accent, bento-box shadows, solid black/white buttons.
---

# Protocol: Auracles UI Design System

## 1. Source of Truth & Core Philosophy

This skill mirrors `docs/auracles-brand-book.pdf` (Brand Book v1.0). If the brand book and this skill disagree, the brand book wins — propose an update to the skill, do not silently deviate.

The interface must consistently feel:
**Expert. Institutional. Precise. Warm. Trusted.**

Communicated through: Trust, Professionalism, Structure, Clarity, Intelligence, Permanence.

### Core Layout Paradigm: The Bento Box Grid
All dashboard pages, search feeds, settings interfaces, and details screens must be built using a **Bento Box layout**.
- **Compartmentalization**: Group information into clean, modular containers (the "bento boxes") using `rounded-2xl` corners, `bg-surface-1`, a standard `border-border-default` border, and `shadow-sm` or `shadow-bento`.
- **Structured Grid Systems**: Arrange these modules side-by-side or stacked using CSS Grid/Flexbox rather than creating plain flat layouts. This establishes clear visual hierarchy and keeps the page feeling structured and professional.
- **Surface Layering**: Nested items, inner listings, or interactive control sections inside a bento block should drop one level lower in elevation using `bg-surface-2` (Surface Level 2) and `rounded-xl` corners.

## 2. Absolute Negative Constraints (Banned Elements)

- DO NOT use gradients or 3D glassmorphism.
- DO NOT use heavy shadows (`shadow-md`, `shadow-lg`, `shadow-xl`). Use borders for separation; subtle shadows only.
- DO NOT use saturated, non-brand colors as decorative accents (only the warm orange Accent and the four semantic colors are allowed).
- DO NOT use `rounded-full` (pill shapes) for cards, containers, or primary buttons (except for status badges, which use `rounded-badge` / `999px` pill). Main cards/containers use `rounded-2xl` (`16px` radius) and nested items/inner interactive controls use `rounded-xl` (`12px` radius).
- DO NOT mix in additional typefaces. Inter Rounded and Poppins only.
- DO NOT use emojis in code, markup, headings, or alt text. Use Phosphor Icons or Radix UI Icons.
- DO NOT use marketing jargon, buzzwords, hyperbolic claims, or corporate clichés.
  - Bad: "Leverage next-generation governance solutions to accelerate transformational outcomes."
  - Good: "Purchase a governance framework and begin implementation immediately."
- DO NOT use generic placeholder content ("Lorem Ipsum", "John Doe", "Acme Corp"). Use realistic Auracles context.

## 3. Typographic Architecture

Two typefaces only.

- **Headers** (page titles, section headers, dashboard metrics, marketplace titles):
  `font-family: 'Inter Rounded', 'Inter', sans-serif`
  Weights: 600, 700, 800
  Large, confident, intentional. Tight tracking on display sizes (`letter-spacing: -0.02em`).

- **Body** (paragraphs, descriptions, forms, marketplace content, metadata):
  `font-family: 'Poppins', sans-serif`
  Weights: 400, 500, 600
  `line-height: 1.6`. High readability on both light and dark surfaces.

Minimal font-weight variation. Hierarchy through size and color.

## 4. Color System

Auracles supports **both light and dark mode**. Every component must render correctly in both. Default to the user's system preference.

### 4.1 Light Mode (default)

| Token | Hex | Use |
|-------|-----|-----|
| Background | `#FFFFFB` | Page/app background (warm off-white) |
| Surface Level 1 | `#F8F6F2` | First elevation: navigation, sidebars |
| Surface Level 2 | `#F1EDE6` | Second elevation: cards, modals |
| Surface Level 3 | `#EAE5DC` | Third elevation: nested panels, raised inputs |

### 4.2 Dark Mode

| Token | Hex | Use |
|-------|-----|-----|
| Background | `#000000` | Page/app background |
| Surface Level 1 | `#0A0A0A` | First elevation: navigation, sidebars |
| Surface Level 2 | `#111111` | Second elevation: cards, modals |
| Surface Level 3 | `#1A1A1A` | Third elevation: nested panels, raised inputs |

### 4.3 Primary Accent — Warm Orange

| Accent     | `#C74634` |

**Use Accent for:**
- Primary buttons
- Call-to-action elements
- Active navigation states
- Links
- Ratings
- Marketplace actions
- Selected states
- Progress indicators

Accent is the only saturated color allowed for decoration or emphasis.

### 4.4 Semantic Colors

| Token | Hex | Use |
|-------|-----|-----|
| Success | `#16A34A` | Confirmation badges, valid states |
| Warning | `#F59E0B` | Caution states, pending actions |
| Error | `#DC2626` | Destructive actions, failure states |
| Information | `#2563EB` | Neutral notices, informational badges |

Use these only for status semantics. Never as decorative accents.

## 5. Component Specifications

### 5.1 Layout
- **Mobile-first always.** Base classes target mobile, `sm:`/`md:`/`lg:` enhance up.
- 12-column grid on `md:` and up. Single column on mobile.
- Max-width `1440px` outer container, content width `1280px`.
- Section spacing: mobile `py-10`, scale to `md:py-16` and `lg:py-24` between major sections.
- Navigation: bottom drawer / hamburger sheet on mobile, persistent left sidebar on `md:` and up.
- Touch targets minimum `44px × 44px` on all interactive elements.
- Test every layout at 375px width (iPhone SE) before committing.
- **Bento Surface & Shell Inheritance**: Under the `AuthenticatedAppShell` Bento wrapper (which sets the outer container to `bg-surface-1 md:rounded-tl-[32px]`), child pages and views must inherit this container. Individual child pages must NOT set their own `bg-background` or `min-h-screen`, as doing so overrides the Bento container layout and background consistency.

### 5.2 Bento Box Cards & Panels
- **Main Cards/Containers**:
  - Background: Surface Level 1 (`bg-surface-1`, which is `#F8F6F2` light / `#0A0A0A` dark)
  - Border: `1px solid border-border-default` (or Surface Level 2)
  - Border-radius: `rounded-2xl` (`16px` or `20px` card token)
  - Shadow: Subtle shadow (`shadow-sm` or `shadow-bento`)
  - Hover: border can highlight with accent (`hover:border-accent/30` or `hover:border-accent/50`) and shadow can darken slightly.
- **Nested Cards, Lists, & Inner Panels**:
  - Background: Surface Level 2 (`bg-surface-2`, which is `#F1EDE6` light / `#111111` dark)
  - Border: `1px solid` Surface Level 3 or standard border
  - Border-radius: `rounded-xl` (`12px`)
  - Hover: background can shift to `bg-surface-1` or border can darken.

### 5.3 Buttons
- **Touch target / min-height**: Always `min-h-12` (48px) for mobile accessibility.

**Primary** (Solid Contrast):
- Background: `bg-foreground` (Black in light mode, Warm Off-White/White in dark mode)
- Text: `text-background` (Warm Off-White/White in light mode, Black in dark mode)
- Border-radius: `rounded-xl` (`12px`)
- Hover: background `bg-foreground/90`
- Active: `transform: scale(0.98)`
- No box shadow

**Secondary**:
- Background: `bg-surface-1`
- Border: `1px solid border-border-default`
- Text: primary text color
- Border-radius: `rounded-xl` (`12px`)
- Hover: background `bg-surface-2`

**Destructive**:
- Background: transparent
- Border: `1px solid #DC2626` (or `border-error/50`)
- Text: `#DC2626` (or `text-error`)
- Border-radius: `rounded-xl` (`12px`)
- Hover: background = `#DC2626` at 10% opacity (or `hover:bg-error/10`)

### 5.4 Inputs & Forms
- Height: Minimum `min-h-12` (48px height for high touch accessibility)
- Background: `bg-background` (#FFFFFB light / #000000 dark) or `bg-surface-1` depending on nested block context
- Border: `1px solid border-border-default`
- Focus border: `focus-visible:ring-2 focus-visible:ring-accent` (Accent ring)
- Border-radius: `rounded-xl` (`12px`)

### 5.5 Tags & Status Badges
- Small (`text-xs`), uppercase, `letter-spacing: 0.05em`
- Border-radius: `rounded-badge` (`999px` pill badge style)
- Use semantic colors at low opacity for background, full opacity for text:
  - Success badge: `bg-[#16A34A]/10`, `text-[#16A34A]`, `border-[#16A34A]/30`
  - Warning badge: `bg-[#F59E0B]/10`, `text-[#F59E0B]`, `border-[#F59E0B]/30`
  - Error badge: `bg-[#DC2626]/10`, `text-[#DC2626]`, `border-[#DC2626]/30`
  - Info badge: `bg-[#2563EB]/10`, `text-[#2563EB]`, `border-[#2563EB]/30`

### 5.6 Dividers
- `border-bottom: 1px solid` Surface Level 3 (or standard border `border-border-default`) — never raw `<hr>` defaults

### 5.7 Trust Signals (always visible per brand book)
- Verification badges, reputation scores, attestation status, contributor credentials must be present without requiring extra navigation
- Use Accent or Success for positive trust signals; muted body text for neutral

### 5.8 Split-View Workspace (Projects)
- Resizable panels
- Surface Level 1 background, Surface Level 3 panel border
- Minimal visual distraction

## 6. Voice & Tone

When writing UI copy:
- **Clear**: communicate ideas simply and directly
- **Concise**: deliver information efficiently
- **Operational**: focus on practical implementation and real-world outcomes
- **Professional**: credible while approachable

Examples:
- ✓ "Frameworks are updated as industry requirements evolve."
- ✗ "Dynamic synergy-driven documentation continuously optimizes operational excellence."

## 7. Mode Implementation Notes

Light + dark mode wiring:
- Tailwind `darkMode: 'class'` on the config
- Apply `class="dark"` to `<html>` based on system preference + user override
- All tokens exposed as CSS variables under `:root` and `.dark` so utility classes work in both modes
- Components reference semantic class names (`bg-surface-1`, `text-foreground`) rather than literal hex
