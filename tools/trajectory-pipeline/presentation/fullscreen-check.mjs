import puppeteer from '/home/general/.local/share/fnm/node-versions/v24.15.0/installation/lib/node_modules/hyperframes/node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js';
import fs from 'node:fs';
const browser=await puppeteer.launch({executablePath:'/home/general/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome',headless:true,args:['--no-sandbox']});
try {
 const page=await browser.newPage();await page.setViewport({width:390,height:844,isMobile:true,hasTouch:true,deviceScaleFactor:2});
 const errors=[];page.on('pageerror',e=>errors.push(String(e)));
 await page.goto(process.env.DECK_URL||'http://127.0.0.1:8447/slideshow.html',{waitUntil:'networkidle0'});
 await page.waitForFunction(()=>document.querySelector('hyperframes-slideshow').controller?.counter.total===32);
 await new Promise(r=>setTimeout(r,400));
 await page.evaluate(()=>document.querySelector('hyperframes-slideshow').focus());await page.keyboard.press('f');
 await page.waitForFunction(()=>!document.getElementById('exit-fullscreen').hidden);
 console.log(await page.evaluate(()=>({fullscreen:!!document.fullscreenElement,expanded:document.querySelector('hyperframes-slideshow').dataset.expanded}))); 
 const nativeBox=await page.$eval('#exit-fullscreen',e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,inView:r.x>=0&&r.y>=0&&r.right<=innerWidth&&r.bottom<=innerHeight}});
 await page.screenshot({path:'checks/fullscreen-iphone.png'});
 await page.touchscreen.tap(nativeBox.x+nativeBox.w/2,nativeBox.y+nativeBox.h/2);
 await page.waitForFunction(()=>!document.fullscreenElement&&document.getElementById('exit-fullscreen').hidden);
 // Older WebKit or a denied API must still have an explicit way back.
 await page.evaluate(()=>{const d=document.querySelector('hyperframes-slideshow');d.requestFullscreen=()=>Promise.reject(new Error('Not supported'));d.webkitRequestFullscreen=undefined;});
 await page.evaluate(()=>document.querySelector('hyperframes-slideshow').focus());await page.keyboard.press('f');await page.waitForFunction(()=>document.querySelector('hyperframes-slideshow').dataset.expanded==='true'&&!document.getElementById('exit-fullscreen').hidden);
 const fallbackBox=await page.$eval('#exit-fullscreen',e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}});
 await page.touchscreen.tap(fallbackBox.x+fallbackBox.w/2,fallbackBox.y+fallbackBox.h/2);
 await page.waitForFunction(()=>!document.querySelector('hyperframes-slideshow').dataset.expanded&&document.getElementById('exit-fullscreen').hidden);
 await page.evaluate(()=>document.querySelector('hyperframes-slideshow').focus());await page.keyboard.press('f');await page.waitForFunction(()=>!document.getElementById('exit-fullscreen').hidden);await page.keyboard.press('Escape');await page.waitForFunction(()=>document.getElementById('exit-fullscreen').hidden);
 const result={nativeEnterExit:true,deniedApiFallbackEnterExit:true,escapeExit:true,nativeBox,errors};fs.writeFileSync('checks/fullscreen-report.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));if(errors.length||!nativeBox.inView||nativeBox.h<44)process.exitCode=1;
} finally {await browser.close();}
