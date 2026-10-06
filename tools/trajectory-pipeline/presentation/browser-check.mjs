import puppeteer from '/home/general/.local/share/fnm/node-versions/v24.15.0/installation/lib/node_modules/hyperframes/node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js';
import fs from 'node:fs';
const browser=await puppeteer.launch({executablePath:'/home/general/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome',headless:true,args:['--no-sandbox']});
const output={};fs.mkdirSync('checks',{recursive:true});
try{
for(const [name,viewport] of Object.entries({desktop:{width:1440,height:900},iphone:{width:390,height:844,isMobile:true,hasTouch:true,deviceScaleFactor:2}})){
 const page=await browser.newPage();await page.setViewport(viewport);const errors=[];page.on('pageerror',e=>errors.push(String(e)));page.on('response',r=>{if(r.status()>=400)errors.push(r.status()+' '+r.url())});
 await page.goto(process.env.DECK_URL||'http://127.0.0.1:18767/',{waitUntil:'networkidle0'});
 await page.waitForFunction(()=>document.querySelector('hyperframes-slideshow').controller?.counter.total===32);
 await page.waitForFunction(()=>!!document.querySelector('hyperframes-player').iframeElement?.contentWindow?.__player);
 const playerFrame=()=>page.frames().find(f=>f.url().includes('/composition/')||f.url()==='about:srcdoc');
 const frame=playerFrame();const slides=[];
 for(let i=0;i<32;i++){
  await page.evaluate(i=>document.querySelector('hyperframes-slideshow').controller.goToSlide(i),i);
  await new Promise(r=>setTimeout(r,35));
  await frame.waitForFunction(id=>getComputedStyle(document.getElementById(id)).visibility==='visible',{},'slide-'+String(i+1).padStart(2,'0'));
  const layout=await frame.evaluate(()=>{const el=[...document.querySelectorAll('.scene')].find(x=>getComputedStyle(x).visibility==='visible');const root=el.getBoundingClientRect();const bad=[];for(const x of el.querySelectorAll('h1,h2,p,footer,article,button')){const r=x.getBoundingClientRect();if(r.bottom>root.bottom-5||r.right>root.right+1||r.x<root.x-1||(getComputedStyle(x).overflow==='hidden'&&x.scrollHeight>x.clientHeight+2))bad.push({tag:x.tagName,text:x.innerText.slice(0,70),box:{x:r.x,y:r.y,w:r.width,h:r.height},scroll:x.scrollHeight,client:x.clientHeight});}const f=el.querySelector('footer').getBoundingClientRect();const v=el.querySelector('.visual').getBoundingClientRect();return {id:el.id,width:root.width,height:root.height,bad,footerY:f.y,visualBottom:v.bottom};});slides.push(layout);
  if([0,5,11,17,21,24,31].includes(i))await page.screenshot({path:`checks/${name}-${i+1}.png`});
 }
 // Test shared next/previous and the explanatory mask interaction.
 await page.evaluate(()=>document.querySelector('hyperframes-slideshow').controller.goToSlide(17));
 const localBox=await frame.$eval('.kind-mask .mask-toggle',e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height};});
 const point=await page.$eval('hyperframes-player',(e,b)=>{const f=e.iframeElement,r=f.getBoundingClientRect();return {x:r.x+(b.x+b.w/2)*r.width/f.offsetWidth,y:r.y+(b.y+b.h/2)*r.height/f.offsetHeight};},localBox);
 if(name==='iphone')await page.touchscreen.tap(point.x,point.y);else await page.mouse.click(point.x,point.y);
 const mask=await frame.$eval('.kind-mask',e=>e.classList.contains('show-mask'));
 await page.evaluate(()=>document.querySelector('hyperframes-slideshow').controller.goToSlide(0));
 await page.keyboard.press('ArrowRight');const next=await page.$eval('hyperframes-slideshow',e=>e.controller.counter.index);
 await page.keyboard.press('ArrowLeft');const prev=await page.$eval('hyperframes-slideshow',e=>e.controller.counter.index);
 // The iframe gesture bridge uses the same shared controller.
 await frame.evaluate(()=>parent.postMessage({source:'trajectory-gesture',type:'next'},location.origin));await new Promise(r=>setTimeout(r,80));
 const swipe=await page.$eval('hyperframes-slideshow',e=>e.controller.counter.index);
 const visibleAfterSwipe=await frame.evaluate(()=>[...document.querySelectorAll('.scene')].find(e=>getComputedStyle(e).visibility==='visible').id);
 let physicalSwipe=null;
 if(name==='iphone'){
 const client=await page.createCDPSession();await client.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:320,y:460}]});await client.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:120,y:460}]});await client.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await new Promise(r=>setTimeout(r,150));physicalSwipe=await page.$eval('hyperframes-slideshow',e=>e.controller.counter.index);
 }
 output[name]={errors,slides,mask,next,prev,swipe,visibleAfterSwipe,physicalSwipe};await page.close();
}
fs.writeFileSync('checks/browser-report.json',JSON.stringify(output,null,2));console.log(JSON.stringify(Object.fromEntries(Object.entries(output).map(([k,v])=>[k,{errors:v.errors,badSlides:v.slides.filter(s=>s.bad.length),mask:v.mask,next:v.next,prev:v.prev,swipe:v.swipe,visibleAfterSwipe:v.visibleAfterSwipe,physicalSwipe:v.physicalSwipe}]))));
if(Object.values(output).some(v=>v.errors.length||v.slides.some(s=>s.bad.length)||!v.mask||v.next!==2||v.prev!==1||v.swipe!==2||v.visibleAfterSwipe!=='slide-02'))process.exitCode=1;
}finally{await browser.close()}
