#!/usr/bin/env node

import { google } from 'googleapis';
import { authorize } from './dist/auth.js';

// Analysis functions based on Claude's language understanding logic
function analyzeLease(description) {
  const text = description.toLowerCase();

  // Positive indicators for 12-month lease requirement
  const leaseIndicators = [
    /12[\s-]?month/i,
    /one[\s-]?year[\s-]?(only|minimum|lease)/i,
    /annual[\s-]?lease/i,
    /12[\s-]?meses/i,
    /año[\s-]?completo/i,
    /contrato[\s-]?anual/i,
    /minimum[\s-]?1[\s-]?year/i
  ];

  // Check for lease indicators
  for (const pattern of leaseIndicators) {
    if (pattern.test(description)) {
      return 'Yes';
    }
  }

  // Negative indicators
  const noLeaseIndicators = [
    /month[\s-]?to[\s-]?month/i,
    /mes[\s-]?a[\s-]?mes/i,
    /short[\s-]?term/i,
    /corto[\s-]?plazo/i
  ];

  for (const pattern of noLeaseIndicators) {
    if (pattern.test(description)) {
      return 'No';
    }
  }

  return 'Unknown';
}

function analyzeFurnished(description) {
  const text = description.toLowerCase();

  // Furnished indicators (English)
  const furnishedYes = [
    /\bfurnished\b/i,
    /fully[\s-]?furnished/i,
    /completamente[\s-]?amueblad/i,
    /\bamueblad/i,
    /con[\s-]?muebles/i,
    /incluye[\s-]?muebles/i
  ];

  // Unfurnished indicators
  const furnishedNo = [
    /unfurnished/i,
    /not[\s-]?furnished/i,
    /sin[\s-]?amueblar/i,
    /no[\s-]?amueblad/i,
    /appliances[\s-]?only/i,
    /solo[\s-]?electro/i,
    /enseres[\s-]?solamente/i
  ];

  // Check furnished
  for (const pattern of furnishedYes) {
    if (pattern.test(description)) {
      return 'Yes';
    }
  }

  // Check unfurnished
  for (const pattern of furnishedNo) {
    if (pattern.test(description)) {
      return 'No';
    }
  }

  return 'Unknown';
}

