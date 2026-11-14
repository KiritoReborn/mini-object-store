---
name: Artaud storage workspace
description: Precise object management with visible storage-system truth.
colors:
  primary: "#08694f"
  primary-hover: "#05543e"
  primary-soft: "#e9f3ed"
  ink: "#1e2924"
  muted: "#637068"
  canvas: "#ffffff"
  sidebar: "#f5f8f6"
  subtle: "#f5f7f6"
  divider: "#e5eae7"
  danger: "#b22b38"
  warning: "#875b16"
typography:
  headline:
    fontFamily: "Geist, Segoe UI, sans-serif"
    fontSize: "29px"
    fontWeight: 550
    lineHeight: 1.25
    letterSpacing: "-0.85px"
  body:
    fontFamily: "Geist, Segoe UI, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Geist, Segoe UI, sans-serif"
    fontSize: "13px"
    fontWeight: 500
    lineHeight: 1.5
rounded:
  control: "7px"
  upload: "11px"
  dialog: "14px"
spacing:
  compact: "8px"
  control: "14px"
  panel: "29px"
  workspace: "38px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.canvas}"
    rounded: "{rounded.control}"
    padding: "9px 14px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
    textColor: "{colors.canvas}"
  button-destructive:
    backgroundColor: "{colors.danger}"
    textColor: "{colors.canvas}"
    rounded: "{rounded.control}"
---

## Overview

Artaud is an operational file workspace. Files lead; infrastructure explains availability. The interface uses restrained green actions, cool-white content, mineral navigation and fine structural separators. The built surface and CSS are authoritative; this document records the shipped choices rather than proposing a future redesign.

## Colors

Green identifies primary actions, selection and confirmed availability. Amber means waiting or attention, red means failure or a destructive action, and neutral means unknown. Status always has readable text. File-type icon colors aid scanning and never replace a textual type label. Old snapshots lose green availability claims when the controller cannot refresh.

## Typography

One self-hosted Geist variable face carries the product; Segoe UI/system sans is the fallback. The font and license ship locally. Headings use a restrained fixed scale; mobile h1 is 26px, then 24px at the narrowest breakpoint. Body data uses tabular numbers. Monospace is reserved for checksums, IDs and JSON. Long filenames truncate in tables and wrap fully in the inspector.

## Layout

Desktop has a 216px sticky navigation rail, flexible main area and a 260px system rail. The main frame uses 38px padding and a 29px content gap. At 1199px the system rail moves below files; at 860px navigation narrows; at 640px it becomes top navigation. At 359px the Size column moves into filename secondary text. Desktop tables paginate ten rows; the inspector scrolls independently while its actions remain visible. Dense lists are intentional; data visualizations must explain actual observations.

Cluster extends this system with a live SVG connection map, controller at left and workers branching at right. On phones a shared controller trunk branches to each worker. HTML buttons carry labels/actions over the geometry; node status always has text. Green traveling marks represent recent worker-transfer observations for four seconds; blue marks are explicitly timestamped historical replay. Neither is an in-flight or throughput meter. Pause freezes this surface; reduced motion removes travel. The eight-row chunk matrix provides exact replica text; distribution bars show shares of recorded copy bytes. Recovery stages describe detection, reconciliation and verification with actual counts and recorded changes, never fictitious progress. The explorer uses 24px section gaps and 24px internal padding, reducing to 16px on phones.

## Elevation & Depth

Tonal layering and thin dividers define normal surfaces. Soft, offset elevation is reserved for dialogs/toasts: `0 5px 14px #142d1e0b, 0 16px 40px #142d1e14`. The backdrop dims the active viewport. There are no glass surfaces, glow effects or faux physical textures.

## Shapes

Controls use 7px corners, the inline upload surface 11px, dialogs 14px and type icons 6â€“12px according to size. Thin borders communicate grouping/state. Small status badges are compact rounded labels rather than large pill containers.

## Components

- Buttons have explicit primary/secondary/destructive/ghost variants, visible focus and disabled/loading states. Hover transitions are about 150ms. Press feedback is a restrained 0.96 scale; reduced-motion settings remove transitions/animations.
- Inputs use fine neutral strokes, a visible green focus treatment and labeled errors. Native file chooser and drag/drop coexist. Upload progress distinguishes sending from replica confirmation and final storage success.
- Native dialogs trap focus. Object details use semantic tabs with roving focus, arrow/Home/End support and an independently scrolling body. Modal feedback stays inside the modal so it is visible and announced. Delete confirmation names the file and visibly disables closure while the operation is in flight.
- Lucide outline icons are the single icon vocabulary. Native text labels carry meaning; icons are decoration or have an action name.
- Objects are a real table with search, type filtering, sorting and pagination. Cluster state is a read-only view of controller observations, not a capacity gauge or Docker control surface.

## Do's and Don'ts

- Do preserve real-data and stale/unknown distinctions. Do label replication as a target when it is policy rather than an observed result.
- Do keep operational tasks visible and errors recoverable. Do test empty, loading, error, queued, stored and unavailable states.
- Do preserve the same-origin controller deployment and B-owned recovery boundary.
- Don't ship QA fixture data, mock network handlers, design briefs or direction metadata in the production UI.
- Don't add speculative analytics, cloud-provider claims, unsupported capacity percentages or decorative charts.

## Demo controls and quiet activity

Worker management uses the same compact structural rows, native dialogs and explicit disabled/error states. Container running state and controller availability have separate text labels. Stop/restart require a focused confirmation; volumes are not deleted. The activity panel starts with grouped successful operations and individually visible failures; the technical filter retains original event detail. Connection settings hide the owner key and explain the direct backend origin. The walkthrough is a collapsible checklist with clearly self-reported progress, keeping the topology primary.
