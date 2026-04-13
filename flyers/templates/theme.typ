// Shared theme utilities for flyer templates

// Default color palette
#let palette = (
  dark-bg: rgb("#1A1A2E"),
  card-bg: rgb("#232740"),
  accent: rgb("#E94560"),
  purple: rgb("#C77DFF"),
  gold: rgb("#D4A843"),
  light-text: rgb("#B8C5D6"),
  muted: rgb("#6B7B8D"),
  white: rgb("#FFFFFF"),
)

// Parse a user color or return fallback
#let user-color(val, fallback) = {
  if val != none and val != "" {
    rgb(val)
  } else {
    fallback
  }
}

// Accent bar
#let accent-bar(color: palette.accent, width: 100%, height: 3pt) = {
  rect(width: width, height: height, fill: color, radius: 1pt)
}

// Divider line
#let divider(color: palette.purple, width: 80pt) = {
  align(center, rect(width: width, height: 2pt, fill: color, radius: 1pt))
}

// Card box
#let card(body, fill: palette.card-bg, width: 100%, inset: 20pt, radius: 12pt) = {
  rect(
    width: width,
    fill: fill,
    radius: radius,
    inset: inset,
    stroke: 0.5pt + rgb("#ffffff15"),
    body
  )
}

// Pricing card
#let price-card(label, price, subtitle, accent-color: palette.purple) = {
  card(
    width: 45%,
    inset: 16pt,
  )[
    #align(center)[
      #text(size: 10pt, weight: "bold", fill: accent-color, tracking: 2pt)[#upper(label)]
      #v(8pt)
      #text(size: 36pt, weight: "bold", fill: palette.white)[#price]
      #v(4pt)
      #text(size: 10pt, fill: palette.light-text)[#subtitle]
    ]
  ]
}

// Bullet point
#let bullet(body, color: palette.accent) = {
  grid(
    columns: (16pt, 1fr),
    gutter: 8pt,
    text(fill: color, size: 11pt)[#sym.bullet],
    text(fill: palette.light-text, size: 11pt)[#body]
  )
}

// Notice banner
#let notice(body, color: palette.accent) = {
  rect(
    width: 100%,
    fill: color.lighten(85%),
    stroke: 0.5pt + color.lighten(50%),
    radius: 8pt,
    inset: 12pt,
    align(center, text(fill: color, size: 10pt, weight: "bold")[#body])
  )
}
