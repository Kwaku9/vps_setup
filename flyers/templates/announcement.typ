// General announcement flyer — news, openings, services, offers
#import "theme.typ": *

// Default parameter values (overridden by params.typ)
#let title = "ANNOUNCEMENT"
#let subtitle = ""
#let heading = ""
#let body-text = ""
#let features = ()
#let price-1-label = ""
#let price-1-amount = ""
#let price-1-detail = ""
#let price-2-label = ""
#let price-2-amount = ""
#let price-2-detail = ""
#let notice-text = ""
#let contact-heading = "GET IN TOUCH"
#let contact-email = ""
#let contact-phone = ""
#let contact-address = ""
#let contact-website = ""
#let footer-text = ""
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

  v(20pt)

  // Subtitle / org name
  if subtitle != "" {
    align(center,
      text(size: 10pt, fill: sec, tracking: 3pt, weight: "bold")[
        #upper(subtitle)
      ]
    )
    v(16pt)
  }

  // Main title
  align(center,
    text(size: 42pt, weight: "bold", fill: palette.white, font: "Playfair Display")[
      #upper(title)
    ]
  )

  v(10pt)

  // Heading
  if heading != "" {
    align(center,
      text(size: 14pt, fill: acc, tracking: 2pt)[
        #upper(heading)
      ]
    )
  }

  v(12pt)
  divider(color: sec)
  v(16pt)

  // Body text
  if body-text != "" {
    align(center,
      block(width: 85%)[
        #set par(leading: 1.4em)
        #text(size: 11pt, fill: palette.light-text)[#body-text]
      ]
    )
    v(22pt)
  }

  // Pricing cards (if provided)
  if price-1-amount != "" {
    align(center,
      grid(
        columns: if price-2-amount != "" { (1fr, 1fr) } else { (1fr,) },
        gutter: 16pt,
        price-card(price-1-label, price-1-amount, price-1-detail, accent-color: sec),
        if price-2-amount != "" {
          price-card(price-2-label, price-2-amount, price-2-detail, accent-color: sec)
        },
      )
    )
    v(22pt)
  }

  // Features
  if features.len() > 0 {
    align(center,
      block(width: 80%)[
        #for (i, feature) in features.enumerate() {
          let col = if calc.odd(i) { sec } else { acc }
          bullet(color: col)[#feature]
          v(4pt)
        }
      ]
    )
    v(22pt)
  }

  // Notice
  if notice-text != "" {
    notice(color: acc)[#notice-text]
    v(22pt)
  }

  // Contact card
  {
    let has-contact = contact-email != "" or contact-phone != "" or contact-address != "" or contact-website != ""
    if has-contact {
      card(inset: 20pt)[
        #align(center)[
          #text(size: 9pt, fill: sec, tracking: 3pt, weight: "bold")[#upper(contact-heading)]
          #v(10pt)
          #if contact-email != "" {
            text(size: 11pt, fill: palette.white)[#contact-email]
            v(6pt)
          }
          #if contact-phone != "" {
            text(size: 11pt, fill: palette.white)[#contact-phone]
            v(6pt)
          }
          #if contact-address != "" {
            text(size: 10pt, fill: palette.light-text)[#contact-address]
            v(6pt)
          }
          #if contact-website != "" {
            text(size: 10pt, fill: palette.light-text)[#contact-website]
          }
        ]
      ]
    }
  }

  v(1fr)

  // Footer
  if footer-text != "" {
    align(center,
      text(size: 8pt, fill: palette.muted, tracking: 3pt)[
        #upper(footer-text)
      ]
    )
    v(12pt)
  }

  accent-bar(color: acc)
}
