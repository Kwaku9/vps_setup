#!/usr/bin/env node

import { google } from 'googleapis';
import { authorize } from './dist/auth.js';

// Scoring functions for property features
function scoreProperty(title, description, location, category) {
  let score = 0;
  const combinedText = `${title} ${description} ${location}`.toLowerCase();

  // Location & View Criteria (45 points max)

  // Coastal location (20 points)
  const coastalRegions = ['condado', 'ocean park', 'dorado', 'isla verde', 'luquillo',
                          'rincon', 'aguadilla', 'piñones', 'vieques', 'culebra'];
  if (coastalRegions.some(region => location.toLowerCase().includes(region)) ||
      /\b(coastal|coast|frente al mar|en la costa|cerca del mar)\b/i.test(combinedText)) {
    score += 20;
  }

  // Ocean view (15 points)
  if (/\b(ocean view|sea view|water view|oceanfront|vista al mar|vista del océano|frente al océano)\b/i.test(combinedText)) {
    score += 15;
  }

  // Near beach (10 points)
  if (/\b(near beach|walking distance.*beach|steps.*beach|beach access|a la playa|cerca de la playa|acceso a la playa)\b/i.test(combinedText)) {
    score += 10;
  }

  // Energy & Utilities Criteria (30 points max)

  // Tesla battery (15 points)
  if (/\b(tesla battery|powerwall|tesla powerwall|solar battery)\b/i.test(combinedText)) {
    score += 15;
  }

  // Generator (10 points)
  if (/\b(generator|backup generator|standby generator|generador|planta eléctrica)\b/i.test(combinedText)) {
    score += 10;
  }

  // Water cistern (5 points)
  if (/\b(water cistern|water reservoir|water tank|cistern|cisterna|tanque de agua)\b/i.test(combinedText)) {
    score += 5;
  }

  // Property Features Criteria (10 points max)

  // Backyard (5 points)
  if (/\b(backyard|back yard|yard|outdoor space|patio|jardín trasero)\b/i.test(combinedText)) {
    score += 5;
  }

  // Kitchen appliances (5 points)
  if (/\b(oven|stove|range|cooktop|horno|estufa|cocina)\b/i.test(combinedText)) {
    score += 5;
  }

  // Property Type Criteria (10 points max)
  const propertyType = category.toLowerCase();

  // Single family (5 points)
  if (/\b(single family|single-family|single family home)\b/i.test(propertyType)) {
    score += 5;
  }

  // Detached house (5 points)
  if (/\b(detached house|detached|detached home|casa)\b/i.test(propertyType)) {
    score += 5;
  }

  return score;
}

