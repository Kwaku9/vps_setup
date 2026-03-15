/**
 * Cloudflare Worker: YouTube Transcript Proxy
 *
 * Uses YouTube's Innertube API (same as youtube-transcript-api library)
 * to fetch transcripts from CF's edge network.
 *
 * Usage:
 *   GET /transcript?v=VIDEO_ID[&timestamps=true][&lang=en]
 *   GET /health
 */

export default {
  async fetch(request, env) {
    const corsHeaders = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Authorization, Content-Type',
    };

    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders });
    }

    // Auth check
    if (env.AUTH_TOKEN) {
      const auth = request.headers.get('Authorization');
      if (!auth || auth !== `Bearer ${env.AUTH_TOKEN}`) {
        return new Response('Unauthorized', { status: 401, headers: corsHeaders });
      }
    }

    const url = new URL(request.url);

    if (url.pathname === '/health') {
      return new Response('ok', { headers: corsHeaders });
    }

    if (url.pathname !== '/transcript') {
      return new Response('Use GET /transcript?v=VIDEO_ID', { status: 404, headers: corsHeaders });
    }

    // Support both GET (public videos) and POST (with cookies for login-required)
    let videoId, withTimestamps, lang, cookies;

    if (request.method === 'POST') {
      const body = await request.json().catch(() => ({}));
      videoId = body.v || url.searchParams.get('v');
      withTimestamps = body.timestamps || url.searchParams.get('timestamps') === 'true';
      lang = body.lang || url.searchParams.get('lang') || 'en';
      cookies = body.cookies || null;
    } else {
      videoId = url.searchParams.get('v');
      withTimestamps = url.searchParams.get('timestamps') === 'true';
      lang = url.searchParams.get('lang') || 'en';
      cookies = null;
    }

    if (!videoId) {
      return new Response('Missing ?v=VIDEO_ID', { status: 400, headers: corsHeaders });
    }

    try {
      const transcript = await fetchTranscript(videoId, lang, withTimestamps, cookies);
      return new Response(transcript, {
        headers: { ...corsHeaders, 'Content-Type': 'text/plain; charset=utf-8' },
      });
    } catch (err) {
      return new Response(`Error: ${err.message}`, { status: 500, headers: corsHeaders });
    }
  },
};

const INNERTUBE_CLIENTS = {
  webEmbed: {
    context: {
      client: {
        clientName: 'WEB_EMBEDDED_PLAYER',
        clientVersion: '1.20260220.00.00',
        hl: 'en',
        gl: 'US',
      },
      thirdParty: {
        embedUrl: 'https://www.google.com',
      },
    },
    apiKey: 'AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8',
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
  },
  web: {
    context: {
      client: {
        clientName: 'WEB',
        clientVersion: '2.20260220.00.00',
        hl: 'en',
        gl: 'US',
      },
    },
    apiKey: 'AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8',
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
  },
  ios: {
    context: {
      client: {
        clientName: 'IOS',
        clientVersion: '20.08.4',
        deviceMake: 'Apple',
        deviceModel: 'iPhone16,2',
        hl: 'en',
        gl: 'US',
        osName: 'iPhone',
        osVersion: '18.3.2',
      },
    },
    apiKey: 'AIzaSyB-63vPrdThhKuerbB2N_l7Kwwcxj6yUAc',
    userAgent: 'com.google.ios.youtube/20.08.4 (iPhone16,2; U; CPU iOS 18_3_2 like Mac OS X;)',
  },
  android: {
    context: {
      client: {
        clientName: 'ANDROID',
        clientVersion: '20.08.38',
        androidSdkVersion: 35,
        hl: 'en',
        gl: 'US',
        osName: 'Android',
        osVersion: '15',
      },
    },
    apiKey: 'AIzaSyA8eiZmM1FaDVjRy-df2KTyQ_vz_yYM39w',
    userAgent: 'com.google.android.youtube/20.08.38 (Linux; U; Android 15; en_US; Pixel 9 Pro Build/AP4A.250205.002) gzip',
  },
};

async function fetchTranscript(videoId, lang, withTimestamps, cookies) {
  let lastError = null;

  const errors = [];

  // Method 1: Scrape the YouTube watch page HTML for embedded captions.
  // Most reliable — fetches the page like a real browser visit.
  try {
    return await tryWatchPage(videoId, lang, withTimestamps, cookies);
  } catch (err) {
    errors.push(`watchPage: ${err.message}`);
  }

  // Method 2: Innertube player API with multiple client types.
  const clientOrder = ['webEmbed', 'web', 'ios', 'android'];

  for (const clientKey of clientOrder) {
    try {
      return await tryClient(clientKey, videoId, lang, withTimestamps, cookies);
    } catch (err) {
      errors.push(`${clientKey}: ${err.message}`);
    }
  }

  throw new Error(errors.join(' | '));
}

