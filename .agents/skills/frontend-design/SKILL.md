---
name: auracles-ui
description: Auracles design system. Dark grayscale, institutional, no bright colors, no gradients. Inter Rounded headers, Poppins body, borders not shadows.
---

# Protocol: Auracles UI Design System

## 1. Protocol Overview

Auracles is a professional knowledge marketplace. The interface must feel:
**Professional. Institutional. Architectural. Trustworthy. Premium. Technical.**

Reference feel: GitHub + Linear + Notion Template Gallery — but for professional intellectual property on a dark canvas.

This protocol enforces the Auracles Visual Design System exactly as defined in `docs/auracles-full-spec.md`. Do not deviate from the palette, typography, or component rules below.

## 2. Absolute Negative Constraints (Banned Elements)

- DO NOT use bright colors — no blue, green, red, or any saturated color on large surfaces.
- DO NOT use gradients anywhere.
- DO NOT use glassmorphism or frosted-glass effects.
- DO NOT use heavy shadows (`shadow-md`, `shadow-lg`, `shadow-xl`). Use borders for separation, not shadows.
- DO NOT use visual clutter — every element earns its place.
- DO NOT use `rounded-full` (pill shapes) for cards, containers, or primary buttons. Cards use `8px` radius.
- DO NOT use Roboto or generic system UI fonts. Use Inter Rounded and Poppins as specified.
- DO NOT use emojis in code, markup, headings, or alt text. Use Phosphor Icons or Radix UI Icons.
- DO NOT use generic placeholder content ("Lorem Ipsum", "John Doe", "Acme Corp"). Use realistic Auracles context (framework names, contributor names, industry terms).
- DO NOT use AI copywriting clichés: "Elevate", "Seamless", "Unleash", "Next-Gen", "Delve". Write plain, specific language.

## 3. Typographic Architecture

Auracles uses two typefaces only. No mixing in additional fonts.

- **Headers (page titles, section headers, dashboard metrics, marketplace titles):**
  `font-family: 'Inter Rounded', 'Inter', sans-serif`
  Weights: 600, 700, 800
  Large, confident headings. Tight tracking (`letter-spacing: -0.02em`) on display sizes.

- **Body (paragraphs, descriptions, forms, metadata, UI labels):**
  `font-family: 'Poppins', sans-serif`
  Weights: 400, 500, 600
  High readability on dark surfaces. `line-height: 1.6`. Consistent spacing rhythm.

- **Text colors on dark backgrounds:**
  - Primary text: `#F5F5F5`
  - Secondary text: `#A3A3A3`
  - Muted/disabled text: `#737373`

Minimal font-weight variation. Hierarchy through size and color, not weight changes.

## 4. Color Palette (Dark Grayscale)

Auracles theme is dark. All surfaces are dark grayscale. Color is used only for semantic states.

| Token | Hex | Use |
|-------|-----|-----|
| Primary Background | `#0A0A0A` | Page/app background |
| Secondary Background | `#111111` | Navigation, sidebars |
| Surface Background | `#161616` | Elevated surfaces, modals |
| Card Background | `#1A1A1A` | Cards, panels, inputs |
| Primary Text | `#F5F5F5` | Body text, headings |
| Secondary Text | `#A3A3A3` | Descriptions, labels |
| Muted Text | `#737373` | Placeholders, disabled |
| Default Border | `#2A2A2A` | Card borders, dividers |
| Hover Background | `#262626` | Row/card hover state |
| Active State | `#303030` | Active/selected background |
| Hover Border | `#3A3A3A` | Card border on hover |
| Selected Border | `#525252` | Focused/selected element border |
| Success / Neutral Accent | `#D4D4D4` | Success badges, subtle highlights |

**No bright colors. No gradients. Elevation through layered grayscale surfaces.**

For status badges and tags, use dark-tinted variants:
- Success: background `#1A2A1A`, text `#86EFAC`
- Warning: background `#2A2010`, text `#FCD34D`
- Error: background `#2A1010`, text `#FCA5A5`
- Info: background `#101A2A`, text `#93C5FD`

## 5. Component Specifications

### Layout
- 12-column grid, max-width `1440px`, content width `1280px`
- Generous whitespace — `py-16` to `py-24` between major sections
- Persistent left sidebar navigation: compact icon + label, clear active states, documentation-style hierarchy

