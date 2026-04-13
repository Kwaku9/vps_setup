FROM alpine:3.21 AS base

# Install Typst and dependencies
RUN apk add --no-cache \
    curl \
    python3 \
    py3-pip \
    fontconfig \
    ttf-dejavu \
    font-noto \
    font-noto-emoji \
    && mkdir -p /usr/share/fonts/google

# Install Typst binary from GitHub releases
ARG TYPST_VERSION=0.13.1
RUN curl -sSL "https://github.com/typst/typst/releases/download/v${TYPST_VERSION}/typst-x86_64-unknown-linux-musl.tar.xz" \
    | tar xJ --strip-components=1 -C /usr/local/bin/ "typst-x86_64-unknown-linux-musl/typst" \
    && chmod +x /usr/local/bin/typst \
    && typst --version

# Install Google Fonts (variable font files from google/fonts repo)
RUN cd /usr/share/fonts/google \
    && curl -sSL -o "Inter.ttf" \
       "https://raw.githubusercontent.com/google/fonts/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf" \
    && curl -sSL -o "PlayfairDisplay.ttf" \
       "https://raw.githubusercontent.com/google/fonts/main/ofl/playfairdisplay/PlayfairDisplay%5Bwght%5D.ttf" \
    && curl -sSL -o "PlayfairDisplay-Italic.ttf" \
       "https://raw.githubusercontent.com/google/fonts/main/ofl/playfairdisplay/PlayfairDisplay-Italic%5Bwght%5D.ttf" \
    && curl -sSL -o "Montserrat.ttf" \
       "https://raw.githubusercontent.com/google/fonts/main/ofl/montserrat/Montserrat%5Bwght%5D.ttf" \
    && fc-cache -f

WORKDIR /app

# Copy templates and generation script
COPY templates/ /app/templates/
COPY generate.py /app/generate.py

# Output directory (mount from host)
VOLUME /app/output

ENV TYPST_FONT_PATHS=/usr/share/fonts

ENTRYPOINT ["python3", "/app/generate.py"]