async function tryWatchPage(videoId, lang, withTimestamps, cookies) {
  // Fetch the YouTube watch page like a real browser visit
  const ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36';

  const cookieHeader = cookies
    ? cookies
    : 'CONSENT=PENDING+987; SOCS=CAESEwgDEgk2NjQxNDUyNjYaAmVuIAEaBgiA_MSZBQ';

  const resp = await fetch(`https://www.youtube.com/watch?v=${videoId}&hl=en`, {
    headers: {
      'User-Agent': ua,
      'Accept-Language': 'en-US,en;q=0.9',
      'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
      Cookie: cookieHeader,
    },
  });

  if (!resp.ok) {
    throw new Error(`Watch page returned ${resp.status}`);
  }

  const html = await resp.text();

  // Extract ytInitialPlayerResponse JSON from the page
  const playerMatch = html.match(/var ytInitialPlayerResponse\s*=\s*(\{.+?\});/s);
  if (!playerMatch) {
    // Try alternative pattern
    const altMatch = html.match(/ytInitialPlayerResponse\s*=\s*(\{.+?\});/s);
    if (!altMatch) {
      throw new Error('Could not find ytInitialPlayerResponse in page HTML');
    }
    var playerData = JSON.parse(altMatch[1]);
  } else {
    var playerData = JSON.parse(playerMatch[1]);
  }

  const status = playerData?.playabilityStatus?.status;
  if (status === 'LOGIN_REQUIRED') {
    throw new Error('Watch page: video requires login');
  }
  if (status === 'ERROR') {
    throw new Error(`Watch page: ${playerData?.playabilityStatus?.reason || 'video unavailable'}`);
  }

  const captionTracks =
    playerData?.captions?.playerCaptionsTracklistRenderer?.captionTracks;

  if (!captionTracks || captionTracks.length === 0) {
    throw new Error('Watch page: no captions available');
  }

  // Find best matching language
  let track = captionTracks.find((t) => t.languageCode === lang);
  if (!track) {
    track = captionTracks.find((t) => t.languageCode.startsWith(lang));
  }
  if (!track) {
    track = captionTracks[0];
  }

  // Fetch the caption data
  const captionUrl = track.baseUrl + '&fmt=json3';
  const captionResp = await fetch(captionUrl, {
    headers: { 'User-Agent': ua },
  });

  if (!captionResp.ok) {
    throw new Error(`Watch page: caption fetch returned ${captionResp.status}`);
  }

  const captionText = await captionResp.text();
  let captionData;
  try {
    captionData = JSON.parse(captionText);
  } catch {
    throw new Error(`Watch page: caption data non-JSON: ${captionText.slice(0, 100)}`);
  }

  return parseEvents(captionData.events || [], withTimestamps);
}

