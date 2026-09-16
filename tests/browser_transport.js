// TEST ONLY. This environment blocks browser navigation. HTTP calls still reach
// the real server through Playwright's Python transport; no application response
// is mocked. Native browser cookies, network fetch and EventSource are NOT tested
// in this mode. Ordered event delivery uses the real server's JSON event endpoint.
window.fetch=async function(url,options={}){
 const raw=await window.testHttp(String(url),options);
 return new Response(raw.body,{status:raw.status,headers:raw.headers});
};
window.EventSource=class TestEventTransport{
 constructor(url){this.url=url;this.listeners=new Map();this.closed=false;this.poll()}
 addEventListener(type,fn){if(!this.listeners.has(type))this.listeners.set(type,[]);this.listeners.get(type).push(fn)}
 close(){this.closed=true;clearTimeout(this.timer)}
 async poll(){if(this.closed)return;
  try{const response=await fetch(this.url+'&format=json');if(!response.ok)throw Error('HTTP '+response.status);const result=await response.json();
   for(const e of result.events){if(this.closed)break;for(const fn of this.listeners.get(e.type)||[])fn({data:JSON.stringify(e.data),lastEventId:String(e.seq)});this.url=this.url.replace(/since=\d+/,'since='+e.seq)}
  }catch(e){this.onerror?.(e)}
  if(!this.closed)this.timer=setTimeout(()=>this.poll(),70);
 }
};
void 0;
