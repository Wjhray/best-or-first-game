const assert=require("node:assert/strict");
const {chromium}=require("playwright");
const BASE="http://127.0.0.1:8765";
const CASES=[["官宦世家",67,"官府來訪"],["軍人世家",68,"軍營徵募"],["豪門士族",69,"士族家議"],["商賈之家",70,"商路貨帳"],["農家子弟",6,"田地收成不佳"],["工匠之家",71,"匠作求援"],["寒門讀書人",72,"寒門借書"],["流民或孤兒",73,"流民的線索"]];
async function selectEvent(page,origin,id){
 return page.evaluate(({origin,id})=>{
  game.origin=origin;game.year=209;game.age=39;game.month=1;game.lifeQuarters=0;game.activeEventId=null;game.eventDone=[];game.eventCooldowns={};
  const e=eventCatalog.find(x=>x.id===id);
  if(!e||!eventConditionsMet(e))throw Error("出身事件條件失敗："+origin+"/"+id);
  const pool=randomEvents.filter(x=>eventConditionsMet(x)&&(game.eventCooldowns[x.id]||0)<=game.lifeQuarters);
  const i=pool.findIndex(x=>x.id===id);if(i<0)throw Error("目標事件不在抽選池："+origin+"/"+id);
  const w=pool.map(x=>x.category==="daily"?1.4:x.category==="region"&&x.trigger.regions?1.8:1);
  const total=w.reduce((s,n)=>s+n,0),n=(w.slice(0,i).reduce((s,v)=>s+v,0)+w[i]/2)/total;
  const q=[0.1,n];Math.random=()=>q.length?q.shift():0.99;pickRandomEvent();
  const selected=game.activeEventId;render();
  return {selected,condition:eventConditionsMet(e),notice:document.querySelector("#choices .notice")?.textContent||"",options:[...document.querySelectorAll("#choices button")].map(b=>b.innerText.trim())};
 },{origin,id});
}
(async()=>{
 let browser,page;const errors=[];
 try{
  browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:390,height:844}});
  page.on("pageerror",e=>errors.push(e.message));
  await page.route("**/cdn.jsdelivr.net/**",r=>r.fulfill({status:200,contentType:"application/javascript",body:""}));
  await page.route("**/supabase-config.js",r=>r.fulfill({status:200,contentType:"application/javascript",body:"window.GAME_SUPABASE_CONFIG=null;"}));
  await page.goto(BASE+"/sanguo/index.html",{waitUntil:"domcontentloaded"});
  assert.match(await page.title(),/三國浮生錄/);
  await page.locator("#name").fill("瀏覽器驗收角色");await page.locator("#start").click();await page.locator("#game").waitFor({state:"visible"});
  console.log("PASS：Chromium 載入遊戲並開始單人角色。");
  const response=await page.request.get(BASE+"/sanguo/events-66.json");assert.equal(response.status(),200);
  const external=await response.json(),inline=await page.evaluate(()=>eventCatalog);
  assert.deepEqual(inline,external,"HTML 內嵌事件與 JSON 必須一致");assert.equal(external.length,73);assert.equal(new Set(external.map(e=>e.id)).size,73);
  const originResults=[];
  for(const [origin,id,title] of CASES){
   const r=await selectEvent(page,origin,id);assert.equal(r.condition,true,origin+" 條件");assert.equal(r.selected,id,origin+" 抽選結果");
   assert.ok(r.notice.includes(title),origin+" 畫面事件標題");assert.ok(r.options.length>0,origin+" 事件選項");
   originResults.push({origin,eventId:r.selected,title,options:r.options.length});
  }
  console.log("PASS：八種出身事件均由實際事件抽選器選中並顯示。");
  await page.evaluate(()=>{game.stats.knowledge=30;game.stats.renown=10;game.aptitude.learning=1;game.aptitude.social=1;});
  await selectEvent(page,"官宦世家",67);
  const before=await page.evaluate(()=>({knowledge:game.stats.knowledge,renown:game.stats.renown}));
  await page.locator("#choices button").filter({hasText:"接受差事"}).click();await page.waitForTimeout(350);
  const after=await page.evaluate(()=>({knowledge:game.stats.knowledge,renown:game.stats.renown,month:game.month,titles:game.log.map(x=>x.title)}));
  assert.equal(after.knowledge,before.knowledge+2,"學識結算");assert.equal(after.renown,before.renown+1,"名聲結算");
  assert.ok(after.titles.includes("官府來訪｜接受差事"),"事件結果紀錄");assert.equal(after.month,4,"事件選擇推進一季");
  console.log("PASS：事件選項數值、季度與人生紀錄正確結算。");
  await page.evaluate(()=>{Math.random=()=>0.99;game.stats.health=50;game.stats.family=50;game.aptitude.constitution=1;game.aptitude.social=1;game.lastFamilyCareQuarter=game.lifeQuarters;render();});
  const pre=await page.evaluate(()=>({month:game.month,q:game.lifeQuarters,health:game.stats.health,family:game.stats.family}));
  await page.locator("#choices button").filter({hasText:"歇息片刻"}).click();await page.waitForTimeout(350);
  const post=await page.evaluate(()=>({month:game.month,q:game.lifeQuarters,health:game.stats.health,family:game.stats.family,titles:game.log.map(x=>x.title)}));
  assert.equal(post.q,pre.q+1);assert.equal(post.month,pre.month+3);assert.equal(post.health,pre.health+2);assert.equal(post.family,pre.family+1);assert.ok(post.titles.includes("歇息片刻"));
  const saved=await page.evaluate(()=>{const d=JSON.parse(localStorage.getItem("sanguo-save-"+game.id)||"null"),last=JSON.parse(localStorage.getItem("sanguo-last")||"null");return{exists:!!d,lastMatches:!!last&&last.id===game.id,snapshot:{id:game.id,year:game.year,month:game.month,age:game.age,origin:game.origin,q:game.lifeQuarters,stats:{...game.stats}}};});
  assert.equal(saved.exists,true);assert.equal(saved.lastMatches,true);console.log("PASS：季度日常行動正常，且角色存檔已寫入。");
  await page.reload({waitUntil:"domcontentloaded"});await page.locator("#continueSaved").waitFor({state:"visible"});await page.locator("#continueSaved").click();await page.locator("#game").waitFor({state:"visible"});
  const restored=await page.evaluate(()=>({id:game.id,year:game.year,month:game.month,age:game.age,origin:game.origin,q:game.lifeQuarters,stats:{...game.stats},titles:game.log.map(x=>x.title)}));
  for(const k of ["id","year","month","age","origin","q"])assert.equal(restored[k],saved.snapshot[k],"恢復欄位 "+k);
  assert.deepEqual(restored.stats,saved.snapshot.stats);assert.ok(restored.titles.includes("接續人生"));
  console.log("PASS：重新載入後角色、數值、進度與紀錄成功恢復。");
  const legacy=await page.evaluate(()=>{game.origin="佃農之家";game.activeEventId=6;game.eventCooldowns={};game.eventDone=[];const condition=eventConditionsMet(eventCatalog.find(e=>e.id===6));render();return{condition,notice:document.querySelector("#choices .notice")?.textContent||""};});
  assert.equal(legacy.condition,true);assert.ok(legacy.notice.includes("田地收成不佳"));
  await page.reload({waitUntil:"domcontentloaded"});await page.locator("#continueSaved").waitFor({state:"visible"});await page.locator("#continueSaved").click();
  const old=await page.evaluate(()=>({origin:game.origin,id:game.activeEventId,condition:eventConditionsMet(eventCatalog.find(e=>e.id===6)),notice:document.querySelector("#choices .notice")?.textContent||""}));
  assert.equal(old.origin,"佃農之家");assert.equal(old.id,6);assert.equal(old.condition,true);assert.ok(old.notice.includes("田地收成不佳"));assert.deepEqual(errors,[]);
  console.log("PASS：舊出身存檔相容；瀏覽器驗收全部通過。");
  console.log(JSON.stringify({status:"PASS",branch:"design/sanguo-world-event-rules",eventCount:external.length,originEvents:originResults,tests:["Chromium 載入","八種出身事件抽選與顯示","事件選項結算","季度日常行動","存檔恢復","舊出身相容","無未處理 JavaScript 錯誤"]},null,2));
 }catch(e){console.error("BROWSER ACCEPTANCE FAILED:",e&&e.stack?e.stack:e);if(page)try{await page.screenshot({path:"/tmp/sanguo-browser-acceptance-failure.png",fullPage:true});}catch(_){}process.exitCode=1;}
 finally{if(browser)await browser.close();}
})();