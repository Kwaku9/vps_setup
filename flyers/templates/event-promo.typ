// Event promotion flyer — concerts, parties, launches, meetups
#import "theme.typ": *

// Default parameter values (overridden by params.typ)
#let event-name = "EVENT NAME"
#let event-tagline = "Your tagline here"
#let event-date = "Saturday, July 12th"
#let event-time = "8:00 PM"
#let event-venue = "The Venue"
#let event-address = "123 Main Street"
#let event-description = ""
#let event-features = ()
#let event-price = ""
#let event-price-label = ""
#let event-rsvp = ""
#let event-contact = ""
#let event-phone = ""
#let event-website = ""
#let event-organizer = ""
#let event-note = ""
#let color-bg = none
#let color-accent = none
#let color-secondary = none

#let flyer(body) = {
  let bg = user-color(color-bg, palette.dark-bg)
  let acc = user-color(color-accent, palette.accent)
  let sec = user-color(color-secondary, palette.purple)

  set page(
    width: 8.5in,
    height: 11in,
    margin: 0.6in,
    fill: bg,
  )
  set text(font: "Inter", fill: palette.white, size: 11pt)

  // Top accent bar
  accent-bar(color: acc)

  v(24pt)

  // Organizer
  if event-organizer != "" {
    align(center,
      text(size: 10pt, fill: sec, tracking: 3pt, weight: "bold")[
        #upper(event-organizer) PRESENTS
      ]
    )
    v(16pt)
  }

  // Event name
  align(center,
    text(size: 44pt, weight: "bold", fill: palette.white, font: "Playfair Display")[
      #upper(event-name)
    ]
  )

  v(12pt)

  // Tagline
  if event-tagline != "" {
    align(center,
      text(size: 14pt, fill: acc, tracking: 2pt)[
        #upper(event-tagline)
      ]
    )
  }

  v(12pt)
  divider(color: sec)
  v(16pt)

  // Description
  if event-description != "" {
    align(center,
      block(width: 85%)[
        #set par(leading: 1.4em)
        #text(size: 11pt, fill: palette.light-text)[#event-description]
      ]
    )
    v(20pt)
  }

  // Date/Time/Venue card
  card(inset: 24pt)[
    #align(center)[
      #grid(
        columns: (1fr, auto, 1fr),
        gutter: 20pt,
        align(center)[
          #text(size: 9pt, fill: sec, tracking: 2pt, weight: "bold")[DATE]
          #v(6pt)
          #text(size: 14pt, fill: palette.white, weight: "bold")[#event-date]
        ],
        rect(width: 1pt, height: 40pt, fill: rgb("#ffffff20")),
        align(center)[
          #text(size: 9pt, fill: sec, tracking: 2pt, weight: "bold")[TIME]
          #v(6pt)
          #text(size: 14pt, fill: palette.white, weight: "bold")[#event-time]
        ],
      )
      #v(12pt)
      #rect(width: 60%, height: 0.5pt, fill: rgb("#ffffff15"))
      #v(12pt)
      #text(size: 9pt, fill: sec, tracking: 2pt, weight: "bold")[VENUE]
      #v(6pt)
      #text(size: 14pt, fill: palette.white, weight: "bold")[#event-venue]
      #if event-address != "" {
        v(4pt)
        text(size: 10pt, fill: palette.light-text)[#event-address]
      }
    ]
  ]

  v(20pt)

  // Features list
  if event-features.len() > 0 {
    align(center,
      block(width: 80%)[
        #for (i, feature) in event-features.enumerate() {
          let col = if calc.odd(i) { sec } else { acc }
          bullet(color: col)[#feature]
          v(4pt)
        }
      ]
    )
    v(20pt)
  }

  // Price
  if event-price != "" {
    align(center)[
      #card(width: 50%, inset: 16pt)[
        #align(center)[
          #if event-price-label != "" {
            text(size: 9pt, fill: sec, tracking: 2pt, weight: "bold")[#upper(event-price-label)]
            v(6pt)
          }
          #text(size: 32pt, weight: "bold", fill: palette.white)[#event-price]
        ]
      ]
    ]
    v(20pt)
  }

  // Notice
  if event-note != "" {
    notice(color: acc)[#event-note]
    v(20pt)
  }

  // Contact / RSVP card
  {
    let has-contact = event-rsvp != "" or event-contact != "" or event-phone != "" or event-website != ""
    if has-contact {
      card(inset: 20pt)[
        #align(center)[
          #text(size: 9pt, fill: sec, tracking: 3pt, weight: "bold")[READY TO JOIN?]
          #v(10pt)
          #if event-rsvp != "" {
            text(size: 11pt, fill: palette.white)[RSVP: #event-rsvp]
            v(6pt)
          }
          #if event-contact != "" {
            text(size: 11pt, fill: palette.white)[#event-contact]
            v(6pt)
          }
          #if event-phone != "" {
            text(size: 11pt, fill: palette.white)[#event-phone]
            v(6pt)
          }
          #if event-website != "" {
            text(size: 10pt, fill: palette.light-text)[#event-website]
          }
        ]
      ]
    }
  }

  v(1fr)

  // Footer
  if event-organizer != "" {
    align(center,
      text(size: 8pt, fill: palette.muted, tracking: 3pt)[
        #upper(event-organizer)
      ]
    )
    v(12pt)
  }

  accent-bar(color: acc)
}
