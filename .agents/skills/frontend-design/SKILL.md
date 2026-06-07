---
name: frontend-design
description: Auracles design system. Trillo-inspired dual-mode (light/dark), warm orange accent, bento-box shadows, solid black/white buttons.
---

# Protocol: Auracles UI Design System

## 1. Source of Truth

This skill mirrors `docs/auracles-brand-book.pdf` (Brand Book v1.0). If the brand book and this skill disagree, the brand book wins — propose an update to the skill, do not silently deviate.

The interface must consistently feel:
**Expert. Institutional. Precise. Warm. Trusted.**

Communicated through: Trust, Professionalism, Structure, Clarity, Intelligence, Permanence.

## 2. Absolute Negative Constraints (Banned Elements)

- DO NOT use gradients or 3D glassmorphism.
- DO NOT use heavy shadows (`shadow-md`, `shadow-lg`, `shadow-xl`). Use borders for separation; subtle shadows only.
- DO NOT use saturated, non-brand colors as decorative accents (only the warm orange Accent and the four semantic colors are allowed).
- DO NOT use `rounded-full` (pill shapes) for cards, containers, or primary buttons. Cards use `8px` radius.
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

### 5.2 Cards
- Background: Surface Level 2 (`#F1EDE6` light / `#111111` dark)
- Border: `1px solid` Surface Level 3 (`#EAE5DC` light / `#1A1A1A` dark)
- Border-radius: `8px`
- Hover: border darkens one step; background bumps to Surface Level 3
- No box-shadow. Elevation via background + border shift only.

### 5.3 Buttons

**Primary** (Solid Black/White):
- Background: `#0025CC`
- Text: `#FFFFFF`
- Border-radius: `6px`
- Hover: background `#0020B0` (10% darker)
- Active: `transform: scale(0.98)`
- No shadow

**Secondary**:
- Background: transparent
- Border: `1px solid` (Surface Level 3)
- Text: primary text color
- Hover: background = Surface Level 1

**Destructive**:
- Background: transparent
- Border: `1px solid #DC2626`
- Text: `#DC2626`
- Hover: background = `#DC2626` at 10% opacity

### 5.4 Inputs & Forms
- Background: Surface Level 2
- Border: `1px solid` Surface Level 3
- Focus border: `1px solid var(--accent)` (Accent ring)
- Border-radius: `6px`

### 5.5 Tags & Status Badges
- Small (`text-xs`), uppercase, `letter-spacing: 0.05em`
- Border-radius: `4px` (not full pill)
- Use semantic colors at low opacity for background, full opacity for text:
  - Success badge: `bg-[#16A34A]/10`, `text-[#16A34A]`, `border-[#16A34A]/30`
  - Warning badge: `bg-[#F59E0B]/10`, `text-[#F59E0B]`, `border-[#F59E0B]/30`
  - Error badge: `bg-[#DC2626]/10`, `text-[#DC2626]`, `border-[#DC2626]/30`
  - Info badge: `bg-[#2563EB]/10`, `text-[#2563EB]`, `border-[#2563EB]/30`

### 5.6 Dividers
- `border-bottom: 1px solid` Surface Level 3 — never raw `<hr>` defaults

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
