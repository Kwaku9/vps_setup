#!/usr/bin/env node

import { google } from 'googleapis';
import { authorize } from './dist/auth.js';

async function filterSheetData() {
  try {
    console.log('Authorizing Google API client...');
    const authClient = await authorize();

    const sheets = google.sheets({ version: 'v4', auth: authClient });

    // Using the test spreadsheet we just created
    const spreadsheetId = '1BGrAOyB35EMDTIiw6IBf4q7ywFlcg4-gmsBHZtbhCPU';
    const sourceTab = 'RawData';
    const filteredTab = 'FilteredData';

    console.log('');
    console.log('='.repeat(60));
    console.log('SheetDataFilter Agent - Data Cleaning');
    console.log('='.repeat(60));
    console.log('');

    // Step 1: Read source data
    console.log(`Reading data from '${sourceTab}' tab...`);
    const response = await sheets.spreadsheets.values.get({
      spreadsheetId: spreadsheetId,
      range: `${sourceTab}!A:Z`
    });

    const rows = response.data.values;
    if (!rows || rows.length === 0) {
      throw new Error('No data found in source tab');
    }

    console.log(`Found ${rows.length} rows (including header)`);

    // Step 2: Identify key columns
    const headers = rows[0];
    const bedroomsIdx = headers.findIndex(h =>
      h && h.toLowerCase().match(/bed(room)?s?/));
    const bathroomsIdx = headers.findIndex(h =>
      h && h.toLowerCase().match(/bath(room)?s?/));

    console.log(`Column mapping:`);
    console.log(`  - Bedrooms column: ${headers[bedroomsIdx]} (index ${bedroomsIdx})`);
    console.log(`  - Bathrooms column: ${headers[bathroomsIdx]} (index ${bathroomsIdx})`);
    console.log('');

    if (bedroomsIdx === -1 || bathroomsIdx === -1) {
      throw new Error('Could not find bedrooms or bathrooms columns');
    }

    // Step 3: Apply filtering logic
    console.log('Applying filter rules:');
    console.log('  - Remove rows where Bedrooms = 1');
    console.log('  - Remove rows where Bathrooms = 1');
    console.log('');

    const headerRow = rows[0];
    const dataRows = rows.slice(1);
    const filteredRows = [headerRow]; // Start with header

    let removedCount = 0;
    let keptCount = 0;

    for (const row of dataRows) {
      const bedrooms = parseInt(row[bedroomsIdx]) || 0;
      const bathrooms = parseInt(row[bathroomsIdx]) || 0;

      // Keep row if BOTH bedrooms != 1 AND bathrooms != 1
      if (bedrooms !== 1 && bathrooms !== 1) {
        filteredRows.push(row);
        keptCount++;
      } else {
        removedCount++;
      }
    }

    console.log(`Filtering results:`);
    console.log(`  - Total input rows: ${dataRows.length}`);
    console.log(`  - Rows removed: ${removedCount}`);
    console.log(`  - Rows kept: ${keptCount}`);
    console.log('');

    // Step 4: Create FilteredData tab if it doesn't exist
    console.log(`Creating '${filteredTab}' tab...`);

    try {
      // Try to add the new sheet
      await sheets.spreadsheets.batchUpdate({
        spreadsheetId: spreadsheetId,
        requestBody: {
          requests: [{
            addSheet: {
              properties: {
                title: filteredTab
              }
            }
          }]
        }
      });
      console.log(`Created new tab: ${filteredTab}`);
    } catch (error) {
      if (error.message.includes('already exists')) {
        console.log(`Tab '${filteredTab}' already exists, will overwrite`);
        // Clear existing data
        await sheets.spreadsheets.values.clear({
          spreadsheetId: spreadsheetId,
          range: `${filteredTab}!A:Z`
        });
      } else {
        throw error;
      }
    }

    // Step 5: Write filtered data to new tab
    console.log('Writing filtered data...');
    await sheets.spreadsheets.values.update({
      spreadsheetId: spreadsheetId,
      range: `${filteredTab}!A1`,
      valueInputOption: 'RAW',
      requestBody: {
        values: filteredRows
      }
    });

    // Step 6: Format the header row in filtered tab
    console.log('Formatting header row...');
    const sheetList = await sheets.spreadsheets.get({
      spreadsheetId: spreadsheetId,
      fields: 'sheets.properties'
    });

    const filteredSheetId = sheetList.data.sheets.find(
      s => s.properties.title === filteredTab
    ).properties.sheetId;

    await sheets.spreadsheets.batchUpdate({
      spreadsheetId: spreadsheetId,
      requestBody: {
        requests: [
          {
            updateSheetProperties: {
              properties: {
                sheetId: filteredSheetId,
                gridProperties: {
                  frozenRowCount: 1
                }
              },
              fields: 'gridProperties.frozenRowCount'
            }
          },
          {
            repeatCell: {
              range: {
                sheetId: filteredSheetId,
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
    console.log('✓ Filtering Complete!');
    console.log('='.repeat(60));
    console.log('');
    console.log(`Spreadsheet URL: https://docs.google.com/spreadsheets/d/${spreadsheetId}/edit`);
    console.log(`Source tab: ${sourceTab} (${dataRows.length} rows)`);
    console.log(`Filtered tab: ${filteredTab} (${keptCount} rows)`);
    console.log(`Rows removed: ${removedCount}`);
    console.log(`Filter criteria applied:`);
    console.log(`  - Removed rows with Bedrooms = 1`);
    console.log(`  - Removed rows with Bathrooms = 1`);
    console.log('');

  } catch (error) {
    console.error('');
    console.error('✗ Error filtering data:', error.message);
    console.error('');
    throw error;
  }
}

filterSheetData();
