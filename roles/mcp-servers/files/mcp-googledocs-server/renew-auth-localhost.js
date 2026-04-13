#!/usr/bin/env node

import { google } from 'googleapis';
import * as fs from 'fs/promises';
import http from 'http';
import { URL } from 'url';
import open from 'open';

const PORT = 3101;
const REDIRECT_URI = `http://localhost:${PORT}`;

console.log('='.repeat(60));
console.log('Google Docs MCP Server - Authentication');
console.log('='.repeat(60));
console.log('');

async function renewAuth() {
  try {
    // Delete old token
    try {
      await fs.unlink('./token.json');
      console.log('✓ Deleted old token.json');
    } catch (err) {
      console.log('ℹ No existing token.json found');
    }

    // Load credentials
    const credContent = await fs.readFile('./credentials.json');
    const keys = JSON.parse(credContent.toString());
    const key = keys.installed || keys.web;

    if (!key) {
      throw new Error('Credentials not found in credentials.json');
    }

    const { client_id, client_secret } = key;

    const oAuth2Client = new google.auth.OAuth2(
      client_id,
      client_secret,
      REDIRECT_URI
    );

    const authorizeUrl = oAuth2Client.generateAuthUrl({
      access_type: 'offline',
      scope: [
        'https://www.googleapis.com/auth/documents',
        'https://www.googleapis.com/auth/drive'
      ],
      prompt: 'consent'
    });

    console.log('');
    console.log('Starting local server on port', PORT);
    console.log('');
    console.log('Opening browser for authorization...');
    console.log('');
    console.log('If browser doesn\'t open automatically, visit:');
    console.log(authorizeUrl);
    console.log('');

    // Create local server
    const server = http.createServer(async (req, res) => {
      try {
        const url = new URL(req.url, REDIRECT_URI);

        if (url.pathname === '/') {
          const code = url.searchParams.get('code');
          const error = url.searchParams.get('error');

          if (error) {
            res.writeHead(400, { 'Content-Type': 'text/html' });
            res.end(`<h1>Authorization Error</h1><p>${error}</p>`);
            console.error('Authorization error:', error);
            setTimeout(() => process.exit(1), 1000);
            return;
          }

          if (!code) {
            res.writeHead(400, { 'Content-Type': 'text/html' });
            res.end('<h1>Error: No authorization code received</h1>');
            return;
          }

          try {
            const { tokens } = await oAuth2Client.getToken(code);
            oAuth2Client.setCredentials(tokens);

            const tokenData = JSON.stringify({
              type: 'authorized_user',
              client_id: client_id,
              client_secret: client_secret,
              refresh_token: tokens.refresh_token,
            });
            await fs.writeFile('./token.json', tokenData);

            res.writeHead(200, { 'Content-Type': 'text/html' });
            res.end(`
              <html>
                <body style="font-family: Arial; padding: 50px; text-align: center;">
                  <h1 style="color: green;">✓ Authentication Successful!</h1>
                  <p>Token saved to token.json</p>
                  <p>You can close this window.</p>
                </body>
              </html>
            `);

            console.log('');
            console.log('='.repeat(60));
            console.log('✓ Authentication successful!');
            console.log('='.repeat(60));
            console.log('');
            console.log('Next steps:');
            console.log('1. docker cp token.json Google-Drive-Docs-mcp:/app/token.json');
            console.log('2. docker cp credentials.json Google-Drive-Docs-mcp:/app/credentials.json');
            console.log('3. docker restart Google-Drive-Docs-mcp');
            console.log('');

            setTimeout(() => {
              server.close();
              process.exit(0);
            }, 2000);
          } catch (error) {
            console.error('Token exchange error:', error.message);
            res.writeHead(500, { 'Content-Type': 'text/html' });
            res.end('<h1>Token Exchange Error</h1><p>' + error.message + '</p>');
          }
        }
      } catch (error) {
        console.error('Request handling error:', error.message);
      }
    });

    server.listen(PORT, async () => {
      console.log(`✓ Local server listening on ${REDIRECT_URI}`);
      console.log('');
      try {
        await open(authorizeUrl);
        console.log('✓ Browser opened');
      } catch (err) {
        console.log('⚠ Could not open browser automatically');
        console.log('Please open the URL manually');
      }
      console.log('');
      console.log('Waiting for authorization...');
    });

  } catch (error) {
    console.error('');
    console.error('✗ Error:', error.message);
    console.error('');
    process.exit(1);
  }
}

renewAuth();
