console.log('--- Script execution started: upload-csv.js ---');
#!/usr/bin/env node

import { google } from 'googleapis';
import { authorize } from './dist/auth.js';
import * as fs from 'fs/promises';
import { parse } from 'csv-parse/sync';

async function uploadCSVToSheets() {
  try {
    console.log('Authorizing Google API client...');
    const authClient = await authorize();

    const sheets = google.sheets({ version: 'v4', auth: authClient });
    const drive = google.drive({ version: 'v3', auth: authClient });

    // Read CSV file
    console.log('Reading CSV file...');
    const csvPath = '/workspace/pycharm-projects/ScrapyExtractor/output.csv';
    const csvContent = await fs.readFile(csvPath, 'utf-8');

    // Parse CSV
    console.log('Parsing CSV data...');
    const records = parse(csvContent, {
      skip_empty_lines: true,
      relax_column_count: true
    });

    console.log(`Parsed ${records.length} rows (including header)`);

    // Create new spreadsheet
    console.log('Creating new Google Sheet...');
    const createResponse = await sheets.spreadsheets.create({
      requestBody: {
        properties: {
          title: 'Real Estate Listings'
        },
        sheets: [{
          properties: {
            title: 'RawData'
          }
        }]
      }
    });

    const spreadsheetId = createResponse.data.spreadsheetId;
    const spreadsheetUrl = createResponse.data.spreadsheetUrl;

    console.log(`Created spreadsheet: ${spreadsheetId}`);
    console.log(`URL: ${spreadsheetUrl}`);

    // Upload data to the sheet
    console.log('Uploading CSV data to sheet...');
    await sheets.spreadsheets.values.update({
      spreadsheetId: spreadsheetId,
      range: 'RawData!A1',
      valueInputOption: 'RAW',
      requestBody: {
        values: records
      }
    });

    // Format the header row
    console.log('Formatting header row...');
    const sheetId = createResponse.data.sheets[0].properties.sheetId;

    await sheets.spreadsheets.batchUpdate({
      spreadsheetId: spreadsheetId,
      requestBody: {
        requests: [
          // Freeze the top row
          {
            updateSheetProperties: {
              properties: {
                sheetId: sheetId,
                gridProperties: {
                  frozenRowCount: 1
                }
              },
              fields: 'gridProperties.frozenRowCount'
            }
          },
          // Make header row bold and increase font size to 12
          {
            repeatCell: {
              range: {
                sheetId: sheetId,
                startRowIndex: 0,
                endRowIndex: 1
              },
              cell: {
                userEnteredFormat: {
                  textFormat: {
                    bold: true,
                    fontSize: 12
                  }
                }
              },
              fields: 'userEnteredFormat(textFormat)'
            }
          }
        ]
      }
    });

    console.log('');
    console.log('='.repeat(60));
    console.log('✓ CSV Upload Successful!');
    console.log('='.repeat(60));
    console.log('');
    console.log(`Spreadsheet Title: Real Estate Listings`);
    console.log(`Spreadsheet ID: ${spreadsheetId}`);
    console.log(`Spreadsheet URL: ${spreadsheetUrl}`);
    console.log(`Rows uploaded: ${records.length} (including header)`);
    console.log('Header formatting applied: Frozen, Bold, Font Size 12');
    console.log('');

    return { spreadsheetId, spreadsheetUrl, rowCount: records.length };

  } catch (error) {
    console.error('');
    console.error('✗ An error occurred during the CSV upload process:', error);
    if (error.stack) {
      console.error('Stack Trace:', error.stack);
    }
    console.error('');
    process.exit(1); // Exit with a non-zero code to indicate failure
  }
}

uploadCSVToSheets().then(() => {
  console.log('--- Script execution finished: upload-csv.js ---');
});