async function enrichListings() {
  try {
    console.log('Authorizing Google API client...');
    const authClient = await authorize();
    const sheets = google.sheets({ version: 'v4', auth: authClient });

    const spreadsheetId = '1BGrAOyB35EMDTIiw6IBf4q7ywFlcg4-gmsBHZtbhCPU';
    const targetTab = 'FilteredData';

    console.log('');
    console.log('='.repeat(60));
    console.log('ListingEnrichmentAgent - Data Enrichment');
    console.log('='.repeat(60));
    console.log('');

    // Step 1: Read the filtered data
    console.log(`Reading data from '${targetTab}' tab...`);
    const response = await sheets.spreadsheets.values.get({
      spreadsheetId: spreadsheetId,
      range: `${targetTab}!A:Z`
    });

    const rows = response.data.values;
    if (!rows || rows.length === 0) {
      throw new Error('No data found in target tab');
    }

    console.log(`Found ${rows.length} rows (including header)`);

    // Step 2: Identify columns
    const headers = rows[0];
    const titleIdx = headers.findIndex(h =>
      h && h.toLowerCase().match(/title/));
    const descriptionIdx = headers.findIndex(h =>
      h && h.toLowerCase().match(/description|details|property_details/));

    console.log(`Column mapping:`);
    console.log(`  - Title column: ${headers[titleIdx]} (index ${titleIdx})`);
    console.log(`  - Description column: ${headers[descriptionIdx]} (index ${descriptionIdx})`);
    console.log('');

    if (descriptionIdx === -1) {
      throw new Error('Could not find description column');
    }

    // Step 3: Add enrichment columns if they don't exist
    let leaseIdx = headers.findIndex(h => h && h.toLowerCase().includes('12 month lease'));
    let furnishedIdx = headers.findIndex(h => h && h.toLowerCase().includes('furnished'));

    if (leaseIdx === -1) {
      headers.push('12 month lease');
      leaseIdx = headers.length - 1;
      console.log(`Added new column: '12 month lease' (index ${leaseIdx})`);
    }

    if (furnishedIdx === -1) {
      headers.push('furnished');
      furnishedIdx = headers.length - 1;
      console.log(`Added new column: 'furnished' (index ${furnishedIdx})`);
    }

    console.log('');
    console.log('Starting enrichment analysis...');
    console.log('Analyzing property descriptions using pattern matching...');
    console.log('');

    // Step 4: Enrich each row
    const enrichedRows = [headers];
    const dataRows = rows.slice(1);

    let leaseYes = 0, leaseNo = 0, leaseUnknown = 0;
    let furnishedYes = 0, furnishedNo = 0, furnishedUnknown = 0;

    for (let i = 0; i < dataRows.length; i++) {
      const row = dataRows[i];
      const title = row[titleIdx] || '';
      const description = row[descriptionIdx] || '';

      // Ensure row has enough columns
      while (row.length < headers.length) {
        row.push('');
      }

      // Combine title and description for more comprehensive analysis
      const combinedText = `${title} ${description}`;

      if (!combinedText.trim()) {
        row[leaseIdx] = 'Unknown';
        row[furnishedIdx] = 'Unknown';
        leaseUnknown++;
        furnishedUnknown++;
        enrichedRows.push(row);
        continue;
      }

      // Analyze using pattern matching functions on combined text
      const leaseResult = analyzeLease(combinedText);
      const furnishedResult = analyzeFurnished(combinedText);

      row[leaseIdx] = leaseResult;
      row[furnishedIdx] = furnishedResult;

      // Track statistics
      if (leaseResult === 'Yes') leaseYes++;
      else if (leaseResult === 'No') leaseNo++;
      else leaseUnknown++;

      if (furnishedResult === 'Yes') furnishedYes++;
      else if (furnishedResult === 'No') furnishedNo++;
      else furnishedUnknown++;

      enrichedRows.push(row);

      // Progress indicator
      if ((i + 1) % 50 === 0) {
        console.log(`  Processed ${i + 1}/${dataRows.length} properties...`);
      }
    }

    // Step 5: Write enriched data back
    console.log('');
    console.log('Writing enriched data back to sheet...');
    await sheets.spreadsheets.values.clear({
      spreadsheetId: spreadsheetId,
      range: `${targetTab}!A:Z`
    });

    await sheets.spreadsheets.values.update({
      spreadsheetId: spreadsheetId,
      range: `${targetTab}!A1`,
      valueInputOption: 'RAW',
      requestBody: {
        values: enrichedRows
      }
    });

    console.log('');
    console.log('='.repeat(60));
    console.log('✓ Enrichment Complete!');
    console.log('='.repeat(60));
    console.log('');
    console.log(`Spreadsheet URL: https://docs.google.com/spreadsheets/d/${spreadsheetId}/edit`);
    console.log(`Tab name: ${targetTab}`);
    console.log(`Rows processed: ${dataRows.length}`);
    console.log(`Columns enriched: ['12 month lease', 'furnished']`);
    console.log('');
    console.log('Analysis Results:');
    console.log(`  12 Month Lease:`);
    console.log(`    - Yes: ${leaseYes}`);
    console.log(`    - No: ${leaseNo}`);
    console.log(`    - Unknown: ${leaseUnknown}`);
    console.log(`  Furnished:`);
    console.log(`    - Yes: ${furnishedYes}`);
    console.log(`    - No: ${furnishedNo}`);
    console.log(`    - Unknown: ${furnishedUnknown}`);
    console.log('');

    return {
      spreadsheetId,
      tab: targetTab,
      rowsProcessed: dataRows.length,
      lease: { yes: leaseYes, no: leaseNo, unknown: leaseUnknown },
      furnished: { yes: furnishedYes, no: furnishedNo, unknown: furnishedUnknown }
    };

  } catch (error) {
    console.error('');
    console.error('✗ Error enriching data:', error.message);
    console.error('');
    throw error;
  }
}

enrichListings();
