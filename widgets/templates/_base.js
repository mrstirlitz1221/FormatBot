var W=window.TelegramWidget;
function $(i){return document.getElementById(i);}
function D(){try{return JSON.parse(W&&W.chatData)||{};}catch(e){return {};}}
function say(t,e){var m=$('ms');if(m){m.textContent=t||'';m.className='ms'+(e?' er':'');}}
var ER={NOT_ALLOWED:'[[js:e_na]]',RATE_LIMITED:'[[js:e_rl]]',TIMEOUT:'[[js:e_to]]',BUSY:'[[js:e_busy]]'};
function hap(){try{W.HapticFeedback.impactOccurred('light');}catch(e){}}
function ask(d,ok){if(!W||W.isForward||W.isPreview){say('[[js:e_na]]',1);return;}hap();say('[[js:wait]]');
W.request(d).then(function(a){var o={};try{o=JSON.parse(a.result)||{};}catch(e){o={m:a.result};}say(o.m||'',o.e);if(ok&&!o.e)ok(o);},
function(e){say(ER[e.code]||'[[js:e_fail]]',1);});}
function fs(b){var u=['[[js:u_b]]','[[js:u_kb]]','[[js:u_mb]]','[[js:u_gb]]'],i=0;b=+b||0;while(b>=1024&&i<3){b/=1024;i++;}return (i?b.toFixed(1):b)+' '+u[i];}
function el(t,c,x){var e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e;}
