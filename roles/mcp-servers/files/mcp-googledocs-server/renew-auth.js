#!/usr/bin/env node

// Simple authentication renewal script for Google Docs MCP Server
// Run this locally (not in Docker) to get a fresh token.json

import { authorize } from './dist/auth.js';

console.log('='.repeat(60));
console.log('Google Docs MCP Server - Authentication Renewal');
console.log('='.repeat(60));
console.log('');
console.log('This script will help you re-authenticate with Google.');
console.log('');

async function renewAuth() {
  try {
    // Delete existing token to force re-authentication
    const fs = await import('fs/promises');
    try {
      await fs.unlink('./token.json');
      console.log('✓ Deleted old token.json');
    } catch (err) {
      console.log('ℹ No existing token.json found');
    }

    console.log('');
    console.log('Starting authentication flow...');
    console.log('');

    const client = await authorize();

    console.log('');
    console.log('='.repeat(60));
    console.log('✓ Authentication successful!');
    console.log('='.repeat(60));
    console.log('');
    console.log('New token.json has been created.');
    console.log('');
    console.log('Next steps:');
    console.log('1. Copy token.json to the Docker container:');
    console.log('   docker cp token.json Google-Drive-Docs-mcp:/app/token.json');
    console.log('');
    console.log('2. Restart the container:');
    console.log('   docker restart Google-Drive-Docs-mcp');
    console.log('');
    console.log('Your Google Sheets MCP server will now be authenticated!');
    console.log('');

  } catch (error) {
    console.error('');
    console.error('✗ Authentication failed:', error.message);
    console.error('');
    console.error('Please check:');
    console.error('- credentials.json exists and is valid');
    console.error('- You have internet connection');
    console.error('- You completed the browser authorization');
    process.exit(1);
  }
}

renewAuth();
