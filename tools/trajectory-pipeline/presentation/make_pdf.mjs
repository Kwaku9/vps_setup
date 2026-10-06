import puppeteer from '/home/general/.local/share/fnm/node-versions/v24.15.0/installation/lib/node_modules/hyperframes/node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js';
import {resolve} from 'node:path';
const browser=await puppeteer.launch({executablePath:'/home/general/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome',headless:true,args:['--no-sandbox']});
try{
 const page=await browser.newPage();await page.setJavaScriptEnabled(false);
 await page.goto('file://'+resolve('read.html'),{waitUntil:'load'});
 await page.pdf({path:'public/trajectory-learning-guide.pdf',format:'A4',printBackground:true,preferCSSPageSize:true,displayHeaderFooter:true,headerTemplate:'<span></span>',footerTemplate:'<div style="font-size:9px;width:100%;text-align:center;color:#52675e">Trajectory Learning · <span class="pageNumber"></span> / <span class="totalPages"></span></div>'});
 await page.setViewport({width:390,height:844,isMobile:true,hasTouch:true,deviceScaleFactor:2});
 await page.goto((process.env.DECK_URL||'http://127.0.0.1:8447')+'/read.html?edition=reading-20261005',{waitUntil:'networkidle0'});
 const checks=await page.evaluate(()=>({sections:document.querySelectorAll('.chapter').length,scripts:document.scripts.length,iframes:document.querySelectorAll('iframe').length,horizontalOverflow:document.documentElement.scrollWidth>innerWidth,pdfLink:!!document.querySelector('a[href="trajectory-learning-guide.pdf"]')}));
 if(checks.sections!==32||checks.scripts!==0||checks.iframes!==0||checks.horizontalOverflow||!checks.pdfLink)throw Error(JSON.stringify(checks));
 await page.screenshot({path:'checks/reading-iphone.png'});
 console.log(JSON.stringify(checks));
}finally{await browser.close()}
