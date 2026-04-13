// Minimal clean flyer — simple message with strong typography
#import "theme.typ": *

// Default parameter values (overridden by params.typ)
#let title = "TITLE"
#let subtitle = ""
#let message = ""
#let date = ""
#let time = ""
#let location = ""
#let contact = ""
#let footer-text = ""
#let color-bg = none
#let color-accent = none
#let color-secondary = none

#let flyer(body) = {
  let bg = user-color(color-bg, palette.dark-bg)
  let acc = user-color(color-accent, palette.gold)
  let sec = user-color(color-secondary, palette.purple)

  set page(
    width: 8.5in,
    height: 11in,
    margin: 1in,
    fill: bg,
  )
  set text(font: "Inter", fill: palette.white, size: 11pt)

  v(1fr)

  // Accent line
  align(center, rect(width: 40pt, height: 3pt, fill: acc, radius: 1pt))

  v(30pt)

  // Subtitle
  if subtitle != "" {
    align(center,
      text(size: 11pt, fill: sec, tracking: 3pt, weight: "bold")[
        #upper(subtitle)
      ]
    )
    v(20pt)
  }

  // Title — big and bold
  align(center,
    text(size: 56pt, weight: "bold", fill: palette.white, font: "Playfair Display")[
      #upper(title)
    ]
  )

  v(20pt)

  // Accent line
  align(center, rect(width: 40pt, height: 3pt, fill: acc, radius: 1pt))

  v(24pt)

  // Message
  if message != "" {
    align(center,
      block(width: 75%)[
        #set par(leading: 1.6em)
        #text(size: 12pt, fill: palette.light-text)[#message]
      ]
    )
    v(30pt)
  }

  // Date / Time / Location
  {
    let has-details = date != "" or time != "" or location != ""
    if has-details {
      align(center)[
        #if date != "" {
          text(size: 13pt, fill: palette.white, weight: "bold")[#date]
          if time != "" {
            text(size: 13pt, fill: palette.muted)[ #sym.dot.c ]
            text(size: 13pt, fill: palette.white, weight: "bold")[#time]
          }
          v(8pt)
        }
        #if location != "" {
          text(size: 11pt, fill: palette.light-text)[#location]
        }
      ]
      v(30pt)
    }
  }

  // Contact
  if contact != "" {
    align(center,
      text(size: 11pt, fill: acc)[#contact]
    )
  }

  v(1fr)

  // Footer
  if footer-text != "" {
    align(center,
      text(size: 8pt, fill: palette.muted, tracking: 2pt)[
        #upper(footer-text)
      ]
    )
    v(16pt)
  }

  align(center, rect(width: 40pt, height: 3pt, fill: acc, radius: 1pt))
}