async function rankListings() {
  try {
    console.log('Authorizing Google API client...');
    const authClient = await authorize();
    const sheets = google.sheets({ version: 'v4', auth: authClient });

    const spreadsheetId = '1BGrAOyB35EMDTIiw6IBf4q7ywFlcg4-gmsBHZtbhCPU';
    const sourceTab = 'FilteredData';
    const rankedTab = 'RankedData';

    console.log('');
    console.log('='.repeat(60));
    console.log('ListingRanker Agent - Multi-Tier Ranking');
    console.log('='.repeat(60));
    console.log('');

    // Step 1: Read the filtered data
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

    // Step 2: Identify columns
    const headers = rows[0];
    const titleIdx = headers.findIndex(h => h && h.toLowerCase().includes('title'));
    const descriptionIdx = headers.findIndex(h => h && h.toLowerCase().match(/description|details|property_details/));
    const locationIdx = headers.findIndex(h => h && h.toLowerCase().includes('location'));
    const categoryIdx = headers.findIndex(h => h && h.toLowerCase().includes('category'));
    const furnishedIdx = headers.findIndex(h => h && h.toLowerCase().includes('furnished'));
    const leaseIdx = headers.findIndex(h => h && h.toLowerCase().includes('12 month lease'));

    console.log(`Column mapping:`);
    console.log(`  - Title: index ${titleIdx}`);
    console.log(`  - Description: index ${descriptionIdx}`);
    console.log(`  - Location: index ${locationIdx}`);
    console.log(`  - Category: index ${categoryIdx}`);
    console.log(`  - Furnished: index ${furnishedIdx}`);
    console.log(`  - 12 Month Lease: index ${leaseIdx}`);

    // Step 3: Add Preference_Score column
    let scoreIdx = headers.findIndex(h => h && h.toLowerCase().includes('preference_score'));
    if (scoreIdx === -1) {
      headers.push('Preference_Score');
      scoreIdx = headers.length - 1;
      console.log(`  - Added Preference_Score: index ${scoreIdx}`);
    }
    console.log('');

    // Step 4: Calculate scores and filter out Furnished = "No"
    console.log('Calculating preference scores...');
    const dataRows = rows.slice(1);
    const scoredRows = [];
    let removedCount = 0;

    for (const row of dataRows) {
      // Ensure row has enough columns
      while (row.length < headers.length) {
        row.push('');
      }

      // Filter out Furnished = "No"
      if (row[furnishedIdx] === 'No') {
        removedCount++;
        continue;
      }

      const title = row[titleIdx] || '';
      const description = row[descriptionIdx] || '';
      const location = row[locationIdx] || '';
      const category = row[categoryIdx] || '';

      const score = scoreProperty(title, description, location, category);
      row[scoreIdx] = score;

      scoredRows.push(row);
    }

    console.log(`Removed ${removedCount} properties with Furnished = "No"`);
    console.log(`Scoring ${scoredRows.length} properties...`);
    console.log('');

    // Step 5: Multi-tier sorting
    console.log('Applying multi-tier sorting:');
    console.log('  Level 1: Furnished status (Yes > Unknown)');
    console.log('  Level 2: Lease flexibility (No/Unknown > Yes)');
    console.log('  Level 3: Preference score (highest first)');
    console.log('');

    scoredRows.sort((a, b) => {
      // Level 1: Furnished (Yes before Unknown)
      if (a[furnishedIdx] !== b[furnishedIdx]) {
        if (a[furnishedIdx] === 'Yes') return -1;
        if (b[furnishedIdx] === 'Yes') return 1;
      }

      // Level 2: Lease flexibility (No/Unknown before Yes)
      const aFlexible = a[leaseIdx] !== 'Yes';
      const bFlexible = b[leaseIdx] !== 'Yes';
      if (aFlexible !== bFlexible) {
        return aFlexible ? -1 : 1;
      }

      // Level 3: Preference score (highest first)
      return (b[scoreIdx] || 0) - (a[scoreIdx] || 0);
    });

    // Step 6: Build ranked data with visual separators
    console.log('Building ranked data with visual separators...');
    const rankedData = [headers];

    // Calculate statistics
    const stats = {
      furnished_yes: { total: 0, flexible: 0, locked: 0, scores: [] },
      furnished_unknown: { total: 0, flexible: 0, locked: 0, scores: [] }
    };

    let currentFurnished = null;
    let currentLease = null;

    for (const row of scoredRows) {
      const furnished = row[furnishedIdx];
      const lease = row[leaseIdx];
      const score = row[scoreIdx];

      // Track statistics
      const statKey = furnished === 'Yes' ? 'furnished_yes' : 'furnished_unknown';
      stats[statKey].total++;
      stats[statKey].scores.push(score);
      if (lease !== 'Yes') {
        stats[statKey].flexible++;
      } else {
        stats[statKey].locked++;
      }

      // Add section separator when Furnished status changes
      if (currentFurnished !== furnished) {
        const separatorRow = new Array(headers.length).fill('');
        separatorRow[0] = `═══ FURNISHED: ${furnished.toUpperCase()} ═══`;
        rankedData.push(separatorRow);
        currentFurnished = furnished;
        currentLease = null; // Reset lease tracker
      }

      // Add subsection separator when lease status changes within same furnished group
      if (currentLease !== lease) {
        const subseparatorRow = new Array(headers.length).fill('');
        const leaseLabel = lease === 'Yes' ? '12 Month Required' : 'Flexible Lease';
        subseparatorRow[0] = `─── ${leaseLabel} ───`;
        rankedData.push(subseparatorRow);
        currentLease = lease;
      }

      rankedData.push(row);
    }

    // Step 7: Create RankedData tab
    console.log(`Creating '${rankedTab}' tab...`);

    try {
      await sheets.spreadsheets.batchUpdate({
        spreadsheetId: spreadsheetId,
        requestBody: {
          requests: [{
            addSheet: {
              properties: {
                title: rankedTab
              }
            }
          }]
        }
      });
      console.log(`Created new tab: ${rankedTab}`);
    } catch (error) {
      if (error.message.includes('already exists')) {
        console.log(`Tab '${rankedTab}' already exists, clearing it...`);
        await sheets.spreadsheets.values.clear({
          spreadsheetId: spreadsheetId,
          range: `${rankedTab}!A:Z`
        });
      } else {
        throw error;
      }
    }

    // Step 8: Write ranked data
    console.log('Writing ranked data...');
    await sheets.spreadsheets.values.update({
      spreadsheetId: spreadsheetId,
      range: `${rankedTab}!A1`,
      valueInputOption: 'RAW',
      requestBody: {
        values: rankedData
      }
    });

    // Step 9: Apply formatting to separators
    console.log('Applying visual formatting to separators...');
    const sheetList = await sheets.spreadsheets.get({
      spreadsheetId: spreadsheetId,
      fields: 'sheets.properties'
    });

    const rankedSheetId = sheetList.data.sheets.find(
      s => s.properties.title === rankedTab
    ).properties.sheetId;

    // Find separator rows and format them
    const formatRequests = [];
    for (let i = 0; i < rankedData.length; i++) {
      const row = rankedData[i];
      if (row[0] && row[0].startsWith('═══')) {
        // Main separator (Furnished groups) - Bold, larger font, colored background, LEFT aligned
        formatRequests.push({
          repeatCell: {
            range: {
              sheetId: rankedSheetId,
              startRowIndex: i,
              endRowIndex: i + 1
            },
            cell: {
              userEnteredFormat: {
                backgroundColor: { red: 0.2, green: 0.4, blue: 0.8 },
                textFormat: {
                  bold: true,
                  fontSize: 12,
                  foregroundColor: { red: 1, green: 1, blue: 1 }
                },
                horizontalAlignment: 'LEFT'
              }
            },
            fields: 'userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)'
          }
        });
      } else if (row[0] && row[0].startsWith('───')) {
        // Subseparator (Lease groups) - Italic, smaller font, light gray background, LEFT aligned
        formatRequests.push({
          repeatCell: {
            range: {
              sheetId: rankedSheetId,
              startRowIndex: i,
              endRowIndex: i + 1
            },
            cell: {
              userEnteredFormat: {
                backgroundColor: { red: 0.9, green: 0.9, blue: 0.9 },
                textFormat: {
                  italic: true,
                  fontSize: 10
                },
                horizontalAlignment: 'LEFT'
              }
            },
            fields: 'userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)'
          }
        });
      }
    }

    // Format header row
    formatRequests.push({
      updateSheetProperties: {
        properties: {
          sheetId: rankedSheetId,
          gridProperties: {
            frozenRowCount: 1
          }
        },
        fields: 'gridProperties.frozenRowCount'
      }
    });

    formatRequests.push({
      repeatCell: {
        range: {
          sheetId: rankedSheetId,
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
    });

    await sheets.spreadsheets.batchUpdate({
      spreadsheetId: spreadsheetId,
      requestBody: {
        requests: formatRequests
      }
    });

    // Calculate final statistics
    const allScores = [...stats.furnished_yes.scores, ...stats.furnished_unknown.scores];
    const avgScore = allScores.reduce((a, b) => a + b, 0) / allScores.length;
    const maxScore = Math.max(...allScores);
    const minScore = Math.min(...allScores);

    console.log('');
    console.log('='.repeat(60));
    console.log('✓ Ranking Complete!');
    console.log('='.repeat(60));
    console.log('');
    console.log(`Spreadsheet URL: https://docs.google.com/spreadsheets/d/${spreadsheetId}/edit`);
    console.log(`Source tab: ${sourceTab}`);
    console.log(`Ranked tab: ${rankedTab}`);
    console.log('');
    console.log('Ranking Statistics:');
    console.log(`  Total properties ranked: ${scoredRows.length}`);
    console.log(`  Properties removed (Furnished=No): ${removedCount}`);
    console.log('');
    console.log('  FURNISHED = YES (${stats.furnished_yes.total} properties)');
    console.log(`    - Flexible lease: ${stats.furnished_yes.flexible}`);
    console.log(`    - 12-month required: ${stats.furnished_yes.locked}`);
    console.log('');
    console.log(`  FURNISHED = UNKNOWN (${stats.furnished_unknown.total} properties)`);
    console.log(`    - Flexible lease: ${stats.furnished_unknown.flexible}`);
    console.log(`    - 12-month required: ${stats.furnished_unknown.locked}`);
    console.log('');
    console.log('Preference Scores:');
    console.log(`  Highest: ${maxScore} points`);
    console.log(`  Lowest: ${minScore} points`);
    console.log(`  Average: ${avgScore.toFixed(1)} points`);
    console.log('');

  } catch (error) {
    console.error('');
    console.error('✗ Error ranking listings:', error.message);
    console.error('');
    throw error;
  }
}

rankListings();
