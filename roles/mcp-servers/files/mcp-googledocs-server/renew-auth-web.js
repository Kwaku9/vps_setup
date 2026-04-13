#!/usr/bin/env node

// Web-based authentication renewal for Google Docs MCP Server
// Works with web app OAuth credentials

import { google } from 'googleapis';
import * as fs from 'fs/promises';
import http from 'http';
import { URL } from 'url';

console.log('='.repeat(60));
console.log('Google Docs MCP Server - Web Authentication');
console.log('='.repeat(60));
console.log('');

async function renewAuthWeb() {
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
    const key = keys.web;

    if (!key) {
      throw new Error('Web credentials not found in credentials.json');
    }

    const { client_id, client_secret, redirect_uris } = key;

    // Use localhost redirect for local auth server
    const redirectUri = 'http://localhost:3000/oauth2callback';

    const oAuth2Client = new google.auth.OAuth2(
      client_id,
      client_secret,
      redirectUri
    );

    const authorizeUrl = oAuth2Client.generateAuthUrl({
      access_type: 'offline',
      scope: [
        'https://www.googleapis.com/auth/documents',
        'https://www.googleapis.com/auth/drive'
      ].join(' '),
      prompt: 'consent' // Force to get refresh token
    });

    console.log('');
    console.log('Please visit this URL to authorize:');
    console.log('');
    console.log(authorizeUrl);
    console.log('');
    console.log('Waiting for authorization...');
    console.log('(A local server is running on http://localhost:3000)');
    console.log('');

    // Create local server to receive the callback
    const server = http.createServer(async (req, res) => {
      try {
        const url = new URL(req.url, `http://${req.headers.host}`);

        if (url.pathname === '/oauth2callback') {
          const code = url.searchParams.get('code');

          if (!code) {
            res.writeHead(400, { 'Content-Type': 'text/html' });
            res.end('<h1>Error: No authorization code received</h1>');
            return;
          }

          // Exchange code for tokens
          const { tokens } = await oAuth2Client.getToken(code);
          oAuth2Client.setCredentials(tokens);

          // Save tokens
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
                <p>You can close this window and return to the terminal.</p>
                <p>Token has been saved to token.json</p>
              </body>
            </html>
          `);

          console.log('');
          console.log('='.repeat(60));
          console.log('✓ Authentication successful!');
          console.log('='.repeat(60));
          console.log('');
          console.log('Token saved to token.json');
          console.log('');
          console.log('Next steps:');
          console.log('1. Copy token.json to Docker container:');
          console.log('   docker cp token.json Google-Drive-Docs-mcp:/app/token.json');
          console.log('');
          console.log('2. Copy credentials.json to Docker container:');
          console.log('   docker cp credentials.json Google-Drive-Docs-mcp:/app/credentials.json');
          console.log('');
          console.log('3. Restart the container:');
          console.log('   docker restart Google-Drive-Docs-mcp');
          console.log('');

          // Close server
          setTimeout(() => {
            server.close();
            process.exit(0);
          }, 2000);
        }
      } catch (error) {
        console.error('Error in callback:', error.message);
        res.writeHead(500, { 'Content-Type': 'text/html' });
        res.end('<h1>Authentication Error</h1><p>' + error.message + '</p>');
      }
    });

    server.listen(3000, () => {
      console.log('Local auth server started on http://localhost:3000');
    });

  } catch (error) {
    console.error('');
    console.error('✗ Authentication failed:', error.message);
    console.error('');
    process.exit(1);
  }
}

renewAuthWeb();