### Cards (Framework Cards, List Items)
- Background: `#1A1A1A`
- Border: `1px solid #2A2A2A`
- Border-radius: `8px` (architectural, not playful)
- Hover: border shifts to `#3A3A3A`, background to `#1E1E1E`
- No box-shadow. Hover elevation via background + border shift only.
- Strong typography hierarchy inside card. Minimal metadata clutter.

### Buttons
- **Primary:** background `#F5F5F5`, text `#0A0A0A`, border-radius `6px`. Hover: `#E5E5E5`. No shadow.
- **Secondary:** transparent background, border `1px solid #3A3A3A`, text `#F5F5F5`. Hover: background `#1A1A1A`.
- **Destructive:** border `1px solid #FCA5A5`, text `#FCA5A5`, transparent background.
- Active press: `transform: scale(0.98)`.

### Inputs & Forms
- Background: `#1A1A1A`
- Border: `1px solid #2A2A2A`
- Focus border: `1px solid #525252`
- Text: `#F5F5F5`, placeholder: `#737373`
- Border-radius: `6px`

### Tags & Status Badges
- Small (`text-xs`), uppercase, `letter-spacing: 0.05em`
- Use dark-tinted status colors from Section 4
- Border-radius: `4px` (not full pill)

### Dividers
- `border-bottom: 1px solid #2A2A2A` — never use `<hr>` with default styling

### Split-View Workspace (Projects)
- Resizable panels
- `#161616` surface, `#2A2A2A` panel border
- Minimal visual distraction — optimized for deep review workflows

## 6. Iconography & Imagery Directives

- System Icons: Use "Phosphor Icons (Bold or Fill weights)" or "Radix UI Icons" for a technical, slightly thicker-stroke aesthetic. Standardize stroke width across all icons.
- Illustrations: Monochromatic, rough continuous-line ink sketches on a white background, featuring a single offset geometric shape filled with a muted pastel color.
- Photography: Use high-quality, desaturated images with a warm tone. Apply subtle overlays (`opacity: 0.04` warm grain) to blend photos into the monochrome palette. Never use oversaturated stock photos. Use reliable placeholders like `https://picsum.photos/seed/{context}/1200/800` when real assets are unavailable.
- Hero & Section Backgrounds: Sections should not feel empty and flat. Use subtle full-width background imagery at very low opacity, soft radial light spots (`radial-gradient` with warm tones at `opacity: 0.03`), or minimal geometric line patterns to add depth without breaking the clean aesthetic.

## 7. Subtle Motion & Micro-Animations

Motion should feel invisible — present but never distracting. The goal is quiet sophistication, not spectacle.

- Scroll Entry: Elements fade in gently as they enter the viewport. Use `translateY(12px)` + `opacity: 0` resolving over `600ms` with `cubic-bezier(0.16, 1, 0.3, 1)`. Use `IntersectionObserver`, never `window.addEventListener('scroll')`.
- Hover States: Cards lift with an ultra-subtle shadow shift (`box-shadow` transitioning from `0 0 0` to `0 2px 8px rgba(0,0,0,0.04)` over `200ms`). Buttons respond with `scale(0.98)` on `:active`.
- Staggered Reveals: Lists and grid items enter with a cascade delay (`animation-delay: calc(var(--index) * 80ms)`). Never mount everything at once.
- Background Ambient Motion: Optional. A single, very slow-moving radial gradient blob (`animation-duration: 20s+`, `opacity: 0.02-0.04`) drifting behind hero sections. Must be applied to a `position: fixed; pointer-events: none` layer. Never on scrolling containers.
- Performance: Animate exclusively via `transform` and `opacity`. No layout-triggering properties (`top`, `left`, `width`, `height`). Use `will-change: transform` sparingly and only on actively animating elements.

## 8. Execution Protocol

When tasked with writing frontend code (HTML, React, Tailwind, Vue) or designing a layout:

1. Establish the macro-whitespace first. Use massive vertical padding between sections (e.g., `py-24` or `py-32` in Tailwind).
2. Constrain the main typography content width to `max-w-4xl` or `max-w-5xl`.
3. Apply the custom typographic hierarchy and monochromatic color variables immediately.
4. Ensure every card, divider, and border adheres strictly to the `1px solid #EAEAEA` rule.
5. Add scroll-entry animations to all major content blocks.
6. Ensure sections have visual depth through imagery, ambient gradients, or subtle textures — no empty flat backgrounds.
7. Provide code that reflects this high-end, uncluttered, editorial aesthetic natively without requiring manual adjustments.