async function tryClient(clientKey, videoId, lang, withTimestamps, cookies) {
  const client = INNERTUBE_CLIENTS[clientKey];

  // Generate a visitor data token (helps bypass bot detection)
  const visitorData = generateVisitorData();

  // Use real cookies if provided, otherwise minimal consent cookie
  const cookieHeader = cookies
    ? cookies
    : 'CONSENT=PENDING+987; SOCS=CAESEwgDEgk2NjQxNDUyNjYaAmVuIAEaBgiA_MSZBQ';

  // Extract SAPISID from cookies for SAPISIDHASH auth header
  const authHeaders = {};
  if (cookies) {
    const sapisid = extractCookie(cookies, 'SAPISID');
    if (sapisid) {
      const origin = 'https://www.youtube.com';
      const timestamp = Math.floor(Date.now() / 1000);
      const hash = await sha1(`${timestamp} ${sapisid} ${origin}`);
      authHeaders['Authorization'] = `SAPISIDHASH ${timestamp}_${hash}`;
    }
  }

  // Step 1: Call the player endpoint to get caption track URLs
  const playerResp = await fetch(
    `https://www.youtube.com/youtubei/v1/player?key=${client.apiKey}&prettyPrint=false`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'User-Agent': client.userAgent,
        'X-YouTube-Client-Name': getClientId(clientKey),
        'X-YouTube-Client-Version': client.context.client.clientVersion,
        'X-Goog-Visitor-Id': visitorData,
        Origin: 'https://www.youtube.com',
        Referer: `https://www.youtube.com/watch?v=${videoId}`,
        'Accept-Language': 'en-US,en;q=0.9',
        Cookie: cookieHeader,
        ...authHeaders,
      },
      body: JSON.stringify({
        context: {
          ...client.context,
          client: {
            ...client.context.client,
            visitorData: visitorData,
          },
        },
        videoId: videoId,
        contentCheckOk: true,
        racyCheckOk: true,
      }),
    }
  );

  if (!playerResp.ok) {
    throw new Error(`Player API returned ${playerResp.status} for client ${clientKey}`);
  }

  const playerText = await playerResp.text();
  let playerData;
  try {
    playerData = JSON.parse(playerText);
  } catch {
    throw new Error(`Player API returned non-JSON (client: ${clientKey}): ${playerText.slice(0, 100)}`);
  }

  // Check playability
  const status = playerData?.playabilityStatus?.status;
  if (status === 'LOGIN_REQUIRED') {
    throw new Error(`Video requires login (client: ${clientKey})`);
  }
  if (status === 'ERROR') {
    throw new Error(`Video unavailable: ${playerData?.playabilityStatus?.reason || 'unknown'}`);
  }

  // Extract caption tracks
  const captionTracks =
    playerData?.captions?.playerCaptionsTracklistRenderer?.captionTracks;

  if (!captionTracks || captionTracks.length === 0) {
    throw new Error(`No captions available (client: ${clientKey})`);
  }

  // Find best matching language
  let track = captionTracks.find((t) => t.languageCode === lang);
  if (!track) {
    track = captionTracks.find((t) => t.languageCode.startsWith(lang));
  }
  if (!track) {
    track = captionTracks[0]; // fallback to first
  }

  // Step 2: Fetch the actual transcript data
  const captionUrl = track.baseUrl + '&fmt=json3';
  const captionResp = await fetch(captionUrl, {
    headers: { 'User-Agent': client.userAgent },
  });

  if (!captionResp.ok) {
    throw new Error(`Caption fetch returned ${captionResp.status}`);
  }

  const captionText = await captionResp.text();
  let captionData;
  try {
    captionData = JSON.parse(captionText);
  } catch {
    throw new Error(`Caption data non-JSON (client: ${clientKey}): ${captionText.slice(0, 100)}`);
  }
  return parseEvents(captionData.events || [], withTimestamps, clientKey);
}

function parseEvents(events, withTimestamps, source) {
  const lines = [];
  for (const event of events) {
    const segs = event.segs || [];
    const text = segs
      .map((s) => (s.utf8 || '').replace(/\n/g, ' '))
      .join('')
      .trim();

    if (!text) continue;

    if (withTimestamps && event.tStartMs !== undefined) {
      const totalSec = Math.floor(event.tStartMs / 1000);
      const min = Math.floor(totalSec / 60);
      const sec = totalSec % 60;
      lines.push(`[${String(min).padStart(2, '0')}:${String(sec).padStart(2, '0')}] ${text}`);
    } else {
      lines.push(text);
    }
  }

  if (lines.length === 0) {
    throw new Error(`Transcript empty after parsing (${source || 'unknown'})`);
  }

  return lines.join('\n');
}

function getClientId(clientKey) {
  const ids = {
    web: '1',
    webEmbed: '56',
    ios: '5',
    android: '3',
  };
  return ids[clientKey] || '1';
}

function generateVisitorData() {
  // Generate a realistic-looking visitor data token
  // This is a base64-encoded protobuf that YouTube uses for session tracking
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
  let result = 'CgtY';
  for (let i = 0; i < 18; i++) {
    result += chars[Math.floor(Math.random() * chars.length)];
  }
  result += '%3D%3D';
  return result;
}

function extractCookie(cookieStr, name) {
  // Extract a cookie value from a Netscape cookies.txt format or Cookie header string
  // Cookie header format: "name=value; name2=value2"
  const match = cookieStr.match(new RegExp(`(?:^|;\\s*|\\n)${name}[=\\t]\\s*([^;\\n]+)`));
  return match ? match[1].trim() : null;
}

async function sha1(message) {
  const encoder = new TextEncoder();
  const data = encoder.encode(message);
  const hashBuffer = await crypto.subtle.digest('SHA-1', data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map((b) => b.toString(16).padStart(2, '0')).join('');
}
